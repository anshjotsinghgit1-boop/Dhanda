import asyncio
import logging
from datetime import datetime, timezone
from aiogram import F, Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from app.db import get_pool
from app.club_live import club_battle_tick
from app.club_competitions import open_level_competitions, competition_lobby_tick
from app.mining_team_wars import finalize_mining_event, mining_team_tick, register_mining_team_handlers

log = logging.getLogger(__name__)
MINING_INTERVAL = 7200
CLUB_INTERVAL = 3600

async def register_mining_group(chat_id: int, title: str):
    async with get_pool().acquire() as conn:
        await conn.execute('INSERT INTO mining_groups(chat_id,title) VALUES($1,$2) ON CONFLICT(chat_id) DO UPDATE SET title=EXCLUDED.title', chat_id, (title or 'Mining group')[:120])

def join_kb(event_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ JOIN MINING", callback_data=f"tmj_{event_id}", style="success")],
        [InlineKeyboardButton(text="🏆 TOP MINING GROUPS", callback_data="top_mining_groups", style="primary")]
    ])

def boxes_kb(prefix, event_id, round_no):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 Box {n}", callback_data=f"{prefix}_{event_id}_{round_no}_{n}") for n in range(start, start+3)]
        for start in (1,4,7)
    ])

async def notify_players(bot, message, markup=None):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT telegram_id FROM players")
    for row in rows:
        try:
            await bot.send_message(row["telegram_id"], message, reply_markup=markup)
        except Exception:
            pass

_countdown_announced = set()


async def announce_countdowns(bot: Bot, now: int):
    """Broadcast 5-minute and 1-minute event reminders once per event cycle."""
    for event_name, interval, emoji, title in (
        ("mining", MINING_INTERVAL, "⛏️", "Mining lobby"),
        ("club", CLUB_INTERVAL, "🏛️", "Club battle queue"),
    ):
        remaining = interval - (now % interval)
        threshold = 300 if 295 < remaining <= 300 else 60 if 55 < remaining <= 60 else None
        if threshold is None:
            continue
        cycle = now // interval
        key = (event_name, cycle, threshold)
        if key in _countdown_announced:
            continue
        _countdown_announced.add(key)
        msg = f"{emoji} <b>{title} opens in {threshold // 60} minute(s)!</b>\n"
        if event_name == "mining":
            msg += "⏳ Join window: 5 minutes · minimum 3 players · top 3 or top 5 qualify by net worth."
            async with get_pool().acquire() as conn:
                groups = await conn.fetch("SELECT chat_id FROM mining_groups")
            for group in groups:
                try:
                    await bot.send_message(group["chat_id"], msg)
                except Exception:
                    log.exception("Mining countdown announcement failed for group %s", group["chat_id"])
        else:
            msg += "⚔️ Unlocks at business level 12 · same-level matchmaking · 15 seconds per round."
        await notify_players(bot, msg)
        # Keep the in-memory dedupe set bounded during long-running Termux sessions.
        if len(_countdown_announced) > 500:
            current_cycles = now // MINING_INTERVAL
            _countdown_announced.difference_update({
                item for item in _countdown_announced if item[1] < current_cycles - 2
            })


async def timed_scheduler(bot: Bot):
    last_mining = int(datetime.now(timezone.utc).timestamp()) // MINING_INTERVAL
    last_club = int(datetime.now(timezone.utc).timestamp()) // CLUB_INTERVAL
    while True:
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            await announce_countdowns(bot, now)
            ms, cs = now // MINING_INTERVAL, now // CLUB_INTERVAL
            if ms != last_mining:
                last_mining = ms
                async with get_pool().acquire() as conn:
                    groups = await conn.fetch("SELECT chat_id,title FROM mining_groups")
                for group in groups:
                    try:
                        async with get_pool().acquire() as conn:
                            # A group's previous reward ends as soon as its next mining begins.
                            await conn.execute("UPDATE mining_group_rewards SET expires_at=NOW() WHERE chat_id=$1", group["chat_id"])
                            event_id = await conn.fetchval("INSERT INTO timed_mining_events(chat_id,opens_at,closes_at) VALUES($1,NOW(),NOW()+INTERVAL '5 minutes') RETURNING id", group["chat_id"])
                        await bot.send_message(group["chat_id"], f"⛏️ <b>MINING LOBBY OPEN</b> · #{event_id}\n━━━━━━━━━━━━━━━━━━\n⏳ <b>5:00 JOIN WINDOW</b>\n👥 Minimum 3 players. Fewer than 3 = event skipped.\n🏆 3–4 applicants: top 3 by net worth qualify.\n💎 5+ applicants: top 5 by net worth qualify.\n📦 Tap JOIN MINING below. Start the bot in DM first.", reply_markup=join_kb(event_id))
                    except Exception:
                        log.exception("Mining event failed for group %s", group["chat_id"])
                await notify_players(bot, "⛏️ Mining is LIVE in your registered group! You have 5 minutes to join. Open the group event message and tap JOIN MINING.")
            if cs != last_club:
                last_club = cs
                await open_level_competitions(bot)
            async with get_pool().acquire() as conn:
                due = await conn.fetch("SELECT id,chat_id FROM timed_mining_events WHERE status='joining' AND closes_at<=NOW()")
            for event in due:
                try:
                    await finalize_mining_event(bot, int(event["id"]), int(event["chat_id"]))
                except Exception:
                    log.exception("Could not finalize mining event %s", event["id"])
            try:
                await mining_team_tick(bot)
                from app.mining_team_wars import matchmake_waiting_teams
                await matchmake_waiting_teams(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Cross-group mining war tick failed")
            try:
                await club_battle_tick(bot)
                await competition_lobby_tick(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Club competition tick failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Timed event scheduler error")
        await asyncio.sleep(5)

def register_timed_handlers(bot: Bot, dp: Dispatcher):
    register_mining_team_handlers(bot, dp)
    @dp.callback_query(F.data.startswith("tmj_"))
    async def mining_join(c: CallbackQuery):
        event_id = int(c.data.rsplit("_",1)[1])
        if c.message.chat.type not in ("group","supergroup"):
            await c.answer("Join in the mining group.", show_alert=True); return
        async with get_pool().acquire() as conn:
            event = await conn.fetchrow("SELECT * FROM timed_mining_events WHERE id=$1 AND chat_id=$2 AND status='joining' AND closes_at>NOW()", event_id, c.message.chat.id)
            player = await conn.fetchval("SELECT 1 FROM players WHERE telegram_id=$1", c.from_user.id)
            if not event or not player:
                await c.answer("Mining is closed, or you need to /start the bot in DM first.", show_alert=True); return
            await conn.execute(
                """INSERT INTO mining_group_members(chat_id,player_id,last_seen_at)
                   SELECT $1,telegram_id,NOW() FROM players WHERE telegram_id=$2
                   ON CONFLICT(chat_id,player_id) DO UPDATE SET last_seen_at=NOW()""",
                c.message.chat.id, c.from_user.id,
            )
            await conn.execute("INSERT INTO timed_mining_players(event_id,player_id) VALUES($1,$2) ON CONFLICT DO NOTHING", event_id, c.from_user.id)
            count = await conn.fetchval("SELECT COUNT(*) FROM timed_mining_players WHERE event_id=$1", event_id)
        await c.answer(f"Joined mining! {count} player(s) joined.")

