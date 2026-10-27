from datetime import datetime, timezone
from app.db import get_pool
from app.mining_rewards import collection_bonus_multiplier

OFFLINE_CAP_SECONDS = 8 * 60 * 60
BASE_CASH_PER_SECOND = 1

def upgrade_cost(level: int) -> int:
    return 500 * level * level

def production_per_second(level: int) -> int:
    return BASE_CASH_PER_SECOND * level

# Backwards-compatible display helper for older parts of the UI.
def production_per_minute(level: int) -> int:
    return production_per_second(level) * 60

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
            base = int(elapsed) * production_per_second(player['business_level'])
            boost = float(player['collection_boost'] or 1.0)
            if player['collection_boost_until'] is None or player['collection_boost_until'] <= now:
                boost = 1.0
                await conn.execute('UPDATE players SET collection_boost=1.0,collection_boost_until=NULL WHERE telegram_id=$1', telegram_id)
            mining_boost = await collection_bonus_multiplier(conn, telegram_id)
            gross = int(base * boost * mining_boost)
            boss_share = 0
            employee = await conn.fetchrow('SELECT boss_id FROM employees WHERE employee_id=$1', telegram_id)
            if employee and gross > 0:
                boss_share = gross * 5 // 100
                gross -= boss_share
                await conn.execute('UPDATE players SET cash=cash+$1 WHERE telegram_id=$2', boss_share, employee['boss_id'])
            await conn.execute('UPDATE players SET cash=cash+$1,last_collected_at=$2 WHERE telegram_id=$3', gross, now, telegram_id)
            return gross, boss_share

async def auto_upgrade_business(telegram_id: int) -> list[str]:
    """Automatically level up whenever the treasury reaches the next target.

    Cash spent on an upgrade is deducted from the treasury only; stocks, gold,
    reputation and owned assets are left untouched, so net worth is not reset.
    From level 12 onward, two club-battle wins are still required per level.
    """
    messages: list[str] = []
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            p = await conn.fetchrow(
                'SELECT cash, business_level, club_battle_wins FROM players WHERE telegram_id=$1 FOR UPDATE',
                telegram_id,
            )
            if not p:
                return messages
            cash = int(p['cash'])
            level = int(p['business_level'])
            wins = int(p['club_battle_wins'] or 0)
            while level < 54:
                cost = upgrade_cost(level)
                if cash < cost:
                    break
                if level >= 12 and wins < 2:
                    break
                cash -= cost
                level += 1
                if level > 12:
                    wins = 0
                await conn.execute(
                    '''UPDATE players
                       SET cash=$1, business_level=$2,
                           club_battle_wins=CASE WHEN $2 > 12 THEN 0 ELSE club_battle_wins END
                       WHERE telegram_id=$3''',
                    cash, level, telegram_id,
                )
                messages.append(
                    f'🏆 Business reached level {level}! Production: '
                    f'{production_per_second(level):,} cash/sec.'
                )
            return messages


async def upgrade_business(telegram_id: int) -> tuple[bool, str]:
    """Compatibility wrapper for older command handlers."""
    messages = await auto_upgrade_business(telegram_id)
    if messages:
        return True, '\n'.join(messages)
    p = await get_player(telegram_id)
    if not p:
        return False, 'Use /start first.'
    level = int(p['business_level'])
    if level >= 54:
        return False, 'Your business is already at the maximum level (54).'
    cost = upgrade_cost(level)
    if level >= 12 and int(p['club_battle_wins'] or 0) < 2:
        remaining = 2 - int(p['club_battle_wins'] or 0)
        return False, f'🏛 Club battle requirement: win {remaining} more match(es) before reaching level {level + 1}.'
    return False, f'Keep building: reach {cost:,} cash to unlock level {level + 1}.'
