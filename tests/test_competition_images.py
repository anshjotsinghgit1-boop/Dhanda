import asyncio
import unittest
from io import BytesIO

from PIL import Image

from app.competition_images import (
    render_competition_result,
    render_forbes_leaderboard,
    render_roster,
)


class FakeBot:
    pass


class CompetitionImageTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "telegram_id": -index,
                "display_name": f"NPC · Test Character {index}",
                "is_npc": True,
                "worth": 100000 - index * 1000,
            }
            for index in range(1, 11)
        ]

    def _assert_png(self, payload):
        image = Image.open(BytesIO(payload))
        self.assertEqual(image.format, "PNG")
        self.assertGreater(image.width, 500)
        self.assertGreater(image.height, 300)

    def test_forbes_leaderboard_renders(self):
        payload = asyncio.run(render_forbes_leaderboard(FakeBot(), self.rows, 50))
        self._assert_png(payload)

    def test_roster_card_renders_with_npc_avatars(self):
        payload = asyncio.run(render_roster(FakeBot(), 12, self.rows))
        self._assert_png(payload)

    def test_final_result_card_renders(self):
        matches = [
            {"opponent_name": "NPC Alpha", "wins_a": 2, "wins_b": 1, "won": True},
            {"opponent_name": "NPC Beta", "wins_a": 0, "wins_b": 2, "won": False},
        ]
        payload = asyncio.run(render_competition_result(FakeBot(), 12, "Test Player", matches, False))
        self._assert_png(payload)


if __name__ == "__main__":
    unittest.main()
