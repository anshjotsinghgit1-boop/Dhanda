from datetime import datetime, timezone
from app.db import get_pool

OFFLINE_CAP_SECONDS = 8 * 60 * 60
BASE_CASH_PER_MINUTE = 10

def upgrade_cost(level: int) -> int:
    return 500 * level * level

def production_per_minute(level: int) -> int:
    return BASE_CASH_PER_MINUTE * level

async def register_player(user) -> None:
    name = (user.full_name or 'Player')[:80]
    async with get_pool().acquire() as conn:
        await conn.execute('''
            INSERT INTO players (telegram_id, username, display_name, season_id)
            VALUES ($1, $2, $3, COALESCE((SELECT id FROM seasons WHERE settled_at IS NULL ORDER BY id DESC LIMIT 1), 1))
            ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username,
              display_name = EXCLUDED.display_name
        ''', user.id, user.username, name)

async def get_player(telegram_id: int):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow('SELECT * FROM players WHERE telegram_id=$1', telegram_id)

async def collect_income(telegram_id: int) -> tuple[int, int]:
    """Collect capped passive income, applying any active temporary mining boost."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            player = await conn.fetchrow('SELECT * FROM players WHERE telegram_id=$1 FOR UPDATE', telegram_id)
            if not player:
                return 0, 0
            now = datetime.now(timezone.utc)
            elapsed = max(0, min((now - player['last_collected_at']).total_seconds(), OFFLINE_CAP_SECONDS))
            base = int(elapsed // 60) * production_per_minute(player['business_level'])
            boost = float(player['collection_boost'] or 1.0)
            if player['collection_boost_until'] is None or player['collection_boost_until'] <= now:
                boost = 1.0
                await conn.execute('UPDATE players SET collection_boost=1.0,collection_boost_until=NULL WHERE telegram_id=$1', telegram_id)
            gross = int(base * boost)
            boss_share = 0
            employee = await conn.fetchrow('SELECT boss_id FROM employees WHERE employee_id=$1', telegram_id)
            if employee and gross > 0:
                boss_share = gross * 5 // 100
                gross -= boss_share
                await conn.execute('UPDATE players SET cash=cash+$1 WHERE telegram_id=$2', boss_share, employee['boss_id'])
            await conn.execute('UPDATE players SET cash=cash+$1,last_collected_at=$2 WHERE telegram_id=$3', gross, now, telegram_id)
            return gross, boss_share

async def upgrade_business(telegram_id: int) -> tuple[bool, str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            p = await conn.fetchrow('SELECT cash, business_level FROM players WHERE telegram_id=$1 FOR UPDATE', telegram_id)
            if not p:
                return False, 'Use /start first.'
            level = p['business_level']
            if level >= 54:
                return False, 'Your business is already at the maximum level (54).'
            cost = upgrade_cost(level)
            if p['cash'] < cost:
                return False, f'You need {cost:,} cash to upgrade. You have {p["cash"]:,}.'
            await conn.execute('UPDATE players SET cash=cash-$1, business_level=business_level+1 WHERE telegram_id=$2', cost, telegram_id)
            return True, f'Business upgraded to level {level + 1}! Production is now {production_per_minute(level + 1):,} cash/min.'
