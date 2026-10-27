from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    """Compact command center with native Telegram button colors."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 My Empire", callback_data="my_empire", style="primary"),
         InlineKeyboardButton(text="⏳ Events", callback_data="events_refresh", style="primary")],
        [InlineKeyboardButton(text="🌈 More Options", callback_data="more_menu", style="primary")],
    ])


def my_empire_keyboard() -> InlineKeyboardMarkup:
    """Primary actions available from the empire screen, using native button colors."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Collect Income", callback_data="collect", style="success")],
        [InlineKeyboardButton(text="⚡ Events", callback_data="events_refresh", style="primary"),
         InlineKeyboardButton(text="🏆 FOSBU List", callback_data="ranking", style="primary")],
        [InlineKeyboardButton(text="🧭 Empire Details", callback_data="more_menu", style="primary")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
    ])


def back_home_keyboard(back_callback: str = "more_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=back_callback),
         InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
    ])
