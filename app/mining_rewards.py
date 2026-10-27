"""Group-scoped mining collection rewards and group net-worth rankings."""
from aiogram import BaseMiddleware
from aiogram.types import Message
from app.db import get_pool


class MiningGroupMemberTracker(BaseMiddleware):
    """Record known bot players who speak in registered groups.

    Telegram bots cannot enumerate every group member, so rankings and passive
    bonuses cover registered players observed in that group.
    """
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.chat.type in ("group", "supergroup"):
            user = event.from_user
            if user and not user.is_bot:
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        """INSERT INTO mining_groups(chat_id,title) VALUES($1,$2)
                           ON CONFLICT(chat_id) DO UPDATE SET title=EXCLUDED.title""",
                        event.chat.id, (event.chat.title or "Mining group")[:120],
                    )
                    await conn.execute(
                        """INSERT INTO mining_group_members(chat_id,player_id,last_seen_at)
                           SELECT $1,telegram_id,NOW() FROM players WHERE telegram_id=$2
                           ON CONFLICT(chat_id,player_id) DO UPDATE SET last_seen_at=NOW()""",
                        event.chat.id, user.id,
                    )
        return await handler(event, data)


async def award_mining_group_win(chat_id: int, event_id: int, team_id: int) -> None:
    """Give team members +30% and known members of their group +15% until next mining."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO mining_group_rewards(chat_id,event_id,expires_at,awarded_at)
                   VALUES($1,$2,NOW()+INTERVAL '2 hours',NOW())
                   ON CONFLICT(chat_id) DO UPDATE SET event_id=EXCLUDED.event_id,
                     expires_at=EXCLUDED.expires_at,awarded_at=EXCLUDED.awarded_at""",
                chat_id, event_id,
            )
            await conn.execute(
                "DELETE FROM mining_group_reward_players WHERE chat_id=$1", chat_id
            )
            await conn.execute(
                """INSERT INTO mining_group_reward_players(chat_id,event_id,player_id)
                   SELECT $1,$2,player_id FROM mining_team_players WHERE team_id=$3
                   ON CONFLICT DO NOTHING""",
                chat_id, event_id, team_id,
            )


async def collection_bonus_multiplier(conn, player_id: int) -> float:
    """Return 1.30 for a current winning-team member, else 1.15 for a group member."""
    row = await conn.fetchrow(
        """SELECT
             CASE
               WHEN EXISTS (
                 SELECT 1 FROM mining_group_rewards r
                 JOIN mining_group_reward_players rp
                   ON rp.chat_id=r.chat_id AND rp.event_id=r.event_id
                 WHERE rp.player_id=$1 AND r.expires_at>NOW()
               ) THEN 1.30
               WHEN EXISTS (
                 SELECT 1 FROM mining_group_members gm
                 JOIN mining_group_rewards r ON r.chat_id=gm.chat_id
                 WHERE gm.player_id=$1 AND r.expires_at>NOW()
               ) THEN 1.15
               ELSE 1.0
             END AS multiplier""",
        player_id,
    )
    return float(row["multiplier"]) if row else 1.0


async def top_mining_groups(limit: int = 10):
    """Rank groups by combined net worth of registered players observed in them."""
    async with get_pool().acquire() as conn:
        return await conn.fetch(
            """SELECT g.chat_id,g.title,COUNT(DISTINCT gm.player_id) AS player_count,
                      COALESCE(SUM(p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)
                        +COALESCE(v.asset_value,0)),0) AS total_worth,
                      MAX(CASE WHEN r.expires_at>NOW() THEN 1 ELSE 0 END) AS has_active_bonus
               FROM mining_groups g
               LEFT JOIN mining_group_members gm ON gm.chat_id=g.chat_id
               LEFT JOIN players p ON p.telegram_id=gm.player_id
               LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id
               LEFT JOIN mining_group_rewards r ON r.chat_id=g.chat_id
               GROUP BY g.chat_id,g.title
               ORDER BY total_worth DESC,player_count DESC,g.title ASC
               LIMIT $1""",
            limit,
        )
