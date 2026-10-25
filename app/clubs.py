"""Club management and registration-window rules."""
from app.db import get_pool

async def create_club(player_id: int, name: str, tag: str) -> tuple[bool, str]:
    name, tag = name.strip()[:40], tag.strip().upper()[:8]
    if len(name) < 3 or not tag.isalnum() or len(tag) < 2:
        return False, "Use a club name of 3–40 characters and an alphanumeric tag of 2–8 characters."
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval("SELECT 1 FROM club_members WHERE player_id=$1", player_id)
            if existing:
                return False, "Leave your current club before creating another."
            try:
                club_id = await conn.fetchval("INSERT INTO clubs(name,tag,owner_id) VALUES($1,$2,$3) RETURNING id", name, tag, player_id)
            except Exception as exc:
                if "unique" in str(exc).lower():
                    return False, "That club name or tag is already taken."
                raise
            await conn.execute("INSERT INTO club_members(club_id,player_id,role) VALUES($1,$2,'owner')", club_id, player_id)
    return True, f"Club {name} [{tag}] created."

async def join_club(player_id: int, tag: str) -> tuple[bool, str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if await conn.fetchval("SELECT 1 FROM club_members WHERE player_id=$1", player_id):
                return False, "You are already in a club."
            club = await conn.fetchrow("SELECT id,name FROM clubs WHERE UPPER(tag)=UPPER($1)", tag.strip())
            if not club:
                return False, "No club found with that tag."
            await conn.execute("INSERT INTO club_members(club_id,player_id) VALUES($1,$2)", club["id"], player_id)
    return True, f"You joined {club['name']}."

async def my_club(player_id: int):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow("""SELECT c.*,cm.role,
            (SELECT COUNT(*) FROM club_members x WHERE x.club_id=c.id) AS members
            FROM club_members cm JOIN clubs c ON c.id=cm.club_id WHERE cm.player_id=$1""", player_id)

async def donate_to_club(player_id: int, amount: int) -> tuple[bool, str]:
    if amount <= 0:
        return False, "Donation must be positive."
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            p = await conn.fetchrow("SELECT cash FROM players WHERE telegram_id=$1 FOR UPDATE", player_id)
            club = await conn.fetchrow("SELECT c.id FROM clubs c JOIN club_members m ON m.club_id=c.id WHERE m.player_id=$1", player_id)
            if not p or not club:
                return False, "Join a club first."
            if p["cash"] < amount:
                return False, "Not enough cash."
            await conn.execute("UPDATE players SET cash=cash-$1 WHERE telegram_id=$2", amount, player_id)
            await conn.execute("UPDATE clubs SET treasury=treasury+$1 WHERE id=$2", amount, club["id"])
    return True, f"Donated {amount:,} cash to your club treasury."

async def registration_status():
    async with get_pool().acquire() as conn:
        return await conn.fetchrow("""SELECT * FROM club_registration
            WHERE NOW() >= opens_at AND NOW() < closes_at AND status='open'
            ORDER BY opens_at DESC LIMIT 1""")
