import tempfile
import unittest
from pathlib import Path

from keeperstudio.orderbook import OrderBook


class TeamListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = OrderBook(Path(self.tmp.name) / "a.sqlite3")
        last = self.book.save_shoot({"name": "Winter Sports 2025", "date": "2025-12-06"})["id"]
        for env, team, coach in [("1", "HS Varsity Boys", "Smith"), ("2", "HS Varsity Boys", "Smith"),
                                 ("3", "7th Grade Girls", "Jones"), ("4", "HS Wrestling", "")]:
            self.book.save_order(last, {"envelope": env, "athlete": "", "team": team, "coach": coach, "lines": []})
        self.book.set_team_order(last, ["7th Grade Girls", "HS Varsity Boys", "HS Wrestling"])
        self.book.save_shoot({"name": "Fall Sports 2026", "date": "2026-09-10"})
        self.sid = self.book.save_shoot({"name": "Winter Sports 2026", "date": "2026-12-05"})["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_shoot_starts_with_last_years_teams_and_coaches(self):
        tl = self.book.team_list(self.sid)
        self.assertEqual([t["name"] for t in tl], ["7th Grade Girls", "HS Varsity Boys", "HS Wrestling"])
        self.assertEqual(tl[1]["coach"], "Smith")
        self.assertFalse(any(t["live"] for t in tl))
        self.assertEqual(self.book.team_order(self.sid), [])  # nothing in use yet

    def test_typed_team_is_added_and_used_team_goes_live(self):
        self.book.save_order(self.sid, {"envelope": "1", "athlete": "", "team": "HS Wrestling", "lines": []})
        self.book.plan_team(self.sid, "HS 9th Boys Basketball", "Lee")
        tl = {t["name"]: t for t in self.book.team_list(self.sid)}
        self.assertTrue(tl["HS Wrestling"]["live"])
        self.assertEqual(tl["HS 9th Boys Basketball"]["coach"], "Lee")

    def test_drop_a_team_for_the_year_only_when_unused(self):
        self.book.save_order(self.sid, {"envelope": "1", "athlete": "", "team": "HS Wrestling", "lines": []})
        self.book.drop_team(self.sid, "7th Grade Girls")
        self.assertNotIn("7th Grade Girls", [t["name"] for t in self.book.team_list(self.sid)])
        with self.assertRaises(ValueError):
            self.book.drop_team(self.sid, "HS Wrestling")

    def test_rename_follows_into_the_list(self):
        self.book.team_list(self.sid)
        self.book.rename_team(self.sid, "HS Wrestling", "HS Boys Wrestling")
        self.assertIn("HS Boys Wrestling", [t["name"] for t in self.book.team_list(self.sid)])

    def test_team_list_window_saves_order_coaches_renames(self):
        self.book.save_order(self.sid, {"envelope": "1", "athlete": "", "team": "HS Wrestling", "lines": []})
        self.book.save_team_list(self.sid, [
            {"name": "HS Boys Wrestling", "coach": "Kim", "was": "HS Wrestling"},
            {"name": "HS Varsity Boys", "coach": "Smith", "was": "HS Varsity Boys"},
            {"name": "HS 9th Boys Basketball", "coach": "Lee", "was": ""},
            {"name": "", "coach": "", "was": ""}])
        tl = self.book.team_list(self.sid)
        self.assertEqual([t["name"] for t in tl], ["HS Boys Wrestling", "HS Varsity Boys", "HS 9th Boys Basketball"])
        self.assertEqual(tl[0]["coach"], "Kim")
        self.assertEqual(self.book.orders(self.sid)[0]["team"], "HS Boys Wrestling")
        with self.assertRaises(ValueError):  # a team in use can't be left out
            self.book.save_team_list(self.sid, [{"name": "HS Varsity Boys", "coach": "", "was": "HS Varsity Boys"}])
        with self.assertRaises(ValueError):
            self.book.save_team_list(self.sid, [{"name": "A", "was": ""}, {"name": "a", "was": ""}])
        self.assertEqual(self.book.next_shoot_name(self.sid), "Winter Sports 2027")

    def test_league_ignores_the_year(self):
        self.assertEqual(OrderBook.league("Winter Sports 2026"), OrderBook.league("Winter Sports 2025"))


if __name__ == "__main__":
    unittest.main()
