import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "migrations/012_club_competition_npc_foundation.sql",
    ROOT / "migrations/013_competition_match_round_state.sql",
    ROOT / "migrations/014_competition_roster_updates.sql",
    ROOT / "migrations/015_allow_reused_npc_opponents.sql",
    ROOT / "migrations/016_club_hourly_schedule.sql",
    ROOT / "migrations/017_club_live_match_screen.sql",
    ROOT / "migrations/018_mining_live_match_screens.sql",
]


class CompetitionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE players (
                telegram_id INTEGER PRIMARY KEY,
                business_level INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE timed_mining_events (id INTEGER PRIMARY KEY);
            CREATE TABLE mining_team_war_opponents (
                war_id INTEGER NOT NULL,
                matchup_number INTEGER NOT NULL,
                opponent_team_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                deadline_at TIMESTAMP,
                PRIMARY KEY(war_id, matchup_number)
            );
        """)
        for migration in MIGRATIONS:
            self.db.executescript(migration.read_text(encoding="utf-8"))

        self.db.executemany(
            "INSERT INTO players(telegram_id,business_level,is_npc,npc_key) VALUES(?,?,?,?)",
            [
                (101, 12, 0, None),
                (102, 12, 0, None),
                (-1, 12, 1, "npc_01"),
                (-2, 12, 1, "npc_02"),
            ],
        )
        self.db.execute(
            """INSERT INTO club_competitions(business_level,status,opens_at,closes_at)
               VALUES(12,'joining',CURRENT_TIMESTAMP,datetime('now','+5 minutes'))"""
        )
        self.competition_id = self.db.execute(
            "SELECT id FROM club_competitions"
        ).fetchone()[0]

    def tearDown(self):
        self.db.close()

    def test_each_hourly_slot_can_have_a_new_competition(self):
        self.db.execute(
            """INSERT INTO club_competitions(business_level,status,opens_at,closes_at,schedule_key)
               VALUES(12,'joining',CURRENT_TIMESTAMP,datetime('now','+5 minutes'),'2026-10-30T10')"""
        )
        self.db.execute(
            """INSERT INTO club_competitions(business_level,status,opens_at,closes_at,schedule_key)
               VALUES(12,'joining',CURRENT_TIMESTAMP,datetime('now','+5 minutes'),'2026-10-30T11')"""
        )
        count = self.db.execute(
            "SELECT COUNT(*) FROM club_competitions WHERE business_level=12"
        ).fetchone()[0]
        self.assertEqual(count, 3)

    def test_mining_live_screen_columns_exist(self):
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(mining_team_war_opponents)")}
        self.assertIn("main_message_id", columns)
        self.assertIn("opponent_message_id", columns)
        self.assertIn("countdown_mark", columns)

    def test_live_match_screen_columns_exist(self):
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(club_competition_matches)")}
        self.assertIn("message_id", columns)
        self.assertIn("countdown_mark", columns)

    def test_each_human_can_get_two_distinct_npc_opponents(self):
        for human_id, opponents in ((101, (-1, -2)), (102, (-1, -2))):
            for match_number, opponent_id in enumerate(opponents, start=1):
                self.db.execute(
                    """INSERT INTO club_competition_matches
                       (competition_id,player_a,player_b,match_number,layout_a,layout_b,picked_b)
                       VALUES(?,?,?,?, '[]','[]',1)""",
                    (self.competition_id, human_id, opponent_id, match_number),
                )
        for human_id in (101, 102):
            rows = self.db.execute(
                """SELECT player_b FROM club_competition_matches
                   WHERE competition_id=? AND player_a=? ORDER BY match_number""",
                (self.competition_id, human_id),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0][0], rows[1][0])

    def test_npc_opponents_can_be_reused_for_many_humans(self):
        for human_id in (101, 102):
            self.db.execute(
                """INSERT INTO club_competition_matches
                   (competition_id,player_a,player_b,match_number,layout_a,layout_b,picked_b)
                   VALUES(?,?,?,1,'[]','[]',1)""",
                (self.competition_id, human_id, -1),
            )
        count = self.db.execute(
            "SELECT COUNT(*) FROM club_competition_matches WHERE player_b=-1 AND match_number=1"
        ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_match_slot_is_unique_per_human(self):
        values = (self.competition_id, 101, -1, 1)
        sql = """INSERT INTO club_competition_matches
                 (competition_id,player_a,player_b,match_number,layout_a,layout_b,picked_b)
                 VALUES(?,?,?,?,'[]','[]',1)"""
        self.db.execute(sql, values)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql, values)

    def test_reapplying_rebuild_migration_preserves_match_rows(self):
        self.db.execute(
            """INSERT INTO club_competition_matches
               (competition_id,player_a,player_b,match_number,layout_a,layout_b,picked_b)
               VALUES(?,101,-1,1,'[]','[]',1)""",
            (self.competition_id,),
        )
        self.db.executescript((ROOT / "migrations/015_allow_reused_npc_opponents.sql").read_text(encoding="utf-8"))
        count = self.db.execute("SELECT COUNT(*) FROM club_competition_matches").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
