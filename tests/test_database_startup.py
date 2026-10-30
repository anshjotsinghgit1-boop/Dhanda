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


class DatabaseStartupTests(unittest.TestCase):
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
                self.assertEqual(count, 50)
                self.assertEqual(level_count, 50)
            finally:
                await close()
                Path(TEST_DB).unlink(missing_ok=True)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
