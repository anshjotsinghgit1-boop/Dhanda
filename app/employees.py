"""Employee recruiting through consent-based challenges."""
from app.db import get_pool

async def send_challenge(boss_id: int, employee_id: int) -> tuple[bool, str]:
    if boss_id == employee_id:
        return False, "You cannot hire yourself."
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            boss = await conn.fetchrow("SELECT business_level,vip_level FROM players WHERE telegram_id=$1 FOR UPDATE", boss_id)
            target = await conn.fetchrow("SELECT telegram_id FROM players WHERE telegram_id=$1", employee_id)
            if not boss or not target:
                return False, "Both players must have started the game with /start."
            if boss["business_level"] < 7:
                return False, "Board of Directors unlocks at business level 7."
            slots = 3 + (2 if boss["vip_level"] >= 5 else 0)
            count = await conn.fetchval("SELECT COUNT(*) FROM employees WHERE boss_id=$1", boss_id)
            if count >= slots:
                return False, f"You have used all {slots} employee slots."
            if await conn.fetchval("SELECT 1 FROM employees WHERE employee_id=$1", employee_id):
                return False, "That player already works for another boss."
            challenge_id = await conn.fetchval("""INSERT INTO employee_challenges(boss_id,employee_id)
                VALUES($1,$2) RETURNING id""", boss_id, employee_id)
    return True, f"Recruitment challenge #{challenge_id} sent. The player must accept with /hireaccept {challenge_id}."

async def accept_challenge(employee_id: int, challenge_id: int) -> tuple[bool, str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            challenge = await conn.fetchrow("""SELECT * FROM employee_challenges
                WHERE id=$1 AND employee_id=$2 AND status='pending' AND expires_at>NOW() FOR UPDATE""",
                challenge_id, employee_id)
            if not challenge:
                return False, "No active recruitment challenge found for you."
            boss = await conn.fetchrow("SELECT business_level,vip_level FROM players WHERE telegram_id=$1 FOR UPDATE", challenge["boss_id"])
            slots = 3 + (2 if boss and boss["vip_level"] >= 5 else 0)
            count = await conn.fetchval("SELECT COUNT(*) FROM employees WHERE boss_id=$1", challenge["boss_id"])
            if not boss or boss["business_level"] < 7 or count >= slots:
                await conn.execute("UPDATE employee_challenges SET status='expired',resolved_at=NOW() WHERE id=$1", challenge_id)
                return False, "The boss no longer has an available employee slot."
            if await conn.fetchval("SELECT 1 FROM employees WHERE employee_id=$1", employee_id):
                return False, "You already have a boss."
            await conn.execute("INSERT INTO employees(employee_id,boss_id) VALUES($1,$2)", employee_id, challenge["boss_id"])
            await conn.execute("UPDATE employee_challenges SET status='accepted',resolved_at=NOW() WHERE id=$1", challenge_id)
    return True, "Recruitment accepted! 5% of your eligible collected income will be paid to your boss."
