"""Persistent level-specific club competition lobbies."""
import logging
from aiogram import F, Bot, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from app.db import get_pool

log = logging.getLogger(__name__)

def join_keyboard(competition_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏛 JOIN LEVEL COMPETITION", callback_data=f"ccj_{competition_id}", style="success")
    ]])


async def open_level_competitions(bot: Bot):
    """Open five-minute lobbies for levels that currently have human players."""
    async with get_pool().acquire() as conn:
        levels = await conn.fetch(
            "SELECT DISTINCT business_level FROM players WHERE is_npc=FALSE AND business_level>=12 ORDER BY business_level"
        )
    for item in levels:
        level = int(item["business_level"])
        async with get_pool().acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM club_competitions WHERE business_level=$1 AND status IN ('joining','running')",
                level,
            )
            if existing:
                continue
            competition_id = await conn.fetchval(
                """INSERT INTO club_competitions(business_level,status,opens_at,closes_at)
                   VALUES($1,'joining',NOW(),NOW()+INTERVAL '5 minutes') RETURNING id""",
                level,
            )
            await conn.execute(
                """INSERT INTO club_competition_participants(competition_id,player_id)
                   SELECT $1,telegram_id FROM players WHERE is_npc=TRUE AND business_level=$2
                   ON CONFLICT(competition_id,player_id) DO NOTHING""",
                competition_id, level,
            )
            humans = await conn.fetch(
                "SELECT telegram_id FROM players WHERE is_npc=FALSE AND business_level=$1",
                level,
            )
        message = (
            f"🏛 <b>LEVEL {level} CLUB COMPETITION</b> · #{competition_id}\n"
            "━━━━━━━━━━━━━━━━━━\n⏳ <b>5:00 JOIN WINDOW</b>\n"
            "Register now. The competition will match you against two different opponents. "
            "You must win both matches to pass."
        )
        for human in humans:
            try:
                await bot.send_message(human["telegram_id"], message, reply_markup=join_keyboard(competition_id))
            except Exception:
                log.debug("Could not notify player %s", human["telegram_id"])


async def competition_lobby_tick():
    async with get_pool().acquire() as conn:
        due = await conn.fetch(
            "SELECT id FROM club_competitions WHERE status='joining' AND closes_at<=NOW()"
        )
        for item in due:
            cid = int(item["id"])
            humans = await conn.fetchval(
                """SELECT COUNT(*) FROM club_competition_participants cp
                   JOIN players p ON p.telegram_id=cp.player_id
                   WHERE cp.competition_id=$1 AND p.is_npc=FALSE""",
                cid,
            )
            if humans:
                await conn.execute(
                    "UPDATE club_competitions SET status='running' WHERE id=$1 AND status='joining'", cid
                )
            else:
                await conn.execute(
                    "UPDATE club_competitions SET status='cancelled',finished_at=NOW() WHERE id=$1 AND status='joining'", cid
                )


def register_competition_handlers(bot: Bot, dp: Dispatcher):
    @dp.callback_query(F.data.startswith("ccj_"))
    async def competition_join(c: CallbackQuery):
        try:
            cid = int(c.data.rsplit("_", 1)[1])
        except (TypeError, ValueError):
            await c.answer("Invalid competition.", show_alert=True)
            return
        async with get_pool().acquire() as conn:
            player = await conn.fetchrow(
                "SELECT business_level,is_npc FROM players WHERE telegram_id=$1", c.from_user.id
            )
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
                """INSERT INTO club_competition_participants(competition_id,player_id)
                   VALUES($1,$2) ON CONFLICT(competition_id,player_id) DO NOTHING""",
                cid, c.from_user.id,
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM club_competition_participants WHERE competition_id=$1", cid
            )
        await c.answer(f"Registered! {count} participant(s) in this roster.", show_alert=True)
