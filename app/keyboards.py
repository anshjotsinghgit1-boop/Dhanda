from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    """Compact command center with emoji-coded navigation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 My Empire", callback_data="my_empire"),
         InlineKeyboardButton(text="⏳ Events", callback_data="events_refresh")],
        [InlineKeyboardButton(text="🌈 More Options", callback_data="more_menu")],
    ])


def my_empire_keyboard() -> InlineKeyboardMarkup:
    """Primary actions available from the empire screen."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Collect Income", callback_data="collect")],
        [InlineKeyboardButton(text="⚡ Events", callback_data="events_refresh"),
         InlineKeyboardButton(text="🏆 FOSBU List", callback_data="ranking")],
        [InlineKeyboardButton(text="🧭 Empire Details", callback_data="more_menu")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
    ])


def back_home_keyboard(back_callback: str = "more_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=back_callback),
         InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
    ])
