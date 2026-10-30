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
