"""Gold, asset collection and industrial park economy services."""
from datetime import datetime, timezone
from decimal import Decimal
from app.db import get_pool

GOLD_RATE_CASH_PER_GRAM = 1000
PERMANENT_ASSET_CAP = 25_000

async def buy_gold(player_id: int, grams: Decimal) -> tuple[bool, str]:
    if grams <= 0 or grams > Decimal("100000"):
        return False, "Enter a positive amount up to 100,000 grams."
    cost = int(grams * GOLD_RATE_CASH_PER_GRAM)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            p = await conn.fetchrow("SELECT cash FROM players WHERE telegram_id=$1 FOR UPDATE", player_id)
            if not p:
                return False, "Use /start first."
            if p["cash"] < cost:
                return False, f"You need {cost:,} cash; you have {p['cash']:,}."
            await conn.execute("UPDATE players SET cash=cash-$1, gold_grams=gold_grams+$2 WHERE telegram_id=$3", cost, grams, player_id)
    return True, f"Bought {grams.normalize()} g of gold for {cost:,} cash. Gold adds {int(grams * 10):,} net worth."

async def sell_gold(player_id: int, grams: Decimal) -> tuple[bool, str]:
    if grams <= 0:
        return False, "Enter a positive amount of gold."
    value = int(grams * GOLD_RATE_CASH_PER_GRAM)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            p = await conn.fetchrow("SELECT gold_grams FROM players WHERE telegram_id=$1 FOR UPDATE", player_id)
            if not p or p["gold_grams"] < grams:
                return False, "You don't have that much gold."
            await conn.execute("UPDATE players SET gold_grams=gold_grams-$1, cash=cash+$2 WHERE telegram_id=$3", grams, value, player_id)
    return True, f"Sold {grams.normalize()} g of gold for {value:,} cash."

async def list_assets():
    async with get_pool().acquire() as conn:
        return await conn.fetch("SELECT * FROM asset_catalog WHERE category <> 'permanent' ORDER BY price")

async def buy_asset(player_id: int, asset_key: str) -> tuple[bool, str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            asset = await conn.fetchrow("SELECT * FROM asset_catalog WHERE asset_key=$1 AND category <> 'permanent'", asset_key)
            if not asset:
                return False, "That asset is not available in the shop."
            p = await conn.fetchrow("SELECT cash FROM players WHERE telegram_id=$1 FOR UPDATE", player_id)
            if not p:
                return False, "Use /start first."
            if p["cash"] < asset["price"]:
                return False, f"You need {asset['price']:,} cash to buy {asset['name']}."
            await conn.execute("UPDATE players SET cash=cash-$1 WHERE telegram_id=$2", asset["price"], player_id)
            await conn.execute("""INSERT INTO player_assets(player_id,asset_id,quantity,permanent)
                VALUES($1,$2,1,FALSE) ON CONFLICT(player_id,asset_id,permanent)
                DO UPDATE SET quantity=player_assets.quantity+1""", player_id, asset["id"])
    return True, f"Purchased {asset['name']} for {asset['price']:,} cash."

async def inventory(player_id: int):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("""SELECT c.name,c.net_worth,c.operation_bonus,a.quantity,a.permanent
            FROM player_assets a JOIN asset_catalog c ON c.id=a.asset_id
            WHERE a.player_id=$1 ORDER BY a.permanent DESC,c.net_worth DESC""", player_id)
        p = await conn.fetchrow("SELECT gold_grams FROM players WHERE telegram_id=$1", player_id)
    return rows, p["gold_grams"] if p else Decimal(0)

async def buy_industrial_building(player_id: int, building_key: str) -> tuple[bool, str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            b = await conn.fetchrow("SELECT * FROM industrial_buildings WHERE building_key=$1", building_key)
            p = await conn.fetchrow("SELECT cash,business_level FROM players WHERE telegram_id=$1 FOR UPDATE", player_id)
            if not b or not p:
                return False, "Building or player not found."
            if p["business_level"] < b["unlock_level"]:
                return False, f"This building unlocks at business level {b['unlock_level']}."
            if p["cash"] < b["price"]:
                return False, f"You need {b['price']:,} cash."
            await conn.execute("UPDATE players SET cash=cash-$1 WHERE telegram_id=$2", b["price"], player_id)
            await conn.execute("""INSERT INTO player_industries(player_id,building_id,quantity,last_settled_at)
                VALUES($1,$2,1,NOW()) ON CONFLICT(player_id,building_id)
                DO UPDATE SET quantity=player_industries.quantity+1""", player_id, b["id"])
    return True, f"Built {b['name']}. It generates {b['reputation_per_hour']:,} reputation/hour and adds {b['operation_bonus']} operation bonus."

async def settle_industry(player_id: int) -> int:
    """Accrue industrial reputation since each building's last settlement."""
    total = 0
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch("""SELECT pi.building_id,pi.quantity,pi.last_settled_at,b.reputation_per_hour
                FROM player_industries pi JOIN industrial_buildings b ON b.id=pi.building_id
                WHERE pi.player_id=$1 FOR UPDATE OF pi""", player_id)
            now = datetime.now(timezone.utc)
            for row in rows:
                hours = max(0, int((now-row["last_settled_at"]).total_seconds() // 3600))
                earned = hours * row["reputation_per_hour"] * row["quantity"]
                if earned:
                    total += earned
                    await conn.execute("UPDATE player_industries SET last_settled_at=$1 WHERE player_id=$2 AND building_id=$3", now, player_id, row["building_id"])
            if total:
                await conn.execute("UPDATE players SET reputation=reputation+$1 WHERE telegram_id=$2", total, player_id)
    return total
