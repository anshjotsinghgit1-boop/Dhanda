from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💼 My Empire', callback_data='dashboard')],
        [InlineKeyboardButton(text='💰 Collect income', callback_data='collect'), InlineKeyboardButton(text='🏗 Upgrade business', callback_data='upgrade')],
        [InlineKeyboardButton(text='🏆 Fosbu ranking', callback_data='ranking')],
        [InlineKeyboardButton(text='🪙 Gold Exchange', callback_data='help_gold'), InlineKeyboardButton(text='🏬 Asset Shop', callback_data='help_assets')],
        [InlineKeyboardButton(text='🏭 Industrial Park', callback_data='help_industry'), InlineKeyboardButton(text='🏰 Clubs', callback_data='help_club')],
    ])
