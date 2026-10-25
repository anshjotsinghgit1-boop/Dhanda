import asyncio
import logging
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from app.config import BOT_TOKEN
from app.db import connect, close, get_pool
from app.economy import register_player, get_player, collect_income, upgrade_business, production_per_minute
from app.keyboards import main_menu
from app.seasons import season_scheduler
from app.assets import buy_gold, sell_gold, list_assets, buy_asset, inventory, buy_industrial_building, settle_industry
from app.clubs import create_club, join_club, my_club, donate_to_club
from app.wars import net_worth, attack

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def dashboard_text(p, worth: int | None = None) -> str:
    extra = f'\n🏆 Net worth: <b>{worth:,}</b>' if worth is not None else ''
    return (f'🏛 <b>EMPIRE CENTURY</b>\n\n'
            f'👤 {p["display_name"]}\n'
            f'💵 Cash: <b>{p["cash"]:,}</b>\n'
            f'🪙 Gold: <b>{p["gold_grams"] if "gold_grams" in p else 0} g</b>\n'
            f'📈 Stocks: <b>{p["stocks"] if "stocks" in p else 0:,}</b>\n'
            f'⭐ Reputation: <b>{p["reputation"]:,}</b>\n'
            f'🏢 Business level: <b>{p["business_level"]}/54</b>\n'
            f'⚙️ Production: <b>{production_per_minute(p["business_level"]):,} cash/min</b>'
            f'{extra}\n\nBuild your empire one upgrade at a time.')


async def ensure_player(user) -> bool:
    await register_player(user)
    return bool(await get_player(user.id))


@dp.message(CommandStart())
async def start(message: Message):
    await register_player(message.from_user)
    p = await get_player(message.from_user.id)
    worth = await net_worth(message.from_user.id)
    await message.answer(
        'Welcome to <b>EMPIRE CENTURY</b>!\n\nYour business empire starts now. Collect income, invest in assets, buy gold, build industry, hire employees, and climb the century rankings.\n\n'
        + dashboard_text(p, worth), reply_markup=main_menu())


@dp.message(Command('empire'))
async def empire(message: Message):
    p = await get_player(message.from_user.id)
    if not p:
        await message.answer('Run /start first.')
        return
    await message.answer(dashboard_text(p, await net_worth(message.from_user.id)), reply_markup=main_menu())


@dp.callback_query(F.data == 'dashboard')
async def dashboard(callback: CallbackQuery):
    p = await get_player(callback.from_user.id)
    if not p:
        await callback.answer('Run /start first.', show_alert=True)
    else:
        await callback.message.edit_text(dashboard_text(p, await net_worth(callback.from_user.id)), reply_markup=main_menu())
        await callback.answer()


@dp.callback_query(F.data == 'collect')
async def collect(callback: CallbackQuery):
    if not await get_player(callback.from_user.id):
        await callback.answer('Run /start first.', show_alert=True)
        return
    industry_rep = await settle_industry(callback.from_user.id)
    amount, shared = await collect_income(callback.from_user.id)
    suffix = f'\n👑 Boss share paid: {shared:,} cash.' if shared else ''
    if industry_rep:
        suffix += f'\n🏭 Industrial reputation settled: +{industry_rep:,}.'
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
        rows = await conn.fetch('''SELECT p.display_name,p.cash,p.reputation,p.business_level,
            p.stocks,p.gold_grams,
            p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.assets,0) AS worth
            FROM players p LEFT JOIN (SELECT pa.player_id,SUM(ac.net_worth*pa.quantity) assets
              FROM player_assets pa JOIN asset_catalog ac ON ac.id=pa.asset_id GROUP BY pa.player_id) a
              ON a.player_id=p.telegram_id
            ORDER BY worth DESC,p.reputation DESC,p.telegram_id ASC LIMIT 10''')
    if not rows:
        text = 'No players ranked yet. Be the first to build an empire!'
    else:
        text = '🏆 <b>FOSBU LIST — TOP 10</b>\n\n' + '\n'.join(
            f'{i}. {r["display_name"]} — 💎 {r["worth"]:,} NW | ⭐ {r["reputation"]:,}'
            for i, r in enumerate(rows, 1))
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()


@dp.message(Command('gold'))
async def gold_command(message: Message):
    parts = (message.text or '').split()
    if len(parts) != 3 or parts[1].lower() not in ('buy', 'sell'):
        await message.answer('Use: /gold buy 2 or /gold sell 1. Gold rate: 1,000 cash per gram.')
        return
    try:
        grams = Decimal(parts[2])
    except InvalidOperation:
        await message.answer('Enter a valid number of grams.')
        return
    ok, result = await (buy_gold(message.from_user.id, grams) if parts[1].lower() == 'buy'
                        else sell_gold(message.from_user.id, grams))
    await message.answer(('✅ ' if ok else '⚠️ ') + result)


@dp.message(Command('assetshop'))
async def asset_shop(message: Message):
    assets = await list_assets()
    if not assets:
        await message.answer('The asset shop is empty.')
        return
    lines = ['🏬 <b>ASSET EXCHANGE</b>', '', 'Buy with /buyasset ASSET_KEY']
    lines.extend(f'• <b>{a["name"]}</b> — {a["price"]:,} cash | +{a["net_worth"]:,} net worth\n  Key: <code>{a["asset_key"]}</code> · {a["description"]}' for a in assets)
    await message.answer('\n'.join(lines))


@dp.message(Command('buyasset'))
async def buyasset_command(message: Message):
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) != 2:
        await message.answer('Use /buyasset sports_car. See /assetshop.')
        return
    ok, result = await buy_asset(message.from_user.id, parts[1].strip().lower())
    await message.answer(('✅ ' if ok else '⚠️ ') + result)


@dp.message(Command('inventory'))
async def inventory_command(message: Message):
    rows, gold = await inventory(message.from_user.id)
    worth = await net_worth(message.from_user.id)
    lines = [f'🎒 <b>YOUR COLLECTION</b>\n🪙 Gold: {gold} g\n💎 Total net worth: {worth:,}']
    if rows:
        lines.extend(f'• {r["name"]} ×{r["quantity"]} — {r["net_worth"]*r["quantity"]:,} NW{" · Permanent" if r["permanent"] else ""}' for r in rows)
    else:
        lines.append('No assets yet. Browse /assetshop.')
    await message.answer('\n'.join(lines))


@dp.message(Command('industry'))
async def industry_command(message: Message):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch('SELECT * FROM industrial_buildings ORDER BY unlock_level')
        owned = await conn.fetch('''SELECT b.name,pi.quantity FROM player_industries pi
            JOIN industrial_buildings b ON b.id=pi.building_id WHERE pi.player_id=$1''', message.from_user.id)
    owned_text = '\n'.join(f'• {r["name"]} ×{r["quantity"]}' for r in owned) or 'No industrial buildings owned.'
    text = ['🏭 <b>INDUSTRIAL PARK</b>', 'Owned:', owned_text, '', 'Available buildings (use /buildindustry KEY):']
    text.extend(f'• {r["name"]} — {r["price"]:,} cash; {r["reputation_per_hour"]} rep/hour; unlock level {r["unlock_level"]}; key <code>{r["building_key"]}</code>' for r in rows)
    await message.answer('\n'.join(text))


@dp.message(Command('buildindustry'))
async def build_industry_command(message: Message):
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) != 2:
        await message.answer('Use /buildindustry workshop. See /industry.')
        return
    ok, result = await buy_industrial_building(message.from_user.id, parts[1].strip().lower())
    await message.answer(('✅ ' if ok else '⚠️ ') + result)


@dp.message(Command('club'))
async def club_command(message: Message):
    parts = (message.text or '').split(maxsplit=2)
    if len(parts) == 1 or parts[1].lower() == 'me':
        club = await my_club(message.from_user.id)
        if not club:
            await message.answer('You are not in a club. Create one with /club create Name | TAG or join using /club join TAG.')
        else:
            await message.answer(f'🏰 <b>{club["name"]} [{club["tag"]}]</b>\nRole: {club["role"]}\nMembers: {club["members"]}\nTreasury: {club["treasury"]:,} cash')
        return
    action = parts[1].lower()
    if action == 'join' and len(parts) >= 3:
        ok, result = await join_club(message.from_user.id, parts[2])
    elif action == 'create' and len(parts) >= 3 and '|' in parts[2]:
        name, tag = parts[2].split('|', 1)
        ok, result = await create_club(message.from_user.id, name, tag)
    else:
        await message.answer('Commands:\n/club\n/club create Empire Crew | EC\n/club join EC')
        return
    await message.answer(('✅ ' if ok else '⚠️ ') + result)


@dp.message(Command('donate'))
async def donate_command(message: Message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer('Use /donate 1000 to contribute cash to your club treasury.')
        return
    ok, result = await donate_to_club(message.from_user.id, int(parts[1]))
    await message.answer(('✅ ' if ok else '⚠️ ') + result)


@dp.message(Command('war'))
async def war_command(message: Message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer('Use /war TELEGRAM_ID to challenge another player.')
        return
    ok, result = await attack(message.from_user.id, int(parts[1]))
    await message.answer(('⚔️ ' if ok else '⚠️ ') + result)


@dp.message(Command('help'))
async def help_command(message: Message):
    await message.answer('''<b>EMPIRE CENTURY — COMMANDS</b>
/empire — your dashboard
/collect — use the Collect income button
/assetshop — browse luxury assets
/buyasset sports_car — purchase an asset
/inventory — your assets and net worth
/gold buy 2 — buy 2 grams of gold
/gold sell 1 — sell 1 gram of gold
/industry — industrial park catalog
/buildindustry workshop — buy a building
/club — view your club
/club create Name | TAG — create a club
/club join TAG — join a club
/donate 1000 — donate to club treasury
/war TELEGRAM_ID — business war
/ranking — use the Season ranking button

Seasons last exactly seven days. Temporary cash and business progress reset at settlement; reputation and eligible permanent assets persist.''', reply_markup=main_menu())


@dp.message(Command('collect'))
async def collect_command(message: Message):
    if not await get_player(message.from_user.id):
        await message.answer('Run /start first.')
        return
    industry_rep = await settle_industry(message.from_user.id)
    amount, shared = await collect_income(message.from_user.id)
    suffix = f' Boss share: {shared:,} cash.' if shared else ''
    if industry_rep:
        suffix += f' Industrial reputation: +{industry_rep:,}.'
    await message.answer(f'Collected {amount:,} cash.{suffix}')


@dp.message(Command('ranking'))
async def ranking_command(message: Message):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch('''SELECT p.display_name,p.cash,p.reputation,p.business_level,p.stocks,p.gold_grams,
            p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.assets,0) AS worth
            FROM players p LEFT JOIN (SELECT pa.player_id,SUM(ac.net_worth*pa.quantity) assets
            FROM player_assets pa JOIN asset_catalog ac ON ac.id=pa.asset_id GROUP BY pa.player_id) a
            ON a.player_id=p.telegram_id ORDER BY worth DESC,p.reputation DESC LIMIT 10''')
    text = '🏆 <b>FOSBU LIST — TOP 10</b>\n\n' + ('\n'.join(f'{i}. {r["display_name"]} — {r["worth"]:,} NW' for i, r in enumerate(rows, 1)) if rows else 'No players yet.')
    await message.answer(text)



@dp.callback_query(F.data == 'help_gold')
async def help_gold(callback: CallbackQuery):
    await callback.message.answer('🪙 <b>Gold Exchange</b>\nRate: 1,000 cash per gram.\nBuy: /gold buy 2\nSell: /gold sell 1')
    await callback.answer()


@dp.callback_query(F.data == 'help_assets')
async def help_assets(callback: CallbackQuery):
    await callback.message.answer('🏬 Browse /assetshop, buy using /buyasset sports_car, and check your collection with /inventory.')
    await callback.answer()


@dp.callback_query(F.data == 'help_industry')
async def help_industry(callback: CallbackQuery):
    await callback.message.answer('🏭 View buildings with /industry and buy one with /buildindustry workshop. Buildings generate reputation over time.')
    await callback.answer()


@dp.callback_query(F.data == 'help_club')
async def help_club(callback: CallbackQuery):
    await callback.message.answer('🏰 /club — view your club\n/club create Empire Crew | EC\n/club join EC\n/donate 1000')
    await callback.answer()


async def main():
    await connect()
    season_task = asyncio.create_task(season_scheduler(), name='season-scheduler')
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        season_task.cancel()
        await asyncio.gather(season_task, return_exceptions=True)
        await close()
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
