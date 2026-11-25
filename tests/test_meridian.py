"""The Meridian bulk order CSV, checked with Meridian's own validate_order.py."""

import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from keeperstudio import meridian as M
from keeperstudio import orders as O
from tests.test_orders import CAT, cart, order

SETTINGS = {"account_email": "studio@example.com", "delivery": "ship"}
# Crop's export sizes, at 300 pixels per inch.
SHAPES = {"5x7": (1500, 2100), "4x6": (1200, 1800), "8x10": (2400, 3000), "2_5x3_5": (750, 1050),
          "7x5": (2100, 1500), "10x8": (3000, 2400), "4x5": (1200, 1500), "1_7x2_2": (510, 660)}


def crops(folder: Path, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        Image.new("RGB", SHAPES[n.split("_", 2)[2]]).save(folder / f"{n}.JPG")


def plan(*orders, teams=None):
    return O.lab_plan(list(orders), CAT, teams or {})


class MeridianTests(unittest.TestCase):
    def test_every_default_code_is_a_bulk_upload_product(self):
        for key, it in O.DEFAULT_MERIDIAN_ITEMS.items():
            code, _ = O.meridian_code(CAT, key)
            if code:
                self.assertTrue(M.products()[code]["how_to_order"].startswith("Bulk upload"), key)

    def test_rows_for_carter(self):
        p = plan(order("Carter", lines=cart(("pkg-f", 1)), image="IMG_5371"))
        rows, left = M.plan_rows(p, CAT, SETTINGS, "Winter Sports", lambda it: f"x/{it['file']}.JPG")
        got = {(r["product_code"], r["quantity"], r["finish"], r["crop"]) for r in rows}
        self.assertEqual(got, {("RA1657", "1", "Matte", "exact"), ("R1646", "2", "Matte", "exact")})
        self.assertEqual(left, [])
        self.assertEqual({r["item_id"] for r in rows}, {"1", "2"})

    def test_wallet_sheet_is_two_4_wallets_and_team_uses_its_size(self):
        p = plan(*[order(f"K{i}", lines=cart(("pkg-g", 1), ("ac-wallets-8", 1)), image=f"IMG_{i}", id=i) for i in range(3)],
                 teams={"U10": "IMG_9000"})
        rows, _ = M.plan_rows(p, CAT, SETTINGS, "W", lambda it: f"x/{it['file']}.JPG")
        by = {r["file_name"]: r for r in rows}
        self.assertEqual((by["x/IMG_0_2_5x3_5.JPG"]["product_code"], by["x/IMG_0_2_5x3_5.JPG"]["quantity"]), ("R623dc", "2"))
        self.assertEqual((by["x/IMG_9000_7x5.JPG"]["product_code"], by["x/IMG_9000_7x5.JPG"]["quantity"]), ("RA1657", "3"))

    def test_keepsakes_without_a_code_are_left_out(self):
        p = plan(order(lines=cart(("misc-magnet-4x5", 2), ("misc-mini-wallets-8", 1)), image="IMG_1"))
        rows, left = M.plan_rows(p, CAT, SETTINGS, "W", lambda it: f"x/{it['file']}.JPG")
        self.assertEqual([(r["product_code"], r["quantity"], r["finish"]) for r in rows], [("MAG45", "2", "")])
        self.assertEqual([(l["file"], "no Meridian product code" in l["why"]) for l in left], [("IMG_1_1_7x2_2", True)])

    def test_build_passes_meridians_checker(self):
        with tempfile.TemporaryDirectory() as d:
            crops(Path(d, "crops", "Orders"), "IMG_5371_5x7", "IMG_5371_4x6", "IMG_5371_2_5x3_5", "IMG_5371_4x5",
                  "IMG_9000_7x5", "IMG_9000_10x8")
            p = plan(order("Carter", lines=cart(("pkg-a", 1), ("misc-magnet-4x5", 1)), image="IMG_5371"),
                     order("Riley", lines=cart(("pkg-f", 1)), id=2), teams={"U10": "IMG_9000"})
            res = M.build(p, CAT, Path(d, "crops"), Path(d, "out"), SETTINGS, "Winter Sports")
            self.assertTrue(res["ok"], res["report"])
            self.assertEqual(res["errors"], [])
            with open(res["csv"], encoding="utf-8") as f:
                got = list(csv.DictReader(f))
            self.assertEqual(list(got[0].keys()), M.COLUMNS)
            for r in got:
                self.assertTrue(Path(d, "out", r["file_name"]).is_file(), r["file_name"])
            self.assertEqual(Path(res["csv"]).name, "Winter Sports-meridian-order.csv")
            self.assertTrue(any("no photo" in l["why"] for l in res["left_out"]))  # Riley has no photo

    def test_checker_catches_a_wrong_shape(self):
        with tempfile.TemporaryDirectory() as d:
            crops(Path(d, "crops"), "IMG_1_5x7")
            Image.new("RGB", (1200, 1800)).save(Path(d, "crops", "IMG_1_5x7.JPG"))  # a 4x6 named 5x7
            res = M.build(plan(order(lines=cart(("ac-5x7", 1)), image="IMG_1")), CAT, Path(d, "crops"), Path(d, "out"),
                          SETTINGS, "T")
            self.assertFalse(res["ok"])
            self.assertTrue(any("exact" in e for e in res["errors"]))

    def test_settings_need_an_email(self):
        self.assertTrue(M.settings_problems({"delivery": "ship"}))
        self.assertEqual(M.settings_problems(SETTINGS), [])


if __name__ == "__main__":
    unittest.main()
