import asyncio
import os
import tempfile
import unittest
from pathlib import Path

TEST_DB = str(Path(tempfile.gettempdir()) / "dhanda_competition_ci.sqlite3")
os.environ.setdefault("BOT_TOKEN", "ci-placeholder")
os.environ["DATABASE_PATH"] = TEST_DB

from app.db import connect, close, get_pool
from app.npcs import seed_npcs
from app.economy import requires_club_competition


class DatabaseStartupTests(unittest.TestCase):
    def test_alternating_competition_gate(self):
        self.assertEqual([level for level in range(12, 54) if requires_club_competition(level)], list(range(12, 54, 2)))
        self.assertFalse(requires_club_competition(13))
        self.assertFalse(requires_club_competition(53))
        self.assertFalse(requires_club_competition(54))

    def test_full_sqlite_startup_and_npc_seed(self):
        async def run():
            await connect()
            try:
                seeded = await seed_npcs()
                seeded_again = await seed_npcs()
                self.assertEqual(seeded, 50)
                self.assertEqual(seeded_again, 50)
                async with get_pool().acquire() as conn:
                    count = await conn.fetchval("SELECT COUNT(*) FROM players WHERE is_npc=TRUE")
                    level_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM players WHERE is_npc=TRUE AND business_level=12"
                    )
                    applied_before = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
                self.assertEqual(count, 50)
                self.assertEqual(level_count, 50)
                await close()
                await connect()
                async with get_pool().acquire() as conn:
                    applied_after = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
                    count_after_restart = await conn.fetchval("SELECT COUNT(*) FROM players WHERE is_npc=TRUE")
                self.assertEqual(applied_after, applied_before)
                self.assertEqual(count_after_restart, 50)
            finally:
                await close()
                Path(TEST_DB).unlink(missing_ok=True)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
