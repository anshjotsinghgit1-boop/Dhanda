import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from app.config import BOT_TOKEN
from app.db import connect, close, get_pool
from app.economy import register_player, get_player, collect_income, upgrade_business, production_per_minute
from app.keyboards import main_menu

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

def dashboard_text(p) -> str:
    return (f'🏛 <b>EMPIRE CENTURY</b>\n\n'
            f'👤 {p["display_name"]}\n'
            f'💵 Cash: <b>{p["cash"]:,}</b>\n'
            f'⭐ Reputation: <b>{p["reputation"]:,}</b>\n'
            f'🏢 Business level: <b>{p["business_level"]}/54</b>\n'
            f'⚙️ Production: <b>{production_per_minute(p["business_level"]):,} cash/min</b>\n\n'
            'Build your empire one upgrade at a time.')

@dp.message(CommandStart())
async def start(message: Message):
    await register_player(message.from_user)
    p = await get_player(message.from_user.id)
    await message.answer('Welcome to <b>EMPIRE CENTURY</b>!\n\nYour business empire starts now. Collect income, upgrade your business, and climb the season rankings.\n\n' + dashboard_text(p), reply_markup=main_menu())

@dp.message(Command('empire'))
async def empire(message: Message):
    p = await get_player(message.from_user.id)
    if not p:
        await message.answer('Run /start first.')
        return
    await message.answer(dashboard_text(p), reply_markup=main_menu())

@dp.callback_query(F.data == 'dashboard')
async def dashboard(callback: CallbackQuery):
    p = await get_player(callback.from_user.id)
    if not p:
        await callback.answer('Run /start first.', show_alert=True)
    else:
        await callback.message.edit_text(dashboard_text(p), reply_markup=main_menu())
        await callback.answer()

@dp.callback_query(F.data == 'collect')
async def collect(callback: CallbackQuery):
    p = await get_player(callback.from_user.id)
    if not p:
        await callback.answer('Run /start first.', show_alert=True)
        return
    amount, shared = await collect_income(callback.from_user.id)
    suffix = f'\n👑 Boss share paid: {shared:,} cash.' if shared else ''
    await callback.message.answer(f'💰 Collected <b>{amount:,}</b> cash!{suffix}', reply_markup=main_menu())
    await callback.answer('Income collected')

@dp.callback_query(F.data == 'upgrade')
async def upgrade(callback: CallbackQuery):
    ok, message = await upgrade_business(callback.from_user.id)
    await callback.message.answer(('✅ ' if ok else 'ℹ️ ') + message, reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == 'ranking')
async def ranking(callback: CallbackQuery):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch('SELECT display_name, cash, reputation, business_level FROM players ORDER BY reputation DESC, cash DESC LIMIT 10')
    if not rows:
        text = 'No players ranked yet. Be the first to build an empire!'
    else:
        text = '🏆 <b>EMPIRE RANKING</b>\n\n' + '\n'.join(f'{i}. {r["display_name"]} — ⭐ {r["reputation"]:,} | 💵 {r["cash"]:,}' for i, r in enumerate(rows, 1))
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()

async def main():
    await connect()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await close()
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
