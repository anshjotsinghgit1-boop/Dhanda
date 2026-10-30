import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from aiogram import F, Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from app.db import get_pool
from app.club_live import club_battle_tick
from app.club_competitions import open_level_competitions, competition_lobby_tick
from app.npcs import advance_npcs
from app.mining_team_wars import finalize_mining_event, mining_team_tick, register_mining_team_handlers
from app.competition_images import render_roster
from aiogram.types import BufferedInputFile

log = logging.getLogger(__name__)
MINING_INTERVAL = 7200
CLUB_INTERVAL = 3600
CLUB_TZ = ZoneInfo('Asia/Kolkata')
CLUB_OPEN_HOURS = set(range(10, 24)) | {0}
_club_roster_announced = set()
_club_opened_slots = set()

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
        rows = await conn.fetch("SELECT telegram_id FROM players WHERE is_npc=FALSE")
    for row in rows:
        try:
            await bot.send_message(row["telegram_id"], message, reply_markup=markup)
        except Exception:
            pass

_countdown_announced = set()


async def announce_countdowns(bot: Bot, now: int):
    """Keep the mining countdown only; club uses a single pre-opening roster photo."""
    remaining = MINING_INTERVAL - (now % MINING_INTERVAL)
    threshold = 300 if 295 < remaining <= 300 else 60 if 55 < remaining <= 60 else None
    if threshold is None:
        return
    cycle = now // MINING_INTERVAL
    key = ("mining", cycle, threshold)
    if key in _countdown_announced:
        return
    _countdown_announced.add(key)
    msg = f"⛏️ <b>Mining lobby opens in {threshold // 60} minute(s)!</b>\\n"
    msg += "⏳ Join window: 5 minutes · minimum 3 players · top 3 or top 5 qualify by net worth."
    async with get_pool().acquire() as conn:
        groups = await conn.fetch("SELECT chat_id FROM mining_groups")
    for group in groups:
        try:
            await bot.send_message(group["chat_id"], msg)
        except Exception:
            log.exception("Mining countdown announcement failed for group %s", group["chat_id"])
    if len(_countdown_announced) > 500:
        current_cycles = now // MINING_INTERVAL
        _countdown_announced.difference_update({
            item for item in _countdown_announced if item[1] < current_cycles - 2
        })


async def announce_club_rosters(bot: Bot, now_local: datetime):
    """Send one clear roster image exactly one minute before each scheduled club opening."""
    if now_local.minute != 59 or now_local.second > 5:
        return
    opening_hour = (now_local.hour + 1) % 24
    if opening_hour not in CLUB_OPEN_HOURS:
        return
    slot = (now_local.date().isoformat(), opening_hour)
    if slot in _club_roster_announced:
        return
    _club_roster_announced.add(slot)
    async with get_pool().acquire() as conn:
        levels = await conn.fetch(
            "SELECT DISTINCT business_level FROM players WHERE is_npc=FALSE AND business_level>=12 ORDER BY business_level"
        )
    for item in levels:
        level = int(item["business_level"])
        async with get_pool().acquire() as conn:
            participants = await conn.fetch(
                """SELECT telegram_id,display_name,is_npc FROM players
                   WHERE business_level=$1 ORDER BY is_npc,display_name""", level
            )
        humans = [p for p in participants if not p["is_npc"]]
        if not humans:
            continue
        try:
            photo = await render_roster(bot, level, participants)
            caption = (
                f"🏛 <b>LEVEL {level} CLUB ROSTER</b>\\n"
                f"⏳ Competition opens in 1 minute · {opening_hour:02d}:00 IST\\n"
                f"👥 {len(participants)} eligible participants"
            )
            for player in humans:
                try:
                    await bot.send_photo(
                        int(player["telegram_id"]),
                        BufferedInputFile(photo, filename=f"level_{level}_roster.png"),
                        caption=caption,
                    )
                except Exception:
                    log.debug("Pre-opening roster delivery failed for %s", player["telegram_id"])
        except Exception:
            log.exception("Could not render pre-opening roster for level %s", level)
    if len(_club_roster_announced) > 64:
        keep_date = now_local.date().isoformat()
        _club_roster_announced.intersection_update({x for x in _club_roster_announced if x[0] == keep_date})


async def timed_scheduler(bot: Bot):
    last_mining = int(datetime.now(timezone.utc).timestamp()) // MINING_INTERVAL
    while True:
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            await announce_countdowns(bot, now)
            now_local = datetime.now(CLUB_TZ)
            await announce_club_rosters(bot, now_local)
            ms = now // MINING_INTERVAL
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
            if now_local.minute == 0 and now_local.second < 5 and now_local.hour in CLUB_OPEN_HOURS:
                slot = (now_local.date().isoformat(), now_local.hour)
                if slot not in _club_opened_slots:
                    _club_opened_slots.add(slot)
                    await open_level_competitions(bot)
                    if len(_club_opened_slots) > 64:
                        today = now_local.date().isoformat()
                        _club_opened_slots.intersection_update({x for x in _club_opened_slots if x[0] == today})
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
        try:
            await advance_npcs()
        except Exception:
            log.exception('NPC progression tick failed')
        await asyncio.sleep(1)

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

