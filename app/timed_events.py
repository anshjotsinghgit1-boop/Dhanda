import asyncio
import logging
from datetime import datetime, timezone
from aiogram import F, Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from app.db import get_pool
from app.club_live import club_battle_tick

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
                        await bot.send_message(group["chat_id"], f"⛏ <b>MINING OPEN</b> #{event_id}\nJoin within 5 minutes. Minimum 2 players. Choose your boxes in four rounds.", reply_markup=join_kb(event_id))
                    except Exception:
                        log.exception("Mining event failed for group %s", group["chat_id"])
                await notify_players(bot, "⛏ Mining has started in your registered groups. You have 5 minutes to join.")
            if cs != last_club:
                last_club = cs
                await notify_players(bot, "🏛 Club battle is open! Join the queue for a club match.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏛 JOIN CLUB BATTLE", callback_data="cbq_join")]]))
            async with get_pool().acquire() as conn:
                due = await conn.fetch("SELECT id,chat_id FROM timed_mining_events WHERE status='joining' AND closes_at<=NOW()")
            for event in due:
                async with get_pool().acquire() as conn:
                    players = await conn.fetch("SELECT p.telegram_id,p.display_name,p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth FROM timed_mining_players t JOIN players p ON p.telegram_id=t.player_id LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id WHERE t.event_id=$1 ORDER BY worth DESC", event["id"])
                    if len(players) < 2:
                        await conn.execute("UPDATE timed_mining_events SET status='skipped',finished_at=NOW() WHERE id=$1", event["id"])
                        msg = "Mining skipped: fewer than 2 players joined. Try the next event."
                    else:
                        await conn.execute("UPDATE timed_mining_events SET status='fighting' WHERE id=$1", event["id"])
                        msg = "⚔️ <b>MINING BATTLE</b>\nOpponents:\n" + "\n".join(f"• {p['display_name']} — {int(p['worth']):,} NW" for p in players) + "\n\nFour rounds! Each player chooses one box per round."
                await bot.send_message(event["chat_id"], msg, reply_markup=boxes_kb("tmr", event["id"], 1) if len(players)>=2 else None)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Timed event scheduler error")
        try:
            await club_battle_tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Club battle timeout processing failed")
        await asyncio.sleep(5)

def register_timed_handlers(bot: Bot, dp: Dispatcher):
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

    @dp.callback_query(F.data.startswith("tmr_"))
    async def mining_box(c: CallbackQuery):
        _, event_id, round_no, box_no = c.data.split("_")
        event_id, round_no, box_no = int(event_id), int(round_no), int(box_no)
        async with get_pool().acquire() as conn:
            joined = await conn.fetchval("SELECT 1 FROM timed_mining_players WHERE event_id=$1 AND player_id=$2", event_id, c.from_user.id)
            event = await conn.fetchrow("SELECT status FROM timed_mining_events WHERE id=$1", event_id)
            if not joined or not event or event["status"] != "fighting":
                await c.answer("You are not in this mining battle.", show_alert=True); return
            # A player's nine boxes contain three outcomes of each type per round.
            from random import Random
            layout = ["money"]*3 + ["empty"]*3 + ["normal"]*3
            Random(f"{event_id}:{round_no}:{c.from_user.id}").shuffle(layout)
            kind = layout[box_no-1]
            worth = await conn.fetchval("SELECT cash+stocks+CAST(gold_grams*10 AS BIGINT)+COALESCE((SELECT asset_value FROM player_asset_valuation WHERE player_id=$1),0) FROM players WHERE telegram_id=$1", c.from_user.id)
            temporary = round(int(worth or 0) * (1.2 if kind=="money" else .8 if kind=="empty" else 1))
            await conn.execute("INSERT INTO timed_mining_rounds(event_id,round_number,player_id,box_kind,temporary_net_worth) VALUES($1,$2,$3,$4,$5) ON CONFLICT(event_id,round_number,player_id) DO NOTHING", event_id, round_no, c.from_user.id, kind, temporary)
        desc = {"money":"Money box: +20% temporary battle NW","empty":"Empty box: -20% temporary battle NW","normal":"Normal box: temporary battle NW unchanged"}[kind]
        if round_no < 4:
            await c.message.answer(f"{c.from_user.full_name}: {desc}. Temporary NW: {temporary:,}", reply_markup=boxes_kb("tmr", event_id, round_no+1))
        else:
            async with get_pool().acquire() as conn:
                wins = await conn.fetchval("SELECT COUNT(*) FROM timed_mining_rounds WHERE event_id=$1 AND player_id=$2 AND box_kind='money'", event_id, c.from_user.id)
                if wins == 4:
                    await conn.execute("UPDATE players SET collection_boost=1.3,collection_boost_until=NOW()+INTERVAL '2 hours' WHERE telegram_id=$1", c.from_user.id)
                    await c.message.answer(f"🏆 {c.from_user.full_name} won all four money boxes! +30% collection speed for 2 hours.")
        await c.answer(desc, show_alert=True)
