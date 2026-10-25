"""Business-war scoring and safe transaction-based battle resolution."""
from app.db import get_pool

async def net_worth(player_id: int) -> int:
    async with get_pool().acquire() as conn:
        p = await conn.fetchrow("SELECT cash,stocks,gold_grams,reputation FROM players WHERE telegram_id=$1", player_id)
        if not p:
            return 0
        assets = await conn.fetchval("SELECT COALESCE(asset_value,0) FROM player_asset_valuation WHERE player_id=$1", player_id) or 0
        return int(p["cash"] + p["stocks"] + p["gold_grams"] * 10 + assets)

async def attack(attacker_id: int, defender_id: int) -> tuple[bool, str]:
    if attacker_id == defender_id:
        return False, "You cannot attack yourself."
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            attacker = await conn.fetchrow("SELECT * FROM players WHERE telegram_id=$1 FOR UPDATE", attacker_id)
            defender = await conn.fetchrow("SELECT * FROM players WHERE telegram_id=$1 FOR UPDATE", defender_id)
            if not attacker or not defender:
                return False, "Both players must have started the game."
            if attacker["frozen"] or defender["frozen"]:
                return False, "A player is frozen and cannot enter a business war."
            a_assets = await conn.fetchval("SELECT COALESCE(asset_value,0) FROM player_asset_valuation WHERE player_id=$1", attacker_id) or 0
            d_assets = await conn.fetchval("SELECT COALESCE(asset_value,0) FROM player_asset_valuation WHERE player_id=$1", defender_id) or 0
            a_score = int(attacker["cash"] + attacker["stocks"] + attacker["gold_grams"]*10 + a_assets + attacker["determination"])
            d_score = int(defender["cash"] + defender["stocks"] + defender["gold_grams"]*10 + d_assets + defender["determination"])
            winner = attacker_id if a_score > d_score else defender_id if d_score > a_score else None
            # Tie-break order: assets, stocks, cash.
            if winner is None:
                a_tie = (int(a_assets), attacker["stocks"], attacker["cash"])
                d_tie = (int(d_assets), defender["stocks"], defender["cash"])
                winner = attacker_id if a_tie > d_tie else defender_id if d_tie > a_tie else None
            won = winner == attacker_id
            # Defender can lose only a bounded share; attacker receives determination based on result.
            gold_delta = 0
            if won:
                gold_delta = 1
                await conn.execute("UPDATE players SET gold_grams=gold_grams+1,determination=LEAST(2000,determination+200) WHERE telegram_id=$1", attacker_id)
                await conn.execute("UPDATE players SET gold_grams=GREATEST(0,gold_grams-1),determination=LEAST(2000,determination+100) WHERE telegram_id=$1", defender_id)
            else:
                await conn.execute("UPDATE players SET determination=LEAST(2000,determination+100) WHERE telegram_id=$1", attacker_id)
                # Defender wins without a gold bonus or determination change.
            await conn.execute("""INSERT INTO business_wars(attacker_id,defender_id,winner_id,attacker_score,defender_score,gold_delta)
                VALUES($1,$2,$3,$4,$5,$6)""", attacker_id, defender_id, winner, a_score, d_score, gold_delta)
    if winner is None:
        return True, f"Business war ended in a tie. Scores: {a_score:,} vs {d_score:,}."
    if won:
        return True, f"You won the business war! +1 g Gold and +200 determination. Scores: {a_score:,} vs {d_score:,}."
    return True, f"You lost the business war. Determination increased by 100. Scores: {a_score:,} vs {d_score:,}."
