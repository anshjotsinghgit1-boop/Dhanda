"""Level-specific club competitions: five-minute lobbies and two NPC matches per player."""
import json
import logging
import random
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


def _boxes(match_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {n}", callback_data=f"ccp_{match_id}_{n}") for n in range(start, start + 3)]
        for start in (1, 4, 7)
    ])


def join_keyboard(competition_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏛 JOIN LEVEL COMPETITION", callback_data=f"ccj_{competition_id}", style="success")
    ]])


async def open_level_competitions(bot: Bot):
    """Open one five-minute lobby per active human business level."""
    async with get_pool().acquire() as conn:
        levels = await conn.fetch(
            "SELECT DISTINCT business_level FROM players WHERE is_npc=FALSE AND business_level>=12 ORDER BY business_level"
        )
    for item in levels:
        level = int(item["business_level"])
        async with get_pool().acquire() as conn:
            exists = await conn.fetchval(
                "SELECT id FROM club_competitions WHERE business_level=$1 AND status IN ('joining','running')",
                level,
            )
            if exists:
                continue
            cid = await conn.fetchval(
                """INSERT INTO club_competitions(business_level,status,opens_at,closes_at)
                   VALUES($1,'joining',NOW(),NOW()+INTERVAL '5 minutes') RETURNING id""", level
            )
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


async def _resolve_match(bot: Bot, match_id: int, force_timeout=False):
    result_matches = []
    player_name = 'Player'
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            m = await conn.fetchrow("SELECT * FROM club_competition_matches WHERE id=$1", match_id)
            if not m or m["status"] != "active":
                return
            deadline = m["deadline_at"]
            now = datetime.now(timezone.utc)
            if deadline and deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if m["picked_a"] is None and not force_timeout and deadline and now < deadline:
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
            final = wa >= 2 or wb >= 2 or rn >= 3
            if final:
                match_winner = m["player_a"] if wa > wb else m["player_b"] if wb > wa else None
                await conn.execute(
                    """UPDATE club_competition_matches SET wins_a=$1,wins_b=$2,status='finished',
                       winner_id=$3,finished_at=NOW() WHERE id=$4""", wa, wb, match_winner, match_id
                )
                await conn.execute(
                    """UPDATE club_competition_participants SET completed_matches=completed_matches+1,
                       matches_won=matches_won+$1 WHERE competition_id=$2 AND player_id=$3""",
                    1 if match_winner == m["player_a"] else 0, m["competition_id"], m["player_a"]
                )
                comp = await conn.fetchrow(
                    "SELECT business_level FROM club_competitions WHERE id=$1", m["competition_id"]
                )
                summary = await conn.fetchrow(
                    "SELECT completed_matches,matches_won FROM club_competition_participants WHERE competition_id=$1 AND player_id=$2",
                    m["competition_id"], m["player_a"]
                )
                if summary and int(summary["completed_matches"]) >= 2:
                    passed = int(summary["matches_won"]) == 2
                    await conn.execute(
                        """UPDATE club_competition_participants SET passed=$1
                           WHERE competition_id=$2 AND player_id=$3""",
                        passed, m["competition_id"], m["player_a"]
                    )
                    if passed:
                        await conn.execute(
                            "UPDATE players SET club_completed_level=$1 WHERE telegram_id=$2 AND business_level=$1",
                            comp["business_level"], m["player_a"]
                        )
                await _finish_competition_if_ready(conn, int(m["competition_id"]), int(comp["business_level"]))
            else:
                next_a = json.dumps(_layout(f"{match_id}:{rn+1}:A"))
                next_b = json.dumps(_layout(f"{match_id}:{rn+1}:B"))
                npc_pick = random.randint(1, 9)
                await conn.execute(
                    """UPDATE club_competition_matches SET round_number=$1,wins_a=$2,wins_b=$3,
                       picked_a=NULL,picked_b=$4,layout_a=$5,layout_b=$6,
                       deadline_at=NOW()+INTERVAL '15 seconds' WHERE id=$7""",
                    rn+1, wa, wb, npc_pick, next_a, next_b, match_id
                )
            human_id = int(m["player_a"])
            opponent_name = await conn.fetchval(
                "SELECT display_name FROM players WHERE telegram_id=$1", m["player_b"]
            )
            level = await conn.fetchval(
                "SELECT business_level FROM club_competitions WHERE id=$1", m["competition_id"]
            )
            state = await conn.fetchrow(
                "SELECT completed_matches,matches_won,passed FROM club_competition_participants WHERE competition_id=$1 AND player_id=$2",
                m["competition_id"], human_id
            )
            if state and int(state["completed_matches"]) >= 2:
                player_name = await conn.fetchval("SELECT display_name FROM players WHERE telegram_id=$1", human_id) or "Player"
                rows = await conn.fetch(
                    """SELECT cm.wins_a,cm.wins_b,cm.winner_id,p.display_name AS opponent_name
                       FROM club_competition_matches cm
                       JOIN players p ON p.telegram_id=cm.player_b
                       WHERE cm.competition_id=$1 AND cm.player_a=$2
                       ORDER BY cm.match_number""",
                    m["competition_id"], human_id
                )
                result_matches = [
                    {"wins_a": int(row["wins_a"]), "wins_b": int(row["wins_b"]),
                     "won": row["winner_id"] == human_id, "opponent_name": row["opponent_name"]}
                    for row in rows
                ]
    if final:
        match_line = f"🏛 <b>LEVEL {level} MATCH RESULT</b>\nOpponent: {opponent_name}\nScore: {wa}–{wb}\n" + (
            "🏆 You won this match!" if match_winner == human_id else "This match was not a win."
        )
        if state and int(state["completed_matches"]) >= 2:
            match_line += "\n\n" + ("<b>🎉 COMPETITION PASSED — both matches won!</b>" if state["passed"] else "<b>❌ COMPETITION NOT PASSED</b> — you needed two wins. Try the next Level competition.")
        else:
            match_line += f"\n\nMatch {int(state['completed_matches']) if state else 1}/2 complete. Your second match still counts, even if you lost this one."
        try:
            if state and int(state["completed_matches"]) >= 2 and len(result_matches) == 2:
                result_image = await render_competition_result(bot, int(level), player_name, result_matches, bool(state["passed"]))
                await bot.send_photo(
                    human_id,
                    BufferedInputFile(result_image, filename=f"level_{level}_competition_result.png"),
                    caption=match_line,
                )
            else:
                await bot.send_message(human_id, match_line)
        except Exception:
            log.exception("Could not send final competition result to %s", human_id)
    else:
        notice = (
            f"🏛 <b>LEVEL {level} MATCH · ROUND {rn}</b>\n"
            f"💰 {ICONs(ka)} vs {ICONs(kb)}\nScore: {wa}–{wb}\n"
            f"Choose a box within {ROUND_SECONDS} seconds."
        )
        try:
            await bot.send_message(human_id, notice, reply_markup=_boxes(match_id))
        except Exception:
            pass


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
    await _send_roster_updates(bot)
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
