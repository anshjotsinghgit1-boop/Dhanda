import asyncio
import logging
from datetime import datetime, timezone
from aiogram import F, Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from app.db import get_pool
from app.club_live import club_battle_tick
from app.mining_team_wars import finalize_mining_event, mining_team_tick, register_mining_team_handlers

log = logging.getLogger(__name__)
MINING_INTERVAL = 7200
CLUB_INTERVAL = 3600

async def register_mining_group(chat_id: int, title: str):
    async with get_pool().acquire() as conn:
        await conn.execute('INSERT INTO mining_groups(chat_id,title) VALUES($1,$2) ON CONFLICT(chat_id) DO UPDATE SET title=EXCLUDED.title', chat_id, (title or 'Mining group')[:120])

def join_kb(event_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⛏ JOIN MINING", callback_data=f"tmj_{event_id}")]])

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

async def timed_scheduler(bot: Bot):
    last_mining = int(datetime.now(timezone.utc).timestamp()) // MINING_INTERVAL
    last_club = int(datetime.now(timezone.utc).timestamp()) // CLUB_INTERVAL
    while True:
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            ms, cs = now // MINING_INTERVAL, now // CLUB_INTERVAL
            if ms != last_mining:
                last_mining = ms
                async with get_pool().acquire() as conn:
                    groups = await conn.fetch("SELECT chat_id,title FROM mining_groups")
                for group in groups:
                    try:
                        async with get_pool().acquire() as conn:
                            event_id = await conn.fetchval("INSERT INTO timed_mining_events(chat_id,opens_at,closes_at) VALUES($1,NOW(),NOW()+INTERVAL '5 minutes') RETURNING id", group["chat_id"])
                        await bot.send_message(group["chat_id"], f"⛏ <b>MINING OPEN</b> #{event_id}\nJoin within 5 minutes. At least 3 players are required. Top 3 qualify from 3–4 applicants; top 5 qualify from 5 or more.", reply_markup=join_kb(event_id))
                    except Exception:
                        log.exception("Mining event failed for group %s", group["chat_id"])
                await notify_players(bot, "⛏ Mining has started in your registered groups. You have 5 minutes to join.")
            if cs != last_club:
                last_club = cs
                await notify_players(bot, "🏛 Club battle is open! Join the queue for a club match.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏛 JOIN CLUB BATTLE", callback_data="cbq_join")]]))
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
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Club battle timeout processing failed")
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
            await conn.execute("INSERT INTO timed_mining_players(event_id,player_id) VALUES($1,$2) ON CONFLICT DO NOTHING", event_id, c.from_user.id)
            count = await conn.fetchval("SELECT COUNT(*) FROM timed_mining_players WHERE event_id=$1", event_id)
        await c.answer(f"Joined mining! {count} player(s) joined.")

