import asyncio
import logging
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.config import BOT_TOKEN
from app.db import connect, close, get_pool
from app.economy import register_player, get_player, collect_income, upgrade_business, production_per_minute
from app.keyboards import main_menu
from app.seasons import season_scheduler
from app.assets import buy_gold, sell_gold, list_assets, buy_asset, inventory, buy_industrial_building, settle_industry, resume_industry
from app.clubs import create_club, join_club, my_club, donate_to_club
from app.wars import net_worth, attack
from app.employees import send_challenge, accept_challenge
from app.stocks import quotes, holdings, trade
from app.mining_wars import create_war, join_team, war_snapshot, start_fight, cancel_war

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# Register group-only guards before gameplay handlers so earlier handlers cannot bypass them.
@dp.message(F.chat.type.in_({"group", "supergroup"}), ~F.text.startswith("/miningwar"), ~F.text.startswith("/miningstatus"))
async def group_mining_only_guard(message: Message):
    await message.answer("⛏ This group is for mining only. Use /miningwar to open a mining lobby; use the bot in private chat for all other game features.")


@dp.callback_query(F.message.chat.type.in_({"group", "supergroup"}), ~F.data.startswith("mine_"))
async def group_non_mining_button_guard(callback: CallbackQuery):
    await callback.answer("Only mining buttons work in group chats. Open the bot in private chat for other features.", show_alert=True)



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
            p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.asset_value,0) AS worth
            FROM players p LEFT JOIN player_asset_valuation a ON a.player_id=p.telegram_id
            ORDER BY worth DESC,p.reputation DESC,p.telegram_id ASC LIMIT 10''')
    if not rows:
        text = 'No players ranked yet. Be the first to build an empire!'
    else:
        text = '🏆 <b>FOSBU LIST — TOP 10</b>\n\n' + '\n'.join(
            f'{i}. {r["display_name"]} — 💎 {r["worth"]:,} NW | ⭐ {r["reputation"]:,}'
            for i, r in enumerate(rows, 1))
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()



def mining_keyboard(war_id: int, status: str) -> InlineKeyboardMarkup:
    if status == "recruiting":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⛏ JOIN MINING", callback_data=f"mine_join_{war_id}")],
            [InlineKeyboardButton(text="⚒️ START MINING", callback_data=f"mine_start_{war_id}"),
             InlineKeyboardButton(text="🔄 Refresh", callback_data=f"mine_refresh_{war_id}")],
            [InlineKeyboardButton(text="✖ Cancel", callback_data=f"mine_cancel_{war_id}")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Refresh", callback_data=f"mine_refresh_{war_id}")]])


async def mining_text(chat_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    war, miners, total_worth = await war_snapshot(chat_id)
    if not war:
        return "No active mining session in this group. Start one with /miningwar.", None
    lines = [f'• {p["display_name"]} — 💎 {p["worth"]:,} NW' for p in miners]
    status = war["status"]
    text = (f'⛏ <b>EMPIRE CENTURY — MINING #{war["id"]}</b>\n'
            f'Status: <b>{status.title()}</b>\n'
            f'Applicants: <b>{len(miners)}</b>\n\n'
            + ('\n'.join(lines) if lines else 'No miners have joined yet.')
            + '\n\nAt start: 3 highest-net-worth miners qualify with 3–4 applicants; '
              '5 qualify with 5 or more applicants. Minimum 3 applicants.')
    return text, mining_keyboard(war["id"], status)


@dp.message(Command("miningwar"))
async def mining_war_command(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Start mining from inside a Telegram group.")
        return
    await register_player(message.from_user)
    ok, result, war_id = await create_war(message.chat.id, message.from_user.id, 5)
    if not ok:
        await message.answer("⚠️ " + result)
        return
    text, markup = await mining_text(message.chat.id)
    sent = await message.answer(text, reply_markup=markup)
    async with get_pool().acquire() as conn:
        await conn.execute("UPDATE group_mining_wars SET message_id=$1 WHERE id=$2", sent.message_id, war_id)


@dp.message(Command("miningstatus"))
async def mining_status_command(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Use /miningstatus in the group where mining is running.")
        return
    text, markup = await mining_text(message.chat.id)
    await message.answer(text, reply_markup=markup)


@dp.callback_query(F.data.startswith("mine_join_"))
async def mining_join_callback(callback: CallbackQuery):
    try:
        war_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer("Invalid mining button.", show_alert=True)
        return
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("Join from the mining group's message.", show_alert=True)
        return
    ok, result = await join_team(callback.message.chat.id, callback.from_user.id, 1, war_id)
    if ok:
        text, markup = await mining_text(callback.message.chat.id)
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
    await callback.answer(result, show_alert=not ok)


@dp.callback_query(F.data.startswith("mine_start_"))
async def mining_start_callback(callback: CallbackQuery):
    try:
        war_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer("Invalid mining button.", show_alert=True)
        return
    ok, result, resolved_id, winner = await start_fight(callback.message.chat.id, callback.from_user.id, war_id)
    if ok:
        await callback.message.edit_text("⛏ <b>MINING RESULTS</b>\n\n" + result)
    await callback.answer(result if len(result) < 180 else "Mining completed.", show_alert=not ok)


@dp.callback_query(F.data.startswith("mine_refresh_"))
async def mining_refresh_callback(callback: CallbackQuery):
    text, markup = await mining_text(callback.message.chat.id)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    await callback.answer("Mining board refreshed.")


@dp.callback_query(F.data.startswith("mine_cancel_"))
async def mining_cancel_callback(callback: CallbackQuery):
    ok, result = await cancel_war(callback.message.chat.id, callback.from_user.id, int(callback.data.rsplit('_', 1)[1]))
    if ok:
        await callback.message.edit_text("✖ " + result)
    await callback.answer(result, show_alert=not ok)


# Group chats are reserved for mining only; the full empire interface is private-chat only.
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



@dp.message(Command('resumeindustry'))
async def resume_industry_command(message: Message):
    ok, result = await resume_industry(message.from_user.id)
    await message.answer(('✅ ' if ok else 'ℹ️ ') + result)


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
/buildindustry workshop — buy a building\n/resumeindustry — resume industry after a season rollover
/club — view your club
/club create Name | TAG — create a club
/club join TAG — join a club
/donate 1000 — donate to club treasury
/war TELEGRAM_ID — direct business war\n/miningwar 3 or /miningwar 5 — group mining war\n/miningstatus — refresh group war\n/stocks — stock market\n/stock buy ECOR 10 — buy shares\n/hire TELEGRAM_ID — send recruitment challenge\n/hireaccept ID — accept recruitment
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
            FROM players p LEFT JOIN player_asset_valuation a ON a.player_id=p.telegram_id ORDER BY worth DESC,p.reputation DESC LIMIT 10''')
    text = '🏆 <b>FOSBU LIST — TOP 10</b>\n\n' + ('\n'.join(f'{i}. {r["display_name"]} — {r["worth"]:,} NW' for i, r in enumerate(rows, 1)) if rows else 'No players yet.')
    await message.answer(text)




@dp.message(Command('stocks'))
async def stocks_command(message: Message):
    rows = await quotes()
    owned = await holdings(message.from_user.id)
    lines = ['📈 <b>EMPIRE STOCK EXCHANGE</b>', 'Trade: /stock buy ECOR 10 or /stock sell ECOR 2', '']
    lines.extend(f'<b>{r["symbol"]}</b> — {r["company_name"]}: {r["price"]:,} cash/share' for r in rows)
    if owned:
        lines.extend(['', '<b>Your holdings</b>'])
        lines.extend(f'• {r["symbol"]}: {r["shares"]} shares · value {r["value"]:,}' for r in owned)
    await message.answer('\n'.join(lines))


@dp.message(Command('stock'))
async def stock_command(message: Message):
    parts = (message.text or '').split()
    if len(parts) != 4 or parts[1].lower() not in ('buy','sell') or not parts[3].isdigit():
        await message.answer('Use /stock buy ECOR 10 or /stock sell ECOR 2. See /stocks.')
        return
    ok, result = await trade(message.from_user.id, parts[2], int(parts[3]), parts[1].lower())
    await message.answer(('✅ ' if ok else '⚠️ ') + result)


@dp.message(Command('hire'))
async def hire_command(message: Message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer('Use /hire TELEGRAM_ID. Board of Directors unlocks at business level 7.')
        return
    ok, result = await send_challenge(message.from_user.id, int(parts[1]))
    await message.answer(('📨 ' if ok else '⚠️ ') + result)


@dp.message(Command('hireaccept'))
async def hire_accept_command(message: Message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer('Use /hireaccept CHALLENGE_ID to accept an employee recruitment challenge.')
        return
    ok, result = await accept_challenge(message.from_user.id, int(parts[1]))
    await message.answer(('✅ ' if ok else '⚠️ ') + result)


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
