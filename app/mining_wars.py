"""Group-scoped mining wars with net-worth-based team selection."""
from app.db import get_pool

async def create_war(chat_id: int, creator_id: int, team_size: int) -> tuple[bool, str, int | None]:
    if team_size not in (3, 5):
        return False, "Choose 3 or 5 players per team.", None
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await conn.fetchval("SELECT 1 FROM players WHERE telegram_id=$1", creator_id):
                return False, "Start the game in a private chat first using /start.", None
            existing = await conn.fetchval("SELECT id FROM group_mining_wars WHERE chat_id=$1 AND status IN ('recruiting','fighting') FOR UPDATE", chat_id)
            if existing:
                return False, f"This group already has active mining war #{existing}. Finish it before creating another.", None
            war_id = await conn.fetchval("""INSERT INTO group_mining_wars(chat_id,creator_id,team_size)
                VALUES($1,$2,$3) RETURNING id""", chat_id, creator_id, team_size)
    return True, f"Mining War #{war_id} is open. Recruit {team_size} players on each team.", war_id

async def join_team(chat_id: int, player_id: int, team: int) -> tuple[bool, str]:
    if team not in (1,2):
        return False, "Invalid team."
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            war = await conn.fetchrow("""SELECT * FROM group_mining_wars
                WHERE chat_id=$1 AND status='recruiting' ORDER BY id DESC LIMIT 1 FOR UPDATE""", chat_id)
            if not war:
                return False, "There is no open mining war in this group."
            player = await conn.fetchrow("SELECT telegram_id FROM players WHERE telegram_id=$1", player_id)
            if not player:
                return False, "Use /start with the bot in a private chat before joining."
            already = await conn.fetchval("SELECT team FROM mining_war_players WHERE war_id=$1 AND player_id=$2", war["id"], player_id)
            if already:
                return False, f"You already joined Team {already}."
            await conn.execute("INSERT INTO mining_war_players(war_id,player_id,team) VALUES($1,$2,$3)", war["id"], player_id, team)
            count_after = await conn.fetchval("SELECT COUNT(*) FROM mining_war_players WHERE war_id=$1 AND team=$2", war["id"], team)
    return True, f"You registered for Team {team} (applicant #{count_after}). The highest-net-worth {war['team_size']} applicants qualify when the fight starts."

async def war_snapshot(chat_id: int):
    async with get_pool().acquire() as conn:
        war = await conn.fetchrow("""SELECT * FROM group_mining_wars
            WHERE chat_id=$1 AND status IN ('recruiting','fighting') ORDER BY id DESC LIMIT 1""", chat_id)
        if not war:
            return None, [], [], 0, 0
        teams = await conn.fetch("""SELECT mwp.team,p.telegram_id,p.display_name,p.username,
              p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth
            FROM mining_war_players mwp JOIN players p ON p.telegram_id=mwp.player_id
            LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id
            WHERE mwp.war_id=$1 ORDER BY mwp.team,worth DESC,p.telegram_id""", war["id"])
        one=[r for r in teams if r["team"]==1][:war["team_size"]]
        two=[r for r in teams if r["team"]==2][:war["team_size"]]
        return war, one, two, sum(r["worth"] for r in one), sum(r["worth"] for r in two)

async def start_fight(chat_id: int, actor_id: int) -> tuple[bool, str, int | None, int | None]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            war=await conn.fetchrow("""SELECT * FROM group_mining_wars
                WHERE chat_id=$1 AND status='recruiting' ORDER BY id DESC LIMIT 1 FOR UPDATE""",chat_id)
            if not war:
                return False,"No open mining war to start.",None,None
            if actor_id != war["creator_id"]:
                return False,"Only the player who opened this war can start it.",None,None
            counts=await conn.fetch("SELECT team,COUNT(*) AS n FROM mining_war_players WHERE war_id=$1 GROUP BY team",war["id"])
            sizes={r["team"]:r["n"] for r in counts}
            if sizes.get(1,0)<war["team_size"] or sizes.get(2,0)<war["team_size"]:
                return False,f"Both teams need at least {war['team_size']} applicants. Current: Team 1 {sizes.get(1,0)}, Team 2 {sizes.get(2,0)}.",None,None
            scores=await conn.fetch("""WITH ranked AS (
                SELECT mwp.team,p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth,
                  ROW_NUMBER() OVER (PARTITION BY mwp.team ORDER BY p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) DESC,p.reputation DESC,p.telegram_id ASC) AS rn
                FROM mining_war_players mwp JOIN players p ON p.telegram_id=mwp.player_id
                LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id WHERE mwp.war_id=$1
            ) SELECT team,SUM(worth) AS score FROM ranked WHERE rn<=$2 GROUP BY team ORDER BY team""",war["id"],war["team_size"])
            s={r["team"]:int(r["score"]) for r in scores}
            # Tie-break: compare each team's highest individual net worth, then reputation total.
            if s[1]==s[2]:
                tops=await conn.fetch("""WITH ranked AS (
                    SELECT mwp.team,p.reputation,p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth,
                      ROW_NUMBER() OVER (PARTITION BY mwp.team ORDER BY p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) DESC,p.reputation DESC,p.telegram_id ASC) AS rn
                    FROM mining_war_players mwp JOIN players p ON p.telegram_id=mwp.player_id
                    LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id WHERE mwp.war_id=$1
                ) SELECT team,MAX(worth) AS top_worth,SUM(reputation) AS reputation FROM ranked WHERE rn<=$2 GROUP BY team ORDER BY team""",war["id"],war["team_size"])
                t={r["team"]:(int(r["top_worth"]),int(r["reputation"])) for r in tops}
                winner=1 if t[1]>t[2] else 2 if t[2]>t[1] else 0
            else:
                winner=1 if s[1]>s[2] else 2
            await conn.execute("UPDATE group_mining_wars SET status='finished',winner_team=$1,started_at=NOW(),finished_at=NOW() WHERE id=$2",winner if winner else None,war["id"])
    if winner==0:
        return True,f"Mining War #{war['id']} ended in a draw! Team 1: {s[1]:,} net worth · Team 2: {s[2]:,}.",war["id"],None
    return True,f"Team {winner} wins Mining War #{war['id']}!\n⛏ Team 1 power: {s[1]:,}\n⛏ Team 2 power: {s[2]:,}",war["id"],winner

async def cancel_war(chat_id: int, actor_id: int) -> tuple[bool,str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            war=await conn.fetchrow("""SELECT * FROM group_mining_wars WHERE chat_id=$1 AND status='recruiting'
                ORDER BY id DESC LIMIT 1 FOR UPDATE""",chat_id)
            if not war:
                return False,"No recruiting mining war to cancel."
            if actor_id!=war["creator_id"]:
                return False,"Only the war creator can cancel it."
            await conn.execute("UPDATE group_mining_wars SET status='cancelled',finished_at=NOW() WHERE id=$1",war["id"])
    return True,f"Mining War #{war['id']} cancelled."
