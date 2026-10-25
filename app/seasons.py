from __future__ import annotations

import asyncio
import logging
from app.db import get_pool

log = logging.getLogger(__name__)
CHECK_INTERVAL_SECONDS = 30
SEASON_DAYS = 7
TOP_REWARD_COUNT = 50

async def settle_expired_season() -> bool:
    """Settle one expired season exactly once, snapshot rankings, then reset temporary progress.

    Reputation persists. Cash and business level reset. Permanent rewards are inventory records,
    not an invented cash payout; the exact reward asset can be configured later.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Serialize settlement attempts, including if multiple bot instances are running.
            await conn.execute("SELECT pg_advisory_xact_lock(728194006)")
            season = await conn.fetchrow(
                "SELECT * FROM seasons WHERE settled_at IS NULL ORDER BY id DESC LIMIT 1 FOR UPDATE"
            )
            if not season:
                return False
            expired = await conn.fetchval("SELECT $1::timestamptz <= NOW()", season["ends_at"])
            if not expired:
                return False

            # Until the full asset/stock market is implemented, this ranking uses cash only.
            # Reputation is retained but is not incorrectly mixed into the temporary net-worth score.
            players = await conn.fetch(
                """SELECT telegram_id, display_name, cash, reputation, business_level
                   FROM players WHERE season_id = $1
                   ORDER BY cash DESC, business_level DESC, reputation DESC, telegram_id ASC""",
                season["id"],
            )
            for rank, player in enumerate(players, start=1):
                eligible = rank <= TOP_REWARD_COUNT
                await conn.execute(
                    """INSERT INTO season_results
                       (season_id, telegram_id, display_name, final_cash, final_reputation,
                        final_business_level, season_rank, permanent_reward_eligible)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                       ON CONFLICT (season_id, telegram_id) DO NOTHING""",
                    season["id"], player["telegram_id"], player["display_name"], player["cash"],
                    player["reputation"], player["business_level"], rank, eligible,
                )
                if eligible:
                    await conn.execute(
                        """INSERT INTO permanent_assets(owner_id, asset_code, source_season_id, label)
                           VALUES ($1, 'fosbu_season_reward', $2, $3)
                           ON CONFLICT (owner_id, asset_code, source_season_id) DO NOTHING""",
                        player["telegram_id"], season["id"], f"Fosbu Season Reward #{rank}",
                    )

            await conn.execute("UPDATE seasons SET settled_at = NOW() WHERE id = $1", season["id"])
            next_season = await conn.fetchrow(
                """INSERT INTO seasons(starts_at, ends_at)
                   VALUES (NOW(), NOW() + ($1::int * INTERVAL '1 day'))
                   RETURNING id""",
                SEASON_DAYS,
            )
            # Preserve reputation and permanent_assets. Reset the temporary business cycle.
            await conn.execute(
                """UPDATE players SET cash = 1000, business_level = 1,
                   last_collected_at = NOW(), season_id = $1""",
                next_season["id"],
            )
            # Employees are temporary season relationships and must not survive the reset.
            await conn.execute("DELETE FROM employees")
            log.info("Settled season %s; started season %s; snapshotted %s players",
                     season["id"], next_season["id"], len(players))
            return True

async def season_scheduler() -> None:
    """Persistent scheduler loop; database state makes restarts safe."""
    while True:
        try:
            if await settle_expired_season():
                log.info("Season rollover completed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Season settlement check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
