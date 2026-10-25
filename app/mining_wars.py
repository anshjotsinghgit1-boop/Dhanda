"""Single-lobby group mining. The strongest 3 or 5 applicants qualify at start."""
from app.db import get_pool


async def create_war(chat_id: int, creator_id: int, team_size: int = 5) -> tuple[bool, str, int | None]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await conn.fetchval("SELECT 1 FROM players WHERE telegram_id=$1", creator_id):
                return False, "Start the game in a private chat first using /start.", None
            existing = await conn.fetchval(
                "SELECT id FROM group_mining_wars WHERE chat_id=$1 AND status IN ('recruiting','fighting')",
                chat_id,
            )
            if existing:
                return False, f"This group already has active mining session #{existing}.", None
            war_id = await conn.fetchval(
                """INSERT INTO group_mining_wars(chat_id,creator_id,team_size)
                   VALUES($1,$2,5) RETURNING id""",
                chat_id, creator_id,
            )
    return True, f"Mining session #{war_id} is open. Players can join with the button.", war_id


async def join_team(chat_id: int, player_id: int, team: int = 1, war_id: int | None = None) -> tuple[bool, str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            war = await conn.fetchrow(
                """SELECT * FROM group_mining_wars
                   WHERE chat_id=$1 AND status='recruiting' AND ($2::BIGINT IS NULL OR id=$2)
                   ORDER BY id DESC LIMIT 1 FOR UPDATE""",
                chat_id, war_id,
            )
            if not war:
                return False, "There is no open mining session in this group."
            if not await conn.fetchval("SELECT 1 FROM players WHERE telegram_id=$1", player_id):
                return False, "Use /start with the bot in a private chat before joining."
            existing = await conn.fetchval(
                "SELECT 1 FROM mining_war_players WHERE war_id=$1 AND player_id=$2",
                war["id"], player_id,
            )
            if existing:
                return False, "You already joined this mining session."
            await conn.execute(
                "INSERT INTO mining_war_players(war_id,player_id,team) VALUES($1,$2,1)",
                war["id"], player_id,
            )
            count_after = await conn.fetchval(
                "SELECT COUNT(*) FROM mining_war_players WHERE war_id=$1", war["id"]
            )
    return True, f"You joined mining! Applicants: {count_after}. The strongest eligible miners are selected when mining starts."


async def war_snapshot(chat_id: int):
    async with get_pool().acquire() as conn:
        war = await conn.fetchrow(
            """SELECT * FROM group_mining_wars
               WHERE chat_id=$1 AND status IN ('recruiting','fighting')
               ORDER BY id DESC LIMIT 1""",
            chat_id,
        )
        if not war:
            return None, [], 0
        miners = await conn.fetch(
            """SELECT p.telegram_id,p.display_name,p.username,
                      p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth
               FROM mining_war_players mwp
               JOIN players p ON p.telegram_id=mwp.player_id
               LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id
               WHERE mwp.war_id=$1
               ORDER BY worth DESC,p.reputation DESC,p.telegram_id ASC""",
            war["id"],
        )
        return war, miners, sum(int(p["worth"]) for p in miners)


async def start_fight(chat_id: int, actor_id: int, war_id: int | None = None) -> tuple[bool, str, int | None, int | None]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            war = await conn.fetchrow(
                """SELECT * FROM group_mining_wars
                   WHERE chat_id=$1 AND status='recruiting' AND ($2::BIGINT IS NULL OR id=$2)
                   ORDER BY id DESC LIMIT 1 FOR UPDATE""",
                chat_id, war_id,
            )
            if not war:
                return False, "No open mining session to start.", None, None
            if actor_id != war["creator_id"]:
                return False, "Only the player who opened this mining session can start it.", None, None
            applicants = await conn.fetchval(
                "SELECT COUNT(*) FROM mining_war_players WHERE war_id=$1", war["id"]
            )
            if applicants < 3:
                return False, f"At least 3 players must join. Current applicants: {applicants}.", None, None
            selected_count = 5 if applicants >= 5 else 3
            selected = await conn.fetch(
                """WITH ranked AS (
                    SELECT p.telegram_id,p.display_name,p.reputation,
                           p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth,
                           ROW_NUMBER() OVER (
                             ORDER BY p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) DESC,
                                      p.reputation DESC,p.telegram_id ASC
                           ) AS rn
                    FROM mining_war_players mwp
                    JOIN players p ON p.telegram_id=mwp.player_id
                    LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id
                    WHERE mwp.war_id=$1
                )
                SELECT * FROM ranked WHERE rn <= $2 ORDER BY rn""",
                war["id"], selected_count,
            )
            total = sum(int(p["worth"]) for p in selected)
            names = "\n".join(
                f'{i}. {p["display_name"]} — 💎 {int(p["worth"]):,} NW'
                for i, p in enumerate(selected, 1)
            )
            await conn.execute(
                "UPDATE group_mining_wars SET status='finished',started_at=NOW(),finished_at=NOW() WHERE id=$1",
                war["id"],
            )
    return True, (
        f'Mining session #{war["id"]} completed!\n'
        f'Selected {selected_count} strongest miner(s) from {applicants} applicants.\n\n'
        f'{names}\n\nCombined selected net worth: {total:,}.'
    ), war["id"], None


async def cancel_war(chat_id: int, actor_id: int, war_id: int | None = None) -> tuple[bool, str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            war = await conn.fetchrow(
                """SELECT * FROM group_mining_wars
                   WHERE chat_id=$1 AND status='recruiting' AND ($2::BIGINT IS NULL OR id=$2)
                   ORDER BY id DESC LIMIT 1 FOR UPDATE""",
                chat_id, war_id,
            )
            if not war:
                return False, "No open mining session to cancel."
            if actor_id != war["creator_id"]:
                return False, "Only the creator can cancel this mining session."
            await conn.execute(
                "UPDATE group_mining_wars SET status='cancelled',finished_at=NOW() WHERE id=$1",
                war["id"],
            )
    return True, f'Mining session #{war["id"]} cancelled.'
