"""Simple persistent stock market; player.stocks stores current marked-to-market value."""
from app.db import get_pool

async def quotes():
    async with get_pool().acquire() as conn:
        return await conn.fetch("SELECT * FROM stock_market ORDER BY symbol")

async def holdings(player_id: int):
    async with get_pool().acquire() as conn:
        return await conn.fetch("""SELECT h.symbol,m.company_name,h.shares,m.price,h.shares*m.price AS value
            FROM player_stock_holdings h JOIN stock_market m ON m.symbol=h.symbol
            WHERE h.player_id=$1 AND h.shares>0 ORDER BY value DESC""", player_id)

async def trade(player_id: int, symbol: str, shares: int, side: str) -> tuple[bool,str]:
    symbol=symbol.upper().strip()
    if shares < 1 or shares > 100000:
        return False,"Shares must be between 1 and 100,000."
    if side not in ("buy","sell"):
        return False,"Trade must be buy or sell."
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            market=await conn.fetchrow("SELECT * FROM stock_market WHERE symbol=$1 FOR UPDATE",symbol)
            p=await conn.fetchrow("SELECT cash FROM players WHERE telegram_id=$1 FOR UPDATE",player_id)
            if not market or not p:
                return False,"Unknown stock symbol or player. Use /stocks."
            price=market["price"]; total=price*shares
            current=await conn.fetchval("SELECT shares FROM player_stock_holdings WHERE player_id=$1 AND symbol=$2 FOR UPDATE",player_id,symbol) or 0
            if side=="buy":
                if p["cash"]<total:
                    return False,f"You need {total:,} cash."
                await conn.execute("UPDATE players SET cash=cash-$1,stocks=stocks+$1 WHERE telegram_id=$2",total,player_id)
                await conn.execute("""INSERT INTO player_stock_holdings(player_id,symbol,shares) VALUES($1,$2,$3)
                    ON CONFLICT(player_id,symbol) DO UPDATE SET shares=player_stock_holdings.shares+EXCLUDED.shares""",player_id,symbol,shares)
            else:
                if current<shares:
                    return False,f"You only own {current} shares of {symbol}."
                await conn.execute("UPDATE players SET cash=cash+$1,stocks=GREATEST(0,stocks-$1) WHERE telegram_id=$2",total,player_id)
                await conn.execute("UPDATE player_stock_holdings SET shares=shares-$1 WHERE player_id=$2 AND symbol=$3",shares,player_id,symbol)
            await conn.execute("INSERT INTO stock_transactions(player_id,symbol,shares,price_each) VALUES($1,$2,$3,$4)",player_id,symbol,shares if side=="buy" else -shares,price)
    return True,f"{side.title()} order complete: {shares} {symbol} share(s) at {price:,} each; total {total:,} cash."
