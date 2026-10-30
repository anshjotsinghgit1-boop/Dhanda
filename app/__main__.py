import asyncio
import logging
from html import escape
import json
import random
import time
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.client.default import DefaultBotProperties

from app.config import BOT_TOKEN
from app.db import connect, close, get_pool
from app.economy import register_player, get_player, collect_income, auto_upgrade_business, upgrade_business, production_per_second, upgrade_cost, requires_club_competition
from app.npcs import seed_npcs
from app.keyboards import main_menu, my_empire_keyboard, back_home_keyboard
from app.seasons import season_scheduler
from app.assets import buy_gold, sell_gold, list_assets, buy_asset, inventory, buy_industrial_building, settle_industry, resume_industry
from app.wars import net_worth
from app.box_battles import new_layout, save_layout, random_layout
from app.employees import send_challenge, accept_challenge
from app.stocks import quotes, holdings, trade
from app.mining_wars import create_war, join_team, war_snapshot, start_fight, cancel_war
from app.timed_events import register_timed_handlers, timed_scheduler, register_mining_group
from app.mining_rewards import MiningGroupMemberTracker, top_mining_groups
from app.club_competitions import register_competition_handlers
from app.competition_images import render_forbes_leaderboard

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
dp.message.middleware(MiningGroupMemberTracker())
register_timed_handlers(bot, dp)

@dp.my_chat_member()
async def register_group_when_bot_added(event: ChatMemberUpdated):
    if event.chat.type not in ("group", "supergroup"):
        return
    if event.new_chat_member.status in ("member", "administrator"):
        await register_mining_group(event.chat.id, event.chat.title or "Mining group")
register_competition_handlers(bot, dp)

# Register group-only guards before gameplay handlers so earlier handlers cannot bypass them.
@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.startswith("/"), ~F.text.startswith("/miningwar"), ~F.text.startswith("/miningstatus"), ~F.text.startswith("/war"), ~F.text.startswith("/rank"), ~F.text.startswith("/events"), ~F.text.startswith("/topgroups"))
async def group_mining_only_guard(message: Message):
    await message.answer("⛏ This group is for mining only. Use /miningwar to open a mining lobby; use the bot in private chat for all other game features.")


@dp.callback_query(F.message.chat.type.in_({"group", "supergroup"}), ~F.data.startswith("mine_"), ~F.data.startswith("box_"), F.data != "top_mining_groups")
async def group_non_mining_button_guard(callback: CallbackQuery):
    await callback.answer("Only mining buttons work in group chats. Open the bot in private chat for other features.", show_alert=True)


def countdown_label(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def event_countdown_text() -> str:
    now = int(time.time())
    mining_remaining = 7200 - (now % 7200)
    club_remaining = 3600 - (now % 3600)
    return (
        "⏳ <b>UPCOMING EVENTS</b>\n"
        f"⛏️ Next mining lobby: <b>{countdown_label(mining_remaining)}</b> · 2-hour cycle\n"
        f"🏛️ Level club competition: <b>{countdown_label(club_remaining)}</b> · hourly cycle\n"
        "Use /events anytime to refresh these countdowns."
    )


def dashboard_text(p, worth: int | None = None) -> str:
    level = int(p["business_level"])
    cash = int(p["cash"])
    rate = production_per_second(level)
    if level >= 54:
        milestone = "🏆 <b>EMPIRE FULLY MAXED</b> · Level 54 unlocked."
    else:
        cost = upgrade_cost(level)
        progress = min(100, int(cash * 100 / cost)) if cost else 100
        filled = min(10, int(progress / 10))
        bar = "🟩" * filled + "▫️" * (10 - filled)
        shortfall = max(0, cost - cash)
        completed_level = int(p["club_completed_level"] or 0) if "club_completed_level" in p.keys() else 0
        battle_locked = requires_club_competition(level) and completed_level != level
        target_status = f"🏛 Win both matches in the Level {level} competition to unlock this upgrade." if battle_locked else (
            "✨ Target reached — level-up is automatic!" if shortfall == 0 else f"💰 <b>{shortfall:,}</b> cash to go"
        )
        milestone = (
            f"🚀 <b>NEXT TARGET · LEVEL {level + 1}</b>\n"
            f"{bar}  <b>{progress}%</b>\n"
            f"🎯 Target: <b>{cost:,}</b> cash\n"
            f"{target_status}"
        )
    extra = f'\n💎 <b>Net worth: {worth:,}</b>' if worth is not None else ''
    return (
        '🏛 <b>EMPIRE CENTURY</b>\n'
        '━━━━━━━━━━━━━━━━━━\n'
        f'👤 <b>{p["display_name"]}</b>\n\n'
        f'💵 Treasury: <b>{cash:,}</b>\n'
        f'⚙️ Production: <b>{rate:,} cash/sec</b> · <b>{rate * 3600:,}/hour</b>\n'
        f'🪙 Gold: <b>{p["gold_grams"] if "gold_grams" in p else 0} g</b>\n'
        f'📈 Stocks: <b>{p["stocks"] if "stocks" in p else 0:,}</b>\n'
        f'⭐ Reputation: <b>{p["reputation"]:,}</b>\n'
        f'🏢 Business level: <b>{level}/54</b>'
        f'{extra}\n\n{milestone}\n\n'
        '💡 <i>Grow your treasury to the target. Your empire levels up automatically.</i>'
    )

async def ensure_player(user) -> bool:
    await register_player(user)
    return bool(await get_player(user.id))


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 Start my company", callback_data="start_company")],
        [InlineKeyboardButton(text="📘 Read the rules", callback_data="game_rules")],
    ])


@dp.message(CommandStart())
async def start(message: Message):
    if message.chat.type != "private":
        await message.answer("Open me in a private chat to start and manage your company.")
        return
    p = await get_player(message.from_user.id)
    if p:
        await auto_upgrade_business(message.from_user.id)
        p = await get_player(message.from_user.id)
        await message.answer(dashboard_text(p, await net_worth(message.from_user.id)),
                             reply_markup=main_menu())
        return
    await message.answer(
        "🏛 <b>EMPIRE CENTURY</b>\n"
        "<i>Build your empire. Grow your wealth. Make every move count.</i>\n\n"
        "🚀 Start with 1,000 cash, build your company, collect income, invest, and compete with other players.\n\n"
        + event_countdown_text() + "\n\n"
        "📘 Read the rules first, or tap below to launch your company.",
        reply_markup=welcome_keyboard())


def events_text() -> str:
    return (
        "🗓️ <b>EMPIRE EVENT SCHEDULE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        + event_countdown_text()
        + "\n\n⛏️ <b>Mining</b>\n"
        "• Lobby opens every 2 hours and stays open for 5 minutes.\n"
        "• Minimum 3 applicants; 3–4 applicants: top 3 qualify; 5+: top 5 qualify by net worth.\n\n"
        "🏛️ <b>Level club competitions</b>\n"
        "• A five-minute lobby opens hourly for each active business level.\n"
        "• Four roster image updates are sent during the lobby.\n"
        "• Each participant faces two different opponents in best-of-three matches. Win both."
    )


def events_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏️ Mining Rules", callback_data="rule_mining", style="primary"),
         InlineKeyboardButton(text="🏰 Club Rules", callback_data="rule_club", style="primary")],
        [InlineKeyboardButton(text="🔄 Refresh Countdown", callback_data="events_refresh", style="primary")],
        [InlineKeyboardButton(text="🏢 My Empire", callback_data="my_empire", style="primary"),
         InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
    ])

@dp.message(Command("events"))
async def events_command(message: Message):
    await message.answer(events_text(), reply_markup=events_keyboard())


async def top_mining_groups_text() -> str:
    rows = await top_mining_groups(10)
    if not rows:
        return ("🏆 <b>TOP MINING GROUPS</b>\n\nNo group data yet. "
                "The bot records known players as they use registered groups.")
    lines = ["🏆 <b>TOP MINING GROUPS BY COMBINED NET WORTH</b>",
             "━━━━━━━━━━━━━━━━━━",
             "<i>Based on registered players the bot has observed in each group.</i>"]
    for i, row in enumerate(rows, 1):
        bonus = " · 💰 +15% active" if row["has_active_bonus"] else ""
        lines.append(f"{i}. <b>{escape(str(row['title']))}</b>\n"
                     f"   💎 {int(row['total_worth'] or 0):,} total net worth · "
                     f"👥 {int(row['player_count'] or 0)} known players{bonus}")
    return "\n".join(lines)


@dp.message(Command("topgroups"))
async def topgroups_command(message: Message):
    await message.answer(await top_mining_groups_text(), reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔄 Refresh", callback_data="top_mining_groups")]]
    ))


@dp.callback_query(F.data == "top_mining_groups")
async def topgroups_callback(callback: CallbackQuery):
    text = await top_mining_groups_text()
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔄 Refresh", callback_data="top_mining_groups")]]
        ))
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await callback.answer("Mining group rankings refreshed")


@dp.callback_query(F.data == "events_refresh")
async def events_refresh(callback: CallbackQuery):
    try:
        await callback.message.edit_text(events_text(), reply_markup=events_keyboard())
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await callback.answer("⏱️ Countdown refreshed")


@dp.callback_query(F.data == "start_company")
async def start_company(callback: CallbackQuery):
    await register_player(callback.from_user)
    await auto_upgrade_business(callback.from_user.id)
    p = await get_player(callback.from_user.id)
    await callback.message.edit_text(
        "✅ <b>Your company is open!</b>\n\n" + dashboard_text(
            p, await net_worth(callback.from_user.id)),
        reply_markup=main_menu())
    await callback.answer("Company created!")


@dp.callback_query(F.data == "game_rules")
async def game_rules(callback: CallbackQuery):
    await callback.message.edit_text(
        "📘 <b>EMPIRE CENTURY · RULEBOOK</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose a section to see only the rules relevant to that activity.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏢 Business", callback_data="rule_business", style="primary"),
             InlineKeyboardButton(text="💰 Economy", callback_data="rule_economy", style="success")],
            [InlineKeyboardButton(text="🏰 Club Battles", callback_data="rule_club", style="primary")],
            [InlineKeyboardButton(text="⛏️ Mining", callback_data="rule_mining", style="success")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="dashboard"),
             InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
        ]))
    await callback.answer()


@dp.callback_query(F.data.in_({"rule_business", "rule_economy", "rule_club", "rule_mining"}))
async def contextual_rules(callback: CallbackQuery):
    sections = {
        "rule_business": (
            "🏢 <b>BUSINESS RULES</b>\n\n"
            "• Your business generates cash automatically.\n"
            "• Collect income to claim earnings, capped at 8 hours per collection.\n"
            "• Upgrades cost in-game cash and increase production.\n"
            "• Club competition gates alternate: 12→13, 14→15, …, 52→53. Win both matches in that level’s competition."
        ),
        "rule_economy": (
            "💰 <b>ECONOMY RULES</b>\n\n"
            "• Treasury is your spendable cash.\n"
            "• Gold, stocks, and eligible assets contribute to net worth.\n"
            "• Check prices and confirmation messages before spending.\n"
            "• Seasons last 7 days; temporary progress resets at settlement while eligible permanent progress persists."
        ),
        "rule_club": (
            "🏰 <b>LEVEL CLUB COMPETITION RULES</b>\n\n"
            "• System-managed competitions open hourly for active business levels from 12+.\n"
            "• The joining window lasts 5 minutes, with four roster image updates.\n"
            "• Every participant faces two different opponents.\n"
            "• Each match is best of three; each box round has a 15-second timer.\n"
            "• You must win both matches in the same competition. Losing the first does not cancel the second.\n"
            "• Only upgrades from levels 12, 14, 16, …, 52 require a competition win."
        ),
        "rule_mining": (
            "⛏️ <b>MINING RULES</b>\n\n"
            "• Mining lobbies open every 2 hours for 5 minutes.\n"
            "• Players must start the bot in private chat before joining.\n"
            "• At least 3 applicants are required.\n"
            "• With 3–4 applicants, the top 3 by net worth qualify; with 5+, the top 5 qualify.\n"
            "• Groups are used for mining activities."
        ),
    }
    await callback.message.edit_text(
        sections[callback.data],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📘 All Rules", callback_data="game_rules", style="primary")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="more_menu"),
             InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
        ]))
    await callback.answer()

@dp.message(Command('empire'))
async def empire(message: Message):
    p = await get_player(message.from_user.id)
    if not p:
        await message.answer('Run /start first.')
        return
    await message.answer(dashboard_text(p, await net_worth(message.from_user.id)), reply_markup=main_menu())


@dp.callback_query(F.data == "more_menu")
async def more_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌈 <b>EMPIRE CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose a department. Each section opens its own focused screen.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏆 FORBES LIST", callback_data="ranking", style="primary"),
             InlineKeyboardButton(text="🪙 Gold & Markets", callback_data="help_gold", style="success")],
            [InlineKeyboardButton(text="🏭 Industry", callback_data="help_industry", style="primary"),
             InlineKeyboardButton(text="🏰 Club", callback_data="help_club", style="primary")],
            [InlineKeyboardButton(text="📘 Rules", callback_data="game_rules", style="primary"),
             InlineKeyboardButton(text="⛏️ Mining Rules", callback_data="rule_mining", style="success")],
            [InlineKeyboardButton(text="🔙 Back to My Empire", callback_data="my_empire", style="primary"),
             InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
        ]))
    await callback.answer()

@dp.callback_query(F.data == 'dashboard')
async def dashboard(callback: CallbackQuery):
    p = await get_player(callback.from_user.id)
    if not p:
        await callback.answer('Run /start first.', show_alert=True)
        return
    await auto_upgrade_business(callback.from_user.id)
    p = await get_player(callback.from_user.id)
    try:
        await callback.message.edit_text(
            dashboard_text(p, await net_worth(callback.from_user.id)),
            reply_markup=main_menu(),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await callback.answer()


@dp.callback_query(F.data == "my_empire")
async def my_empire(callback: CallbackQuery):
    p = await get_player(callback.from_user.id)
    if not p:
        await callback.answer("Run /start first.", show_alert=True)
        return
    await auto_upgrade_business(callback.from_user.id)
    p = await get_player(callback.from_user.id)
    await callback.message.edit_text(
        dashboard_text(p, await net_worth(callback.from_user.id)),
        reply_markup=my_empire_keyboard(),
    )
    await callback.answer()

@dp.callback_query(F.data == 'collect')
async def collect(callback: CallbackQuery):
    if not await get_player(callback.from_user.id):
        await callback.answer('Run /start first.', show_alert=True)
        return
    industry_rep = await settle_industry(callback.from_user.id)
    amount, shared = await collect_income(callback.from_user.id)
    level_ups = await auto_upgrade_business(callback.from_user.id)
    suffix = f'\n👑 Boss share paid: {shared:,} cash.' if shared else ''
    if industry_rep:
        suffix += f'\n🏭 Industrial reputation settled: +{industry_rep:,}.'
    if level_ups:
        suffix += '\n\n' + '\n'.join(level_ups)
    # Keep the empire screen in place; show collection and automatic level-ups separately.
    await callback.message.answer(f'💚 <b>Income collected: {amount:,} cash!</b>{suffix}')
    p = await get_player(callback.from_user.id)
    await callback.message.edit_text(
        dashboard_text(p, await net_worth(callback.from_user.id)),
        reply_markup=my_empire_keyboard())
    await callback.answer('Income collected')

@dp.callback_query(F.data == 'upgrade')
async def upgrade(callback: CallbackQuery):
    ok, message = await upgrade_business(callback.from_user.id)
    p = await get_player(callback.from_user.id)
    await callback.message.edit_text(
        ('✅ ' if ok else 'ℹ️ ') + message + '\n\n' +
        dashboard_text(p, await net_worth(callback.from_user.id)),
        reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data == 'ranking')
async def ranking(callback: CallbackQuery):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch('''SELECT p.telegram_id,p.display_name,p.is_npc,p.business_level,
            p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.asset_value,0) AS worth,
            COUNT(*) OVER () AS total_players
            FROM players p LEFT JOIN player_asset_valuation a ON a.player_id=p.telegram_id
            ORDER BY worth DESC,p.telegram_id ASC LIMIT 10''')
    if not rows:
        await callback.message.answer("No players ranked yet. Be the first to build an empire!")
    else:
        image = await render_forbes_leaderboard(bot, rows, int(rows[0]["total_players"]))
        await callback.message.answer_photo(
            BufferedInputFile(image, filename="forbes_list.png"),
            caption="🏆 <b>FORBES LIST</b> · Ranked by net worth only",
            reply_markup=main_menu(),
        )
    await callback.answer()


async def mining_text(chat_id: int):
    async with get_pool().acquire() as conn:
        event = await conn.fetchrow("SELECT * FROM timed_mining_events WHERE chat_id=$1 ORDER BY id DESC LIMIT 1", chat_id)
        if not event:
            return "No mining event has run in this group yet. Run /miningwar once to register this group.", None
        miners = await conn.fetch("""SELECT p.display_name,p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth
            FROM timed_mining_players t JOIN players p ON p.telegram_id=t.player_id
            LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id
            WHERE t.event_id=$1 ORDER BY worth DESC,p.reputation DESC,p.telegram_id ASC""", event["id"])
        team = await conn.fetchrow("SELECT id,team_size,status FROM mining_teams WHERE event_id=$1", event["id"])
    status = str(event["status"]).title()
    lines = [f"• {p['display_name']} — 💎 {int(p['worth']):,} NW" for p in miners]
    text = (f"⛏ <b>EMPIRE CENTURY — MINING #{event['id']}</b>\n"
            f"Status: <b>{status}</b>\nApplicants: <b>{len(miners)}</b>\n\n"
            + ("\n".join(lines) if lines else "No miners have joined yet."))
    if team:
        text += f"\n\nQualified team: <b>{team['team_size']} players</b> · {team['status'].title()}"
    if event["status"] == "joining":
        text += "\n\nAt close: top 3 qualify with 3–4 applicants; top 5 qualify with 5 or more. Minimum 3."
        return text, InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⛏ JOIN MINING", callback_data=f"tmj_{event['id']}")]])
    if event["status"] == "skipped":
        text += "\n\nThis event was skipped because fewer than 3 eligible players joined."
    return text, None


@dp.message(Command("miningwar"))
async def mining_war_command(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Start mining from inside a Telegram group.")
        return
    await register_player(message.from_user)
    await register_mining_group(message.chat.id, message.chat.title or 'Mining group')
    await message.answer('✅ This group is registered for EMPIRE CENTURY mining. Events open automatically every 2 hours with a 5-minute joining window. At least 3 players must join; otherwise this group skips that event.')


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
    await message.answer(
        "🏛 <b>Clubs are managed by the game.</b>\n"
        "Players do not create clubs, join by tags, or donate to club treasuries. "
        "When your business reaches an eligible level, join the level competition from its private lobby."
    )

@dp.message(Command('donate'))
async def donate_command(message: Message):
    await message.answer("Club donations are disabled. Competitions are managed automatically by the game.")

def battle_keyboard(battle_id, picked=None, outcomes=None):
    picked = set(picked or [])
    icons = {"money":"💰", "normal":"⚪", "empty":"🕳"}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=(icons[outcomes[n-1]] if n in picked and outcomes else ("🔓" if n in picked else "⬛")), callback_data=f"box_b_{battle_id}_{n}") for n in range(start, start+3)]
        for start in (1,4,7)
    ])

def setup_keyboard(slot, items):
    icons = {"money":"💰","normal":"⚪","empty":"🕳"}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{n} {icons[items[n-1]]}", callback_data=f"box_s_{slot}_{n}") for n in range(start,start+3)]
        for start in (1,4,7)
    ] + [[InlineKeyboardButton(text="💾 Save layout", callback_data=f"box_save_{slot}")] ])

@dp.message(Command("boxes"))
async def boxes_command(message: Message):
    if message.chat.type != "private":
        await message.answer("Set up your boxes in a private chat with the bot.")
        return
    parts=(message.text or "").split()
    slot=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 1
    if slot not in range(1,6):
        await message.answer("Choose layout slot 1–5: /boxes 1")
        return
    async with get_pool().acquire() as conn:
        row=await conn.fetchrow("SELECT outcomes FROM box_layouts WHERE player_id=$1 AND layout_no=$2",message.from_user.id,slot)
        draft=await conn.fetchrow("SELECT outcomes FROM box_layout_drafts WHERE player_id=$1 AND layout_no=$2",message.from_user.id,slot)
    items=json.loads(row["outcomes"]) if row else json.loads(draft["outcomes"]) if draft else new_layout()
    async with get_pool().acquire() as conn:
        await conn.execute("INSERT INTO box_layout_drafts(player_id,layout_no,outcomes) VALUES($1,$2,$3) ON CONFLICT(player_id,layout_no) DO UPDATE SET outcomes=excluded.outcomes",message.from_user.id,slot,json.dumps(items))
    await message.answer(f"🎭 <b>BOX SETUP · LAYOUT {slot}/5</b>\nTap boxes to cycle Money → Normal → Empty. Save only when there are exactly 3 of each.",reply_markup=setup_keyboard(slot,items))

@dp.callback_query(F.data.startswith("box_s_"))
async def box_setup_click(c: CallbackQuery):
    _, _, slot_s, n_s = c.data.split("_")
    slot, n = int(slot_s), int(n_s)
    async with get_pool().acquire() as conn:
        row=await conn.fetchrow("SELECT outcomes FROM box_layout_drafts WHERE player_id=$1 AND layout_no=$2",c.from_user.id,slot)
    if not row:
        await c.answer("Run /boxes first.",show_alert=True); return
    items=json.loads(row["outcomes"])
    items[n-1]={"money":"normal","normal":"empty","empty":"money"}[items[n-1]]
    async with get_pool().acquire() as conn:
        await conn.execute("UPDATE box_layout_drafts SET outcomes=$1 WHERE player_id=$2 AND layout_no=$3",json.dumps(items),c.from_user.id,slot)
    await c.message.edit_reply_markup(reply_markup=setup_keyboard(slot,items))
    counts=" · ".join(f"{k.title()}: {items.count(k)}" for k in ("money","normal","empty"))
    await c.answer(counts)

@dp.callback_query(F.data.startswith("box_save_"))
async def box_setup_save(c: CallbackQuery):
    slot=int(c.data.rsplit("_",1)[1])
    async with get_pool().acquire() as conn:
        row=await conn.fetchrow("SELECT outcomes FROM box_layout_drafts WHERE player_id=$1 AND layout_no=$2",c.from_user.id,slot)
    if not row:
        await c.answer("Run /boxes first.",show_alert=True); return
    items=json.loads(row["outcomes"])
    if not await save_layout(c.from_user.id,slot,items):
        await c.answer("Need exactly 3 Money, 3 Normal, and 3 Empty boxes.",show_alert=True); return
    await c.answer(f"Layout {slot}/5 saved!",show_alert=True)
    await c.message.edit_text(f"✅ Layout {slot}/5 saved.\n💰 Money ×3 · ⚪ Normal ×3 · 🕳 Empty ×3")

@dp.message(Command('war'))
async def war_command(message: Message):
    parts=(message.text or "").split()
    if message.chat.type in ("group","supergroup") and message.reply_to_message and message.reply_to_message.from_user:
        defender=int(message.reply_to_message.from_user.id)
    elif len(parts)==2 and parts[1].isdigit():
        defender=int(parts[1])
    else:
        await message.answer("Use /war TELEGRAM_ID in private chat, or reply to a player's message with /war in a group.")
        return
    if message.chat.type in ("group","supergroup"):
        try:
            await bot.send_message(message.from_user.id, "⚔️ You started a business war from the group. Open the boxes below.")
        except Exception:
            await message.answer("Open the bot in private chat and press /start first, then retry the group reply /war.")
            return
    if defender==message.from_user.id:
        await message.answer("You cannot battle yourself."); return
    async with get_pool().acquire() as conn:
        a=await conn.fetchrow("SELECT telegram_id FROM players WHERE telegram_id=$1",message.from_user.id)
        d=await conn.fetchrow("SELECT display_name FROM players WHERE telegram_id=$1",defender)
        active=await conn.fetchval("SELECT id FROM box_battles WHERE challenger_id=$1 AND status='active'",message.from_user.id)
    if not a or not d:
        await message.answer("Both players must have started the game with /start."); return
    if active:
        await message.answer("Finish your current battle first."); return
    outcomes=await random_layout(defender)
    challenger_worth=await net_worth(message.from_user.id)
    defender_worth=await net_worth(defender)
    async with get_pool().acquire() as conn:
        battle_id=await conn.fetchval("INSERT INTO box_battles(challenger_id,defender_id,outcomes,challenger_net_worth,defender_net_worth) VALUES($1,$2,$3,$4,$5) RETURNING id",message.from_user.id,defender,json.dumps(outcomes),challenger_worth,defender_worth)
    battle_text=f"⚔️ <b>BUSINESS WAR</b>\nChallenger: {message.from_user.full_name}\nYour net worth: <b>{challenger_worth:,}</b>\nDefender: {d['display_name']}\nDefender net worth: <b>{defender_worth:,}</b>\n\nOpen boxes until the first pair matches. 💰 Money pair = ×1.2, ⚪ Normal pair = ×1.0, 🕳 Empty pair = ×0.8. Your adjusted battle net worth is compared with the defender's net worth."
    if message.chat.type in ("group","supergroup"):
        await bot.send_message(message.from_user.id,battle_text,reply_markup=battle_keyboard(battle_id))
        await message.answer("⚔️ Business war started. Check your private chat with the bot to play.")
    else:
        await message.answer(battle_text,reply_markup=battle_keyboard(battle_id))

@dp.callback_query(F.data.startswith("box_b_"))
async def business_battle_pick(c: CallbackQuery):
    _,_,battle_s,n_s=c.data.split("_")
    battle_id,n=int(battle_s),int(n_s)
    icons={"money":"💰","normal":"⚪","empty":"🕳"}
    labels={"money":"Money ×1.2","normal":"Normal ×1.0","empty":"Empty ×0.8"}
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            b=await conn.fetchrow("SELECT * FROM box_battles WHERE id=$1",battle_id)
            if not b:
                await c.answer("Battle not found.",show_alert=True); return
            if b["challenger_id"]!=c.from_user.id:
                await c.answer("Only the challenger plays this business war.",show_alert=True); return
            picked=json.loads(b["picked"])
            outcomes=json.loads(b["outcomes"])
            if b["status"]!="active":
                await c.answer("This battle has ended.",show_alert=True); return
            if n in picked:
                await c.answer("That box was already opened.",show_alert=True); return
            kind=outcomes[n-1]
            picked.append(n)
            opened=[outcomes[x-1] for x in picked]
            pair=next((k for k in ("money","normal","empty") if opened.count(k)>=2),None)
            finished=pair is not None and len(picked)>=3  # reveal at least three boxes
            status="finished" if finished else "active"
            await conn.execute("UPDATE box_battles SET picked=$1,result_kind=$2,status=$3,round_no=round_no+1 WHERE id=$4",json.dumps(picked),pair,status,battle_id)
            challenger=b["challenger_id"]
            defender=b["defender_id"]
            challenger_worth=int(b["challenger_net_worth"])
            defender_worth=int(b["defender_net_worth"])
            challenger_row=await conn.fetchrow("SELECT display_name FROM players WHERE telegram_id=$1",challenger)
            defender_row=await conn.fetchrow("SELECT display_name FROM players WHERE telegram_id=$1",defender)
            challenger_name=challenger_row["display_name"] if challenger_row else "Challenger"
            defender_name=defender_row["display_name"] if defender_row else "Defender"
    board=battle_keyboard(battle_id,picked,outcomes)
    result=f"📦 Box {n} revealed: {icons[kind]} <b>{labels[kind]}</b>"
    if finished:
        multiplier={"money":1.2,"normal":1.0,"empty":0.8}[pair]
        adjusted=int(challenger_worth*multiplier)
        difference=adjusted-defender_worth
        result+=f"\n\n🔗 First pair: {icons[pair]} <b>{labels[pair]}</b>"
        result+=f"\n\n🏁 <b>BUSINESS WAR · FINISHED</b>\n\n<b>{challenger_name}</b>\n{challenger_worth:,} × {multiplier:.1f} = <b>{adjusted:,}</b>\n\n<b>{defender_name}</b>\n{defender_worth:,}\n\n<b>NET WORTH DIFFERENCE: {abs(difference):,}</b>\n{'🏆 Challenger wins!' if difference>0 else '🛡 Defender wins!' if difference<0 else '🤝 It is a tie!'}"
        if difference>0:
            result+="\n\n🏆 <b>Challenger wins!</b>"
            async with get_pool().acquire() as conn:
                await conn.execute("UPDATE players SET gold_grams=gold_grams+1,determination=LEAST(2000,determination+200) WHERE telegram_id=$1",challenger)
                await conn.execute("UPDATE players SET gold_grams=GREATEST(0,gold_grams-1),determination=LEAST(2000,determination+100) WHERE telegram_id=$1",defender)
        elif difference<0:
            result+="\n\n🛡 <b>Defender wins!</b>"
            async with get_pool().acquire() as conn:
                await conn.execute("UPDATE players SET determination=LEAST(2000,determination+100) WHERE telegram_id=$1",challenger)
        else:
            result+="\n\n🤝 <b>It's a tie!</b>"
        result+="\n\n✅ <b>BATTLE ENDED</b> · Final box board remains visible below."
    else:
        result+=f"\n\n📦 <b>Boxes opened: {len(picked)}/9</b>\n{'Pair found — open one more box to confirm the result.' if pair else 'Find a matching pair. At least 3 boxes must be opened before the result is final.'}"
    await c.message.edit_text(result,reply_markup=board)
    await c.answer(f"{icons[kind]} {labels[kind]}")
    

@dp.message(Command('help'))
async def help_command(message: Message):
    await message.answer(
        "🎮 <b>EMPIRE CENTURY — CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose a section below. Use the inline buttons to open your dashboard, markets, clubs, rankings, event countdowns, and rules.\n\n"
        "💡 Event countdowns can be refreshed anytime from the Events screen. Seasons last 7 days; temporary cash and business progress reset at settlement, while reputation and eligible permanent assets persist.",
        reply_markup=main_menu())


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


@dp.message(Command('rank'))
async def rank_command(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message and message.reply_to_message.from_user else message.from_user
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow('''WITH ranked AS (
                SELECT p.telegram_id, p.display_name, p.is_npc, p.cash, p.business_level,
                       p.stocks, p.gold_grams,
                       p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.asset_value,0) AS worth,
                       ROW_NUMBER() OVER (ORDER BY p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.asset_value,0) DESC,
                                                    p.telegram_id ASC) AS position,
                       COUNT(*) OVER () AS total_players
                FROM players p
                LEFT JOIN player_asset_valuation a ON a.player_id=p.telegram_id
            )
            SELECT * FROM ranked WHERE telegram_id=$1''', target.id)
    if not row:
        await message.answer(f"📊 {target.full_name} hasn't started Business Life yet.")
        return
    assets_value = max(0, int(row["worth"]) - int(row["cash"]) - int(row["stocks"]) - int(row["gold_grams"] * 10))
    await message.answer(
        f"📊 <b>BUSINESS LIFE RANK</b>\n\n"
        f"👤 <b>{row['display_name']}</b>\n"
        f"🏆 Rank: <b>#{row['position']}</b> of {row['total_players']} players\n"
        f"💎 Net worth: <b>{int(row['worth']):,}</b>\n\n"
        f"💵 Cash: <b>{int(row['cash']):,}</b>\n"
        f"🪙 Gold: <b>{row['gold_grams']} g</b>\n"
        f"📈 Stocks: <b>{int(row['stocks']):,}</b>\n"
        f"🏢 Business level: <b>{row['business_level']}/54</b>\n"
        f"⭐ Reputation: <b>{int(row['reputation']):,}</b>\n"
        f"🏗️ Owned assets value: <b>{assets_value:,}</b>"
    )


@dp.message(Command('ranking'))
async def ranking_command(message: Message):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch('''SELECT p.telegram_id,p.display_name,p.is_npc,p.business_level,
            p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.asset_value,0) AS worth,
            COUNT(*) OVER () AS total_players
            FROM players p LEFT JOIN player_asset_valuation a ON a.player_id=p.telegram_id
            ORDER BY worth DESC,p.telegram_id ASC LIMIT 10''')
    if not rows:
        await message.answer("No players ranked yet.")
        return
    image = await render_forbes_leaderboard(bot, rows, int(rows[0]["total_players"]))
    await message.answer_photo(
        BufferedInputFile(image, filename="forbes_list.png"),
        caption="🏆 <b>FORBES LIST</b> · Ranked by net worth only",
    )


@dp.message(Command('season'))
async def season_leaderboard_command(message: Message):
    async with get_pool().acquire() as conn:
        season = await conn.fetchrow(
            "SELECT id,starts_at,ends_at FROM seasons WHERE settled_at IS NULL ORDER BY id DESC LIMIT 1"
        )
        if not season:
            await message.answer("No active season found.")
            return
        rows = await conn.fetch('''SELECT p.telegram_id,p.display_name,p.is_npc,p.business_level,
            p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(a.asset_value,0) AS worth,
            COUNT(*) OVER () AS total_players
            FROM players p LEFT JOIN player_asset_valuation a ON a.player_id=p.telegram_id
            WHERE p.season_id=$1
            ORDER BY worth DESC,p.telegram_id ASC LIMIT 10''', season["id"])
    if not rows:
        await message.answer("No players have joined this season yet.")
        return
    starts = season["starts_at"].strftime("%d %b") if hasattr(season["starts_at"], "strftime") else str(season["starts_at"])[:10]
    ends = season["ends_at"].strftime("%d %b") if hasattr(season["ends_at"], "strftime") else str(season["ends_at"])[:10]
    subtitle = f"SEASON {season['id']}  •  {starts} — {ends}"
    image = await render_forbes_leaderboard(
        bot, rows, int(rows[0]["total_players"]),
        title="WEEKLY LEADERBOARD", subtitle=subtitle,
    )
    await message.answer_photo(
        BufferedInputFile(image, filename=f"season_{season['id']}_leaderboard.png"),
        caption="📅 <b>WEEKLY SEASON LEADERBOARD</b> · Net worth ranking",
    )


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


@dp.callback_query(F.data == 'help_club')
async def help_club(callback: CallbackQuery):
    await callback.message.edit_text(
        '🏰 <b>SYSTEM CLUB DIVISION</b>\n\n'
        'Clubs are created and managed by the game. Players cannot create clubs, join by tags, or donate.\n\n'
        'A five-minute level-specific competition lobby opens hourly. Join from its private message, follow the four roster updates, then play two different opponents. Win both best-of-three matches to pass.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏰 Club Rules", callback_data="rule_club", style="primary")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="more_menu"),
             InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
        ]))
    await callback.answer()


@dp.callback_query(F.data == 'help_gold')
async def help_gold(callback: CallbackQuery):
    await callback.message.edit_text(
        '🪙 <b>GOLD EXCHANGE</b>\n'
        'Rate: 1,000 cash per gram.\n'
        'Buy: /gold buy 2\n'
        'Sell: /gold sell 1',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📘 Economy Rules", callback_data="rule_economy")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="more_menu"),
             InlineKeyboardButton(text="🏠 Home", callback_data="dashboard")],
        ]))
    await callback.answer()


@dp.callback_query(F.data == 'help_assets')
async def help_assets(callback: CallbackQuery):
    await callback.message.edit_text(
        '🏬 <b>ASSET COLLECTION</b>\n'
        'Browse /assetshop, buy with /buyasset sports_car, and check your collection with /inventory.',
        reply_markup=back_home_keyboard("more_menu"))
    await callback.answer()


@dp.callback_query(F.data == 'help_industry')
async def help_industry(callback: CallbackQuery):
    await callback.message.edit_text(
        '🏭 <b>INDUSTRY</b>\n'
        'View buildings with /industry and buy one with /buildindustry workshop. Buildings generate reputation over time.',
        reply_markup=back_home_keyboard("more_menu"))
    await callback.answer()

async def main():
    await connect()
    npc_count = await seed_npcs()
    logging.getLogger(__name__).info('NPC roster ready: %s game characters', npc_count)
    season_task = asyncio.create_task(season_scheduler(), name='season-scheduler')
    timed_task = asyncio.create_task(timed_scheduler(bot), name='timed-events-scheduler')
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        season_task.cancel()
        timed_task.cancel()
        await asyncio.gather(season_task, timed_task, return_exceptions=True)
        await close()
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())