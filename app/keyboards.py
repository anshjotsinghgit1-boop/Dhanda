from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 My company", callback_data="dashboard")],
        [InlineKeyboardButton(text="💰 Collect income", callback_data="collect"),
         InlineKeyboardButton(text="⬆️ Upgrade", callback_data="upgrade")],
        [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="ranking")],
        [InlineKeyboardButton(text="⏳ Events & countdowns", callback_data="events_refresh")],
        [InlineKeyboardButton(text="🔄 Refresh dashboard", callback_data="dashboard")],
        [InlineKeyboardButton(text="🪙 Gold market", callback_data="help_gold"),
         InlineKeyboardButton(text="🛍 Asset shop", callback_data="help_assets")],
        [InlineKeyboardButton(text="🏭 Industry", callback_data="help_industry"),
         InlineKeyboardButton(text="🤝 Clubs", callback_data="help_club")],
        [InlineKeyboardButton(text="📘 Rules & help", callback_data="game_rules")],
    ])
