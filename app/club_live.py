"""Live, equal-level club box matches. The database owns the round deadline and picks."""
import asyncio
import json
import random
from datetime import datetime, timezone
from aiogram import F, Bot, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from app.db import get_pool

ROUND_SECONDS = 15
RANK = {"money": 2, "normal": 1, "empty": 0}
ICON = {"money": "💰", "normal": "⚪", "empty": "🕳"}

def boxes(match_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {n}", callback_data=f"clbp_{match_id}_{n}") for n in range(start, start+3)]
        for start in (1,4,7)
    ])

def make_layout(seed):
    values = ["money"]*3 + ["normal"]*3 + ["empty"]*3
    random.Random(seed).shuffle(values)
    return values

async def _resolve(bot: Bot, match_id: int, timed_out: bool = False):
    """Resolve only when both players picked or the server deadline has passed."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            m = await conn.fetchrow("SELECT * FROM club_live_matches WHERE id=$1 FOR UPDATE", match_id)
            if not m or m["status"] != "active":
                return
            now = datetime.now(timezone.utc)
            deadline = m["deadline_at"]
            if deadline and deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if m["picked_a"] is None or m["picked_b"] is None:
                if not timed_out or (deadline and now < deadline):
                    return
            la, lb = json.loads(m["layout_a"]), json.loads(m["layout_b"])
            ka = la[m["picked_a"]-1] if m["picked_a"] else None
            kb = lb[m["picked_b"]-1] if m["picked_b"] else None
            if ka and kb:
                winner = m["player_a"] if RANK[ka] > RANK[kb] else m["player_b"] if RANK[kb] > RANK[ka] else None
            elif ka:
                winner = m["player_a"]
            elif kb:
                winner = m["player_b"]
            else:
                winner = None
            wa, wb = int(m["wins_a"]), int(m["wins_b"])
            if winner == m["player_a"]: wa += 1
            elif winner == m["player_b"]: wb += 1
            rn = int(m["round_number"])
            await conn.execute(
                "INSERT INTO club_live_rounds(match_id,round_number,player_a_kind,player_b_kind,winner_id) VALUES($1,$2,$3,$4,$5) ON CONFLICT(match_id,round_number) DO NOTHING",
                match_id, rn, ka, kb, winner)
            final = wa >= 2 or wb >= 2 or rn >= 3
            if final:
                match_winner = m["player_a"] if wa > wb else m["player_b"] if wb > wa else None
                await conn.execute("UPDATE club_live_matches SET wins_a=$1,wins_b=$2,status='finished',winner_id=$3,finished_at=NOW() WHERE id=$4", wa, wb, match_winner, match_id)
                if match_winner:
                    loser = m["player_b"] if match_winner == m["player_a"] else m["player_a"]
                    await conn.execute("UPDATE players SET club_battle_wins=club_battle_wins+1 WHERE telegram_id=$1", match_winner)
                    await conn.execute("UPDATE players SET club_battle_wins=0 WHERE telegram_id=$1", loser)
            else:
                await conn.execute("UPDATE club_live_matches SET round_number=$1,wins_a=$2,wins_b=$3,picked_a=NULL,picked_b=NULL,deadline_at=NOW()+( $4 * INTERVAL '1 second') WHERE id=$5", rn+1, wa, wb, ROUND_SECONDS, match_id)
            names = await conn.fetch("SELECT telegram_id,display_name FROM players WHERE telegram_id IN ($1,$2)", m["player_a"], m["player_b"])
            names_by_id = {r["telegram_id"]: r["display_name"] for r in names}
    round_line = f"Round {rn}: {ICON.get(ka, '⌛')} vs {ICON.get(kb, '⌛')} — " + (f"{names_by_id.get(winner, 'Player')} wins." if winner else "Draw.")
    if final:
        result = f"🏛 <b>CLUB BATTLE RESULT</b>\n{names_by_id.get(m['player_a'],'Player')}: {wa}/3 rounds\n{names_by_id.get(m['player_b'],'Player')}: {wb}/3 rounds\n\n" + (f"🏆 {names_by_id.get(match_winner,'Player')} wins! Win two matches against different opponents to unlock upgrades." if match_winner else "🤝 Match tied. Queue again for another opponent.")
        for pid in (m["player_a"], m["player_b"]):
            try: await bot.send_message(pid, result)
            except Exception: pass
    else:
        notice = f"🏛 <b>CLUB BATTLE · ROUND {rn} RESULT</b>\n{round_line}\nScore: {wa}–{wb}\nNext round starts now. You have {ROUND_SECONDS} seconds."
        for pid in (m["player_a"], m["player_b"]):
            try: await bot.send_message(pid, notice, reply_markup=boxes(match_id))
            except Exception: pass

async def club_battle_tick(bot: Bot):
    async with get_pool().acquire() as conn:
        due = await conn.fetch("SELECT id FROM club_live_matches WHERE status='active' AND deadline_at<=NOW()")
    for row in due:
        try: await _resolve(bot, int(row["id"]), timed_out=True)
        except Exception: pass

def register_club_live_handlers(bot: Bot, dp: Dispatcher):
    @dp.callback_query(F.data == "cbq_join")
    async def club_join(c: CallbackQuery):
        async with get_pool().acquire() as conn:
            p = await conn.fetchrow("SELECT business_level FROM players WHERE telegram_id=$1", c.from_user.id)
            if not p:
                await c.answer("Start the bot in private chat with /start first.", show_alert=True); return
            level = int(p["business_level"])
            if level < 12:
                await c.answer("Club battles unlock at business level 12.", show_alert=True); return
            active = await conn.fetchval("SELECT 1 FROM club_live_matches WHERE status='active' AND (player_a=$1 OR player_b=$1)", c.from_user.id)
            if active:
                await c.answer("Finish your current club battle first.", show_alert=True); return
            await conn.execute("INSERT INTO club_battle_queue(player_id) VALUES($1) ON CONFLICT(player_id) DO NOTHING", c.from_user.id)
            opponent = await conn.fetchrow("""SELECT q.player_id,p.business_level FROM club_battle_queue q
                JOIN players p ON p.telegram_id=q.player_id
                WHERE q.player_id<>$1 AND p.business_level=$2
                  AND NOT EXISTS (SELECT 1 FROM club_battles b WHERE
                    (b.player_a=$1 AND b.player_b=q.player_id) OR (b.player_b=$1 AND b.player_a=q.player_id))
                ORDER BY q.joined_at LIMIT 1""", c.from_user.id, level)
            if not opponent:
                count = await conn.fetchval("SELECT COUNT(*) FROM club_battle_queue WHERE player_id<>$1", c.from_user.id)
                await c.answer(f"Queued at level {level}. Waiting for an equal-level opponent ({count} waiting).", show_alert=True)
                return
            other = int(opponent["player_id"])
            await conn.execute("DELETE FROM club_battle_queue WHERE player_id IN ($1,$2)", c.from_user.id, other)
            la, lb = make_layout(f"{c.from_user.id}:{other}:{datetime.now(timezone.utc).timestamp()}"), make_layout(f"{other}:{c.from_user.id}:{datetime.now(timezone.utc).timestamp()}")
            match_id = await conn.fetchval("""INSERT INTO club_live_matches(player_a,player_b,layout_a,layout_b,deadline_at)
                VALUES($1,$2,$3,$4,NOW()+($5 * INTERVAL '1 second')) RETURNING id""",
                c.from_user.id, other, json.dumps(la), json.dumps(lb), ROUND_SECONDS)
            names = await conn.fetch("SELECT telegram_id,display_name FROM players WHERE telegram_id IN ($1,$2)", c.from_user.id, other)
            name_map = {r["telegram_id"]: r["display_name"] for r in names}
        intro = f"🏛 <b>LIVE CLUB BATTLE #{match_id}</b>\n{ name_map.get(c.from_user.id,'Player') } vs { name_map.get(other,'Player') }\n\nOpen one box in {ROUND_SECONDS} seconds. 💰 beats ⚪, ⚪ beats 🕳, 💰 beats 🕳. First to 2 round wins takes the match. Queue again to face a different opponent."
        for pid in (c.from_user.id, other):
            try: await bot.send_message(pid, intro, reply_markup=boxes(match_id))
            except Exception: pass
        await c.answer("Opponent found! Check your private chat with the bot.", show_alert=True)

    @dp.callback_query(F.data.startswith("clbp_"))
    async def club_pick(c: CallbackQuery):
        try: _, match_s, box_s = c.data.split("_"); match_id, box_no = int(match_s), int(box_s)
        except (ValueError, TypeError):
            await c.answer("Invalid box.", show_alert=True); return
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                m = await conn.fetchrow("SELECT * FROM club_live_matches WHERE id=$1 FOR UPDATE", match_id)
                if not m or m["status"] != "active":
                    await c.answer("This match has ended.", show_alert=True); return
                if c.from_user.id not in (m["player_a"],m["player_b"]):
                    await c.answer("This is not your match.", show_alert=True); return
                if m["deadline_at"] and datetime.now(timezone.utc) > (m["deadline_at"].replace(tzinfo=timezone.utc) if m["deadline_at"].tzinfo is None else m["deadline_at"]):
                    await c.answer("Round time is over.", show_alert=True); return
                field = "picked_a" if c.from_user.id == m["player_a"] else "picked_b"
                if m[field] is not None:
                    await c.answer("You already opened a box this round.", show_alert=True); return
                await conn.execute(f"UPDATE club_live_matches SET {field}=$1 WHERE id=$2 AND {field} IS NULL", box_no, match_id)
                ready = await conn.fetchrow("SELECT picked_a,picked_b FROM club_live_matches WHERE id=$1", match_id)
        await c.answer("Box selected. Waiting for your opponent…")
        if ready and ready["picked_a"] is not None and ready["picked_b"] is not None:
            await _resolve(bot, match_id)
