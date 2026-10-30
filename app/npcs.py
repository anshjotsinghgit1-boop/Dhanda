"""Persistent non-Telegram game characters used by Empire Century."""
from app.db import get_pool

NPC_NAMES = (
    "Aarav Mehta", "Kabir Malhotra", "Reyansh Kapoor", "Vihaan Khanna", "Aditya Rao",
    "Arjun Bedi", "Ishaan Sethi", "Rudra Chauhan", "Devansh Shah", "Ayaan Gill",
    "Myra Kapoor", "Anaya Mehra", "Aadhya Singh", "Kiara Bansal", "Saanvi Rao",
    "Pari Khurana", "Ira Malhotra", "Navya Arora", "Zara Khan", "Tara Sethi",
    "Vivaan Joshi", "Shaurya Nair", "Dhruv Anand", "Atharv Jain", "Kian Verma",
    "Yuvaan Das", "Samarth Roy", "Neil Khanna", "Rohan Oberoi", "Aryan Gill",
    "Avni Mehta", "Riya Sood", "Aarohi Shah", "Ishita Bedi", "Meher Kaur",
    "Diya Nair", "Aisha Arora", "Prisha Jain", "Naira Kapoor", "Anvi Rao",
    "Krish Malhotra", "Laksh Bansal", "Parth Sethi", "Ranveer Das", "Yash Oberoi",
    "Misha Khanna", "Shanaya Gill", "Amaira Verma", "Vanya Roy", "Aditi Anand",
)
NPC_ID_BASE = -9_100_000

async def seed_npcs() -> int:
    """Idempotently seed 50 NPC rows; these IDs are never Telegram accounts."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            season_id = await conn.fetchval("SELECT id FROM seasons WHERE settled_at IS NULL ORDER BY id DESC LIMIT 1") or 1
            for index, name in enumerate(NPC_NAMES, start=1):
                await conn.execute("""INSERT INTO players
                    (telegram_id,username,display_name,season_id,is_npc,npc_key,business_level)
                    VALUES ($1,NULL,$2,$3,TRUE,$4,12)
                    ON CONFLICT (telegram_id) DO UPDATE SET
                    is_npc=TRUE,npc_key=EXCLUDED.npc_key,display_name=EXCLUDED.display_name""",
                    NPC_ID_BASE-index, "🤖 NPC · "+name, season_id, f"empire_npc_{index:02d}")
    return len(NPC_NAMES)
import random
from datetime import datetime, timezone
from app.economy import requires_club_competition, upgrade_cost, production_per_second

_last_tick = 0.0
_last_competition_attempt = {}

async def advance_npcs() -> int:
    """Accrue NPC income and simulate their level-gate competitions."""
    global _last_tick
    now = datetime.now(timezone.utc)
    stamp = now.timestamp()
    if stamp - _last_tick < 30:
        return 0
    _last_tick = stamp
    changed = 0
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT telegram_id,npc_key,cash,business_level,last_collected_at,club_completed_level FROM players WHERE is_npc=TRUE")
        for npc in rows:
            level = int(npc["business_level"])
            last = npc["last_collected_at"]
            if last is None:
                elapsed = 0
            else:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                elapsed = max(0, min(int((now-last).total_seconds()), 8*60*60))
            cash = int(npc["cash"] or 0) + elapsed * production_per_second(level)
            completed = int(npc["club_completed_level"] or 0)
            if requires_club_competition(level) and completed != level:
                pid = int(npc["telegram_id"])
                last_attempt = _last_competition_attempt.get(pid, 0)
                if stamp - last_attempt >= 3600:
                    _last_competition_attempt[pid] = stamp
                    if random.random() < 0.72:
                        completed = level
            while level < 54 and cash >= upgrade_cost(level):
                if requires_club_competition(level) and completed != level:
                    break
                cash -= upgrade_cost(level)
                level += 1
                changed += 1
            await conn.execute("UPDATE players SET cash=$1,business_level=$2,club_completed_level=$3,last_collected_at=$4 WHERE telegram_id=$5 AND is_npc=TRUE", cash, level, completed, now, npc["telegram_id"])
    return changed
