"""Formatted pull sheet / crop list / orders: the preview table and the PDF."""

import tempfile
import unittest
from pathlib import Path

from keeperstudio import orders as O
from keeperstudio import reports as R
from tests.test_orders import CAT, cart, order


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.orders = [order("Carter", lines=cart(("pkg-f", 1)), image="IMG_5371", team="9th Grade"),
                       order("Riley", lines=cart(("pkg-g", 1)), image="IMG_5369", team="9th Grade", id=2),
                       order("Sam", lines=cart(("misc-magnet-5x7", 1)), image="IMG_5375", team="JV", id=3)]

    def test_pull_sheet_hides_empty_columns_and_groups_by_team(self):
        t = R.table(O.pull_sheet_csv(self.orders, CAT), "pull")
        self.assertIn("5x7", t["head"])
        self.assertNotIn("8x10", t["head"])        # nobody bought one
        self.assertNotIn("Phone", t["head"])       # never filled in
        kinds = [r["kind"] for r in t["rows"]]
        self.assertEqual(kinds, ["group", "row", "row", "group", "row", "total"])
        self.assertTrue(t["rows"][0]["label"].startswith("9th Grade"))
        self.assertEqual(t["align"][t["head"].index("Total")], "money")
        self.assertEqual(len(t["rows"][1]["cells"]), len(t["head"]))

    def test_shoot_summary(self):
        decorated = []
        for o in self.orders:
            s = O.order_summary(o, CAT)
            s["lab_cents"] = 100  # a stand-in lab estimate per envelope
            decorated.append({**o, "summary": s})
        decorated[0]["paid_method"], decorated[0]["paid_cents"] = "cash", decorated[0]["summary"]["total_cents"]
        decorated[0]["summary"] = O.order_summary(decorated[0], CAT) | {"lab_cents": 100}
        secs = {s["heading"]: s for s in R.shoot_summary(decorated, CAT, {"shipping_cents": 500})}
        totals = {r["cells"][0]: r["cells"][1] for r in secs["Totals"]["rows"]}
        sales = sum(o["summary"]["total_cents"] for o in decorated)
        self.assertEqual(totals["Sales"], O.money(sales))
        self.assertEqual(totals["You keep"], O.money(sales - 300 - 500))
        teams = [r["cells"][0] for r in secs["By team (profit before shipping)"]["rows"]]
        self.assertEqual(teams, ["9th Grade", "JV", "TOTAL"])
        sold = {r["cells"][0]: r["cells"][2] for r in secs["What sold"]["rows"]}
        self.assertEqual((sold["Package F"], sold["Package G"]), ("1", "1"))
        self.assertIn("Still owed", secs)  # Riley and Sam haven't paid
        self.assertEqual(len([r for r in secs["Still owed"]["rows"] if r["kind"] == "row"]), 2)
        with tempfile.TemporaryDirectory() as d:
            out = R.pdf_sections(list(secs.values()), Path(d, "summary"), "Shoot summary", "Test")
            self.assertEqual(out.read_bytes()[:5], b"%PDF-")

    def test_every_export_makes_a_pdf(self):
        exports = {"pull": O.pull_sheet_csv(self.orders, CAT), "crop": O.crop_list_csv(self.orders, CAT, {}),
                   "items": O.line_items_csv(self.orders, CAT), "roes": O.roes_csv(self.orders, CAT, {})}
        with tempfile.TemporaryDirectory() as d:
            for kind, text in exports.items():
                out = R.pdf(R.table(text, kind), Path(d, f"{kind}.csv"), R.TITLES[kind], "Test shoot")
                self.assertEqual(out.suffix, ".pdf")
                self.assertEqual(out.read_bytes()[:5], b"%PDF-", kind)


if __name__ == "__main__":
    unittest.main()
