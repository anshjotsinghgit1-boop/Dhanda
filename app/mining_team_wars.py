"""Automatic cross-group mining team battles."""
from app.db import get_pool
from aiogram import F, Bot, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

def _box_kb(war_id, matchup):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {n}", callback_data=f"mtpick_{war_id}_{matchup}_{n}") for n in range(start,start+3)]
        for start in (1,4,7)
    ])

async def mining_team_tick(bot: Bot):
    return

def register_mining_team_handlers(bot: Bot, dp: Dispatcher):
    return
