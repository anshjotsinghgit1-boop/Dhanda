from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    """A small home screen; reveal secondary actions only when requested."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 My empire", callback_data="dashboard"),
         InlineKeyboardButton(text="⏳ Events", callback_data="events_refresh")],
        [InlineKeyboardButton(text="☰ More options", callback_data="more_menu")],
    ])
