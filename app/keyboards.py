from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💼 My Empire', callback_data='dashboard')],
        [InlineKeyboardButton(text='💰 Collect income', callback_data='collect'), InlineKeyboardButton(text='🏗 Upgrade business', callback_data='upgrade')],
        [InlineKeyboardButton(text='🏆 Season ranking', callback_data='ranking')],
    ])
