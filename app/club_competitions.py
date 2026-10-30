"""Level-specific club competitions: five-minute lobbies and two NPC matches per player."""
import json
import logging
import random
import math
from datetime import datetime, timezone
from aiogram import F, Bot, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from app.competition_images import render_roster, render_competition_result
from app.db import get_pool

log = logging.getLogger(__name__)
ROUND_SECONDS = 15
RANK = {"money": 2, "normal": 1, "empty": 0}
ICONS = {"money": "💰", "normal": "⚪", "empty": "🕳"}


def _layout(seed):
    values = ["money"] * 3 + ["normal"] * 3 + ["empty"] * 3
    random.Random(seed).shuffle(values)
    return values


def _boxes(match_id, opened_box=None, opened_kind=None):
    styles = ("primary", "success", "danger")
    labels = {"money": "💰 MONEY", "normal": "⚪ NORMAL", "empty": "🕳 EMPTY"}
    rows = []
    for row_index, start in enumerate((1, 4, 7)):
        row = []
        for n in range(start, start + 3):
            opened = n == opened_box
            label = labels.get(opened_kind, "📦 OPENED") if opened else f"📦 BOX {n}"
            row.append(InlineKeyboardButton(
                text=label,
                callback_data="ccp_done" if opened else f"ccp_{match_id}_{n}",
                style=styles[row_index],
            ))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_keyboard(competition_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏛 JOIN LEVEL COMPETITION", callback_data=f"ccj_{competition_id}", style="success")
    ]])


async def open_level_competitions(bot: Bot, schedule_key: str | None = None):
    """Open a five-minute lobby for every active level in one hourly IST slot."""
    if schedule_key is None:
        schedule_key = datetime.now().strftime('%Y-%m-%dT%H')

    async with get_pool().acquire() as conn:
        levels = await conn.fetch(
            "SELECT DISTINCT business_level FROM players WHERE is_npc=FALSE AND business_level>=12 ORDER BY business_level"
        )
    for item in levels:
        level = int(item["business_level"])
        async with get_pool().acquire() as conn:
            cid = await conn.fetchval(
                """INSERT INTO club_competitions(business_level,status,opens_at,closes_at,schedule_key)
                   VALUES($1,'joining',NOW(),NOW()+INTERVAL '5 minutes',$2)
                   ON CONFLICT(business_level,schedule_key) DO NOTHING RETURNING id""",
                level, schedule_key
            )
            if cid is None:
                continue
            await conn.execute(
                """INSERT INTO club_competition_participants(competition_id,player_id)
                   SELECT $1,telegram_id FROM players WHERE is_npc=TRUE AND business_level=$2
                   ON CONFLICT(competition_id,player_id) DO NOTHING""", cid, level
            )
            humans = await conn.fetch(
                "SELECT telegram_id FROM players WHERE is_npc=FALSE AND business_level=$1", level
            )
        body = (
            f"🏛 <b>LEVEL {level} CLUB COMPETITION</b> · #{cid}\n"
            "━━━━━━━━━━━━━━━━━━\n⏳ <b>5:00 JOIN WINDOW</b>\n"
            "Join now. After the lobby closes, you'll face two different opponents. "
            "Win both best-of-three matches to pass this level's competition."
        )
        for human in humans:
            try:
                await bot.send_message(human["telegram_id"], body, reply_markup=join_keyboard(cid))
            except Exception:
                log.debug("Competition notification failed for %s", human["telegram_id"])


async def _finish_competition_if_ready(conn, cid, level):
    remaining = await conn.fetchval(
        """SELECT COUNT(*) FROM club_competition_participants cp
           JOIN players p ON p.telegram_id=cp.player_id
           WHERE cp.competition_id=$1 AND p.is_npc=FALSE AND cp.completed_matches<2""", cid
    )
    if int(remaining or 0) == 0:
        await conn.execute(
            "UPDATE club_competitions SET status='finished',finished_at=NOW() WHERE id=$1", cid
        )


def _as_utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _edit_match_screen(bot, chat_id, message_id, text, markup=None):
    if not message_id:
        return
    try:
        await bot.edit_message_text(
            chat_id=int(chat_id), message_id=int(message_id),
            text=text, reply_markup=markup,
        )
    except Exception:
        log.debug("Could not edit live match screen %s for %s", message_id, chat_id, exc_info=True)


async def _refresh_active_match_screens(bot: Bot):
    """Edit countdown checkpoints on the same message for every active match."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT cm.*,c.business_level,p.display_name AS opponent_name
               FROM club_competition_matches cm
               JOIN club_competitions c ON c.id=cm.competition_id
               JOIN players p ON p.telegram_id=cm.player_b
               WHERE cm.status='active' AND cm.deadline_at IS NOT NULL AND cm.message_id IS NOT NULL"""
        )
    now = datetime.now(timezone.utc)
    for m in rows:
        deadline = _as_utc(m["deadline_at"])
        remaining = max(0, (deadline - now).total_seconds())
        seconds = math.ceil(remaining)
        if remaining > ROUND_SECONDS:
            checkpoint = 100 + max(1, math.ceil(remaining - ROUND_SECONDS))
            phase = "starting"
            label = f"⏳ MATCH STARTS IN {checkpoint - 100}..."
            markup = None
        else:
            checkpoint = seconds
            phase = "live"
            label = f"⏱️ {seconds} SECONDS LEFT"
            markup = _boxes(int(m["id"]), m["picked_a"],
                            json.loads(m["layout_a"])[int(m["picked_a"])-1] if m["picked_a"] else None)
        if phase == "live" and checkpoint not in {15, 10, 7, 5, 3, 1}:
            continue
        if int(m["countdown_mark"] or -1) == checkpoint:
            continue
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE club_competition_matches SET countdown_mark=$1 WHERE id=$2 AND countdown_mark<>$1",
                checkpoint, m["id"]
            )
        layout = json.loads(m["layout_a"])
        picked = int(m["picked_a"]) if m["picked_a"] else None
        reveal = f"\n🔓 You opened Box {picked}: {ICONS[layout[picked-1]} {layout[picked-1].upper()}" if picked else ""
        screen = (
            f"🏛 <b>LEVEL {m['business_level']} MATCH {m['match_number']}/2 · ROUND {m['round_number']}</b>\n"
            f"Opponent: {m['opponent_name']}\n"
            f"Score: {m['wins_a']}–{m['wins_b']}\n"
            f"{label}{reveal}\n"
            "Choose one colorful box before the shared round timer ends."
        )
        await _edit_match_screen(bot, m["player_a"], m["message_id"], screen, markup)


async def _resolve_match(bot: Bot, match_id: int, force_timeout=False):
    result_image = None
    result_caption = None
    edit_payload = None
    start_next = False
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            m = await conn.fetchrow("SELECT * FROM club_competition_matches WHERE id=$1", match_id)
            if not m or m["status"] != "active":
                return
            deadline = _as_utc(m["deadline_at"])
            now = datetime.now(timezone.utc)
            if not force_timeout or not deadline or now < deadline:
                return
            la, lb = json.loads(m["layout_a"]), json.loads(m["layout_b"])
            pa, pb = m["picked_a"], m["picked_b"]
            ka = la[int(pa)-1] if pa else None
            kb = lb[int(pb)-1] if pb else None
            if ka and kb:
                winner = m["player_a"] if RANK[ka] > RANK[kb] else m["player_b"] if RANK[kb] > RANK[ka] else None
            elif ka:
                winner = m["player_a"]
            elif kb:
                winner = m["player_b"]
            else:
                winner = None
            wa, wb, rn = int(m["wins_a"]), int(m["wins_b"]), int(m["round_number"])
            if winner == m["player_a"]:
                wa += 1
            elif winner == m["player_b"]:
                wb += 1
            round_result = (
                f"🏁 ROUND {rn} RESULT\n"
                f"You: {ICONS.get(ka, '⌛')}  ·  Opponent: {ICONS.get(kb, '⌛')}\n"
                f"{'🏆 You won this round!' if winner == m['player_a'] else '🤖 Opponent won this round.' if winner == m['player_b'] else '🤝 Round tied.'}\n"
                f"Score: {wa}–{wb}"
            )
            match_final = wa >= 2 or wb >= 2 or rn >= 3
            human_id = int(m["player_a"])
            level = int(await conn.fetchval(
                "SELECT business_level FROM club_competitions WHERE id=$1", m["competition_id"]
            ))
            opponent_name = await conn.fetchval(
                "SELECT display_name FROM players WHERE telegram_id=$1", m["player_b"]
            )
            if not match_final:
                next_a = json.dumps(_layout(f"{match_id}:{rn+1}:A"))
                next_b = json.dumps(_layout(f"{match_id}:{rn+1}:B"))
                await conn.execute(
                    """UPDATE club_competition_matches SET round_number=$1,wins_a=$2,wins_b=$3,
                       picked_a=NULL,picked_b=$4,layout_a=$5,layout_b=$6,
                       deadline_at=NOW()+INTERVAL '18 seconds',countdown_mark=-1 WHERE id=$7""",
                    rn+1, wa, wb, random.randint(1,9), next_a, next_b, match_id
                )
                edit_payload = (
                    f"🏛 <b>LEVEL {level} MATCH {m['match_number']}/2</b>\n{opponent_name}\n\n"
                    f"{round_result}\n\n⏳ Next round starts in 3..."
                )
            else:
                match_winner = m["player_a"] if wa > wb else m["player_b"] if wb > wa else None
                await conn.execute(
                    """UPDATE club_competition_matches SET wins_a=$1,wins_b=$2,status='finished',
                       winner_id=$3,finished_at=NOW() WHERE id=$4""", wa, wb, match_winner, match_id
                )
                await conn.execute(
                    """UPDATE club_competition_participants SET completed_matches=completed_matches+1,
                       matches_won=matches_won+$1 WHERE competition_id=$2 AND player_id=$3""",
                    1 if match_winner == m["player_a"] else 0, m["competition_id"], human_id
                )
                state = await conn.fetchrow(
                    "SELECT completed_matches,matches_won,passed FROM club_competition_participants WHERE competition_id=$1 AND player_id=$2",
                    m["competition_id"], human_id
                )
                if int(m["match_number"]) == 1:
                    next_match = await conn.fetchrow(
                        """SELECT id,player_b FROM club_competition_matches
                           WHERE competition_id=$1 AND player_a=$2 AND match_number=2 AND status='active'""",
                        m["competition_id"], human_id
                    )
                    if next_match:
                        await conn.execute(
                            """UPDATE club_competition_matches SET deadline_at=NOW()+INTERVAL '18 seconds',
                               message_id=$1,countdown_mark=-1 WHERE id=$2""",
                            m["message_id"], next_match["id"]
                        )
                        next_name = await conn.fetchval(
                            "SELECT display_name FROM players WHERE telegram_id=$1", next_match["player_b"]
                        )
                        edit_payload = (
                            f"🏛 <b>LEVEL {level} MATCH 1/2 RESULT</b>\n{opponent_name}\n"
                            f"Score: {wa}–{wb}\n"
                            f"{'🏆 Match won!' if match_winner == human_id else '❌ Match not won.'}\n\n"
                            f"⏳ MATCH 2/2 — {next_name}\nStarting in 3..."
                        )
                        start_next = True
                else:
                    passed = int(state["matches_won"]) == 2
                    await conn.execute(
                        """UPDATE club_competition_participants SET passed=$1
                           WHERE competition_id=$2 AND player_id=$3""",
                        passed, m["competition_id"], human_id
                    )
                    if passed:
                        await conn.execute(
                            "UPDATE players SET club_completed_level=$1 WHERE telegram_id=$2 AND business_level=$1",
                            level, human_id
                        )
                    await _finish_competition_if_ready(conn, int(m["competition_id"]), level)
                    rows = await conn.fetch(
                        """SELECT cm.wins_a,cm.wins_b,cm.winner_id,p.display_name AS opponent_name
                           FROM club_competition_matches cm JOIN players p ON p.telegram_id=cm.player_b
                           WHERE cm.competition_id=$1 AND cm.player_a=$2 ORDER BY cm.match_number""",
                        m["competition_id"], human_id
                    )
                    result_matches = [
                        {"wins_a": int(row["wins_a"]), "wins_b": int(row["wins_b"]),
                         "won": row["winner_id"] == human_id, "opponent_name": row["opponent_name"]}
                        for row in rows
                    ]
                    player_name = await conn.fetchval(
                        "SELECT display_name FROM players WHERE telegram_id=$1", human_id
                    ) or "Player"
                    result_image = await render_competition_result(
                        bot, level, player_name, result_matches, passed
                    )
                    result_caption = (
                        f"🏛 <b>LEVEL {level} COMPETITION COMPLETE</b>\n"
                        f"{'🎉 PASSED — both matches won!' if passed else '❌ NOT PASSED — both match wins were required.'}"
                    )
                    edit_payload = (
                        f"🏛 <b>LEVEL {level} COMPETITION COMPLETE</b>\n"
                        f"{'🎉 PASSED — both matches won!' if passed else '❌ NOT PASSED — try the next hourly competition.'}"
                    )
    if edit_payload:
        await _edit_match_screen(bot, human_id, m["message_id"], edit_payload, None)
    if result_image is not None:
        try:
            await bot.send_photo(
                human_id, BufferedInputFile(result_image, filename=f"level_{level}_competition_result.png"),
                caption=result_caption,
            )
        except Exception:
            log.exception("Could not send final competition image to %s", human_id)


async def _start_first_match(bot: Bot, cid: int, level: int, pid: int, match_id: int, opponent: int):
    opponent_name = "NPC Opponent"
    async with get_pool().acquire() as conn:
        opponent_name = await conn.fetchval("SELECT display_name FROM players WHERE telegram_id=$1", opponent) or opponent_name
    message = await bot.send_message(
        pid,
        f"🏛 <b>LEVEL {level} MATCH 1/2</b>\nOpponent: {opponent_name}\n"
        "Best of three · first to two round wins.\n⏳ Match starts in 3...",
    )
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE club_competition_matches SET message_id=$1 WHERE id=$2",
            message.message_id, match_id
        )


async def _refresh_unused():
    return


def ICONs(kind):
    return ICONS.get(kind, "⌛")


async def _send_roster_updates(bot: Bot):
    async with get_pool().acquire() as conn:
        lobbies = await conn.fetch(
            "SELECT id,business_level,opens_at,roster_updates_sent FROM club_competitions WHERE status='joining'"
        )
    now = datetime.now(timezone.utc)
    for lobby in lobbies:
        opened = lobby["opens_at"]
        if isinstance(opened, str):
            opened = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        sent = int(lobby["roster_updates_sent"] or 0)
        elapsed = (now - opened).total_seconds()
        update_no = min(4, int(elapsed // 60))
        if sent >= 4 or update_no <= sent:
            continue
        cid, level = int(lobby["id"]), int(lobby["business_level"])
        async with get_pool().acquire() as conn:
            participants = await conn.fetch(
                """SELECT p.telegram_id,p.display_name,p.is_npc FROM club_competition_participants cp
                   JOIN players p ON p.telegram_id=cp.player_id
                   WHERE cp.competition_id=$1 ORDER BY p.is_npc,p.display_name""", cid
            )
        if not participants or not any(not person["is_npc"] for person in participants):
            continue
        try:
            image = await render_roster(bot, level, participants)
            for person in participants:
                if person["is_npc"]:
                    continue
                try:
                    await bot.send_photo(
                        person["telegram_id"],
                        BufferedInputFile(image, filename=f"level_{level}_roster_{update_no}.png"),
                        caption=f"🏛 <b>LEVEL {level} ROSTER UPDATE {update_no}/4</b>\n👥 {len(participants)} participants registered",
                    )
                except Exception:
                    log.debug("Roster update delivery failed for %s", person["telegram_id"])
        except Exception:
            log.exception("Could not render roster image for competition %s", cid)
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE club_competitions SET roster_updates_sent=$1 WHERE id=$2 AND roster_updates_sent=$3",
                update_no, cid, sent
            )


async def competition_lobby_tick(bot: Bot):
    """Close lobbies, create two distinct NPC matches per human, and advance rounds."""
    await _refresh_active_match_screens(bot)
    async with get_pool().acquire() as conn:
        due = await conn.fetch("SELECT id,business_level FROM club_competitions WHERE status='joining' AND closes_at<=NOW()")
        active = await conn.fetch("SELECT id FROM club_competition_matches WHERE status='active' AND deadline_at<=NOW()")
    for item in due:
        cid, level = int(item["id"]), int(item["business_level"])
        async with get_pool().acquire() as conn:
            humans = await conn.fetch(
                """SELECT cp.player_id FROM club_competition_participants cp
                   JOIN players p ON p.telegram_id=cp.player_id
                   WHERE cp.competition_id=$1 AND p.is_npc=FALSE ORDER BY cp.joined_at,cp.player_id""", cid
            )
            npcs = await conn.fetch(
                "SELECT telegram_id FROM players WHERE is_npc=TRUE AND business_level=$1 ORDER BY telegram_id", level
            )
            if not humans or len(npcs) < 2:
                await conn.execute("UPDATE club_competitions SET status='cancelled',finished_at=NOW() WHERE id=$1", cid)
                continue
            await conn.execute("UPDATE club_competitions SET status='running' WHERE id=$1 AND status='joining'", cid)
            npc_ids = [int(n["telegram_id"]) for n in npcs]
            for idx, human in enumerate(humans):
                pid = int(human["player_id"])
                chosen = [npc_ids[idx % len(npc_ids)], npc_ids[(idx + 1) % len(npc_ids)]]
                for match_no, opponent in enumerate(chosen, start=1):
                    la = json.dumps(_layout(f"{cid}:{pid}:{match_no}:human"))
                    lb = json.dumps(_layout(f"{cid}:{pid}:{match_no}:npc"))
                    await conn.execute(
                        """INSERT INTO club_competition_matches
                           (competition_id,player_a,player_b,match_number,round_number,
                            layout_a,layout_b,picked_b,deadline_at)
                           VALUES($1,$2,$3,$4,1,$5,$6,$7,NOW()+INTERVAL '15 seconds')""",
                        cid, pid, opponent, match_no, la, lb, random.randint(1,9)
                    )
                    match_id = await conn.fetchval("SELECT last_insert_rowid()")
                    try:
                        await bot.send_message(
                            pid,
                            f"🏛 <b>LEVEL {level} MATCH {match_no}/2</b>\nOpponent: {await conn.fetchval('SELECT display_name FROM players WHERE telegram_id=$1', opponent)}\n"
                            f"Win this best-of-three match. First to 2 rounds wins. You have {ROUND_SECONDS} seconds per round.",
                            reply_markup=_boxes(int(match_id)),
                        )
                    except Exception:
                        log.debug("Could not send match to player %s", pid)
    for item in active:
        try:
            await _resolve_match(bot, int(item["id"]), force_timeout=True)
        except Exception:
            log.exception("Competition match %s failed to resolve", item["id"])


def register_competition_handlers(bot: Bot, dp: Dispatcher):
    @dp.callback_query(F.data.startswith("ccj_"))
    async def competition_join(c: CallbackQuery):
        try:
            cid = int(c.data.rsplit("_", 1)[1])
        except (TypeError, ValueError):
            await c.answer("Invalid competition.", show_alert=True)
            return
        async with get_pool().acquire() as conn:
            player = await conn.fetchrow("SELECT business_level,is_npc FROM players WHERE telegram_id=$1", c.from_user.id)
            competition = await conn.fetchrow(
                "SELECT * FROM club_competitions WHERE id=$1 AND status='joining' AND closes_at>NOW()", cid
            )
            if not player:
                await c.answer("Start the game with /start first.", show_alert=True)
                return
            if player["is_npc"]:
                await c.answer("NPC characters join automatically.", show_alert=True)
                return
            if not competition or int(player["business_level"]) != int(competition["business_level"]):
                await c.answer("This lobby is closed or belongs to another business level.", show_alert=True)
                return
            await conn.execute(
                "INSERT INTO club_competition_participants(competition_id,player_id) VALUES($1,$2) ON CONFLICT(competition_id,player_id) DO NOTHING",
                cid, c.from_user.id
            )
            count = await conn.fetchval("SELECT COUNT(*) FROM club_competition_participants WHERE competition_id=$1", cid)
        await c.answer(f"Registered! {count} participant(s) in this roster.", show_alert=True)

    @dp.callback_query(F.data.startswith("ccp_"))
    async def competition_pick(c: CallbackQuery):
        try:
            _, match_s, box_s = c.data.split("_")
            match_id, box_no = int(match_s), int(box_s)
        except (TypeError, ValueError):
            await c.answer("Invalid box.", show_alert=True)
            return
        if box_no not in range(1,10):
            await c.answer("Choose one of the nine boxes.", show_alert=True)
            return
        async with get_pool().acquire() as conn:
            m = await conn.fetchrow("SELECT * FROM club_competition_matches WHERE id=$1 AND status='active'", match_id)
            if not m or int(m["player_a"]) != c.from_user.id:
                await c.answer("This isn't your active match.", show_alert=True)
                return
            if m["picked_a"] is not None:
                await c.answer("You've already picked this round.", show_alert=True)
                return
            deadline = m["deadline_at"]
            if deadline and deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if deadline and datetime.now(timezone.utc) > deadline:
                await c.answer("Round time is over.", show_alert=True)
                return
            await conn.execute("UPDATE club_competition_matches SET picked_a=$1 WHERE id=$2 AND picked_a IS NULL", box_no, match_id)
            picked = await conn.fetchrow("SELECT picked_a,picked_b FROM club_competition_matches WHERE id=$1", match_id)
        await c.answer("Box selected.")
        if picked and picked["picked_a"] is not None and picked["picked_b"] is not None:
            await _resolve_match(bot, match_id)
