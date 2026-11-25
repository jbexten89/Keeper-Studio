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
