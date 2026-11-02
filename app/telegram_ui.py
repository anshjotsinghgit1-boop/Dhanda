"""Safe Telegram message updates for callback-driven screens."""
from aiogram.exceptions import TelegramBadRequest


async def safe_edit_message(message, text: str, reply_markup=None):
    """Edit text/caption when possible; otherwise send the screen as a new message.

    Telegram cannot edit text on media messages without a caption. Captions are
    limited to 1024 characters, so longer screens are sent as normal messages.
    """
    try:
        if message.text is not None:
            await message.edit_text(text, reply_markup=reply_markup)
        elif message.caption is not None and len(text) <= 1024:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if "message is not modified" in error:
            return
        if "there is no text in the message to edit" in error or "message can't be edited" in error:
            await message.answer(text, reply_markup=reply_markup)
            return
        raise
