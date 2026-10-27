from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    """Keep the home screen focused; open other actions from their own screens."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 My empire", callback_data="dashboard"),
         InlineKeyboardButton(text="⏳ Events", callback_data="events_refresh")],
        [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="ranking")],
    ])
