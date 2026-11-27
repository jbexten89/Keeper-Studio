"""School & other orders: prints that aren't on any envelope."""

import tempfile
import unittest
from pathlib import Path

from keeperstudio import extras as X
from keeperstudio import meridian as M
from keeperstudio import orders as O
from keeperstudio import reports as R
from keeperstudio.orderbook import OrderBook
from tests.test_orders import CAT, cart, order

TP = {"Varsity": "IMG_5373.jpg", "JV": "IMG_5390.jpg", "Peewee": ""}
SCHOOL = {"id": 1, "kind": "School", "customer": "Bryan High School", "paid_cents": 5000, "paid_method": "check",
          "items": [
              {"src": "teams", "size": "8x10", "product": "Professional Prints", "counts": {"Varsity": 1, "JV": 1, "Peewee": 1},
               "price_cents": 0},
              {"src": "team", "team": "Varsity", "size": "16x20", "product": "Standouts", "qty": 1, "price_cents": 8500},
              {"src": "photo", "image": "IMG_4412.jpg", "label": "Carter Smith", "size": "11x14",
               "product": "Professional Prints", "qty": 3, "price_cents": 2500},
          ]}
TEACHERS = {"id": 2, "kind": "Teachers", "items": [
    {"src": "teams", "size": "5x7", "product": "Professional Prints", "counts": {"Varsity": 2, "JV": 3}, "price_cents": 0}]}


class ExtrasTests(unittest.TestCase):
    def test_codes_follow_size_product_and_orientation(self):
        self.assertEqual(X.product_code("16x20", "Professional Prints", True), "R1616")
        self.assertEqual(X.product_code("16x20", "Standouts", True), "SO1-R1616-H")
        self.assertEqual(X.product_code("11x14", "Standouts", False), "SO1-R161-V")
        self.assertEqual(X.product_code("4x6", "Canvas", False), "")
        sizes = X.choices()["products"]
        self.assertIn("Standout", [p["name"] for p in sizes["16x20"]])
        self.assertEqual([p["name"] for p in sizes["4x6"]][0], "Print")

    def test_summary_counts_per_team_and_prices(self):
        s = X.summary(SCHOOL, TP)
        self.assertEqual(s["prints"], 3 + 1 + 3)
        self.assertEqual(s["sales_cents"], 8500 + 3 * 2500)
        self.assertEqual(s["due_cents"], 8500 + 7500 - 5000)
        lab = 3 * X.lab_each("R1680A") + X.lab_each("SO1-R1616-H") + 3 * X.lab_each("R1614")
        self.assertEqual(s["lab_cents"], lab)
        t = X.summary(TEACHERS, TP)
        self.assertEqual((t["prints"], t["sales_cents"], t["free"]), (5, 0, True))

    def test_lines_say_what_stops_a_print(self):
        ls = X.lines(SCHOOL, TP, crop_names={"8x10", "10x8", "20x16"})
        by = {(l["size"], l["label"]): l for l in ls}
        self.assertEqual(by[("8x10", "Varsity team")]["file"], "IMG_5373_10x8")
        self.assertEqual(by[("8x10", "Peewee team")]["why"], "no group photo picked")
        self.assertEqual(by[("16x20", "Varsity team")]["file"], "IMG_5373_20x16")
        self.assertEqual(by[("11x14", "Carter Smith")]["why"], "11x14 isn't set up in Crop")

    def test_portrait_16x20_uses_its_own_crop_or_the_8x10(self):
        o = {"id": 3, "kind": "School", "items": [{"src": "photo", "image": "IMG_4412.jpg", "label": "Carter", "size": "16x20",
                                                   "product": "Professional Prints", "qty": 1, "price_cents": 0}]}
        self.assertEqual(X.lines(o, TP, crop_names={"16x20", "8x10"})[0]["file"], "IMG_4412_16x20")
        self.assertEqual(X.lines(o, TP, crop_names={"8x10"})[0]["file"], "IMG_4412_8x10")

    def test_lab_plan_merges_with_families_and_labels_who(self):
        fam = [order("Avery", "Varsity", cart(("ac-8x10-team", 2)), id=9, image="IMG_1.jpg")]
        plan = O.lab_plan(fam, CAT, TP, [SCHOOL, TEACHERS])
        groups = {g["group"]: g for g in plan["groups"]}
        v = next(it for it in groups["8x10 Team"]["items"] if it["file"] == "IMG_5373_10x8")
        self.assertEqual(v["qty"], 3)  # Avery's two + one for the school
        self.assertIn("School: Bryan High School (Varsity team)", v["for"])
        self.assertEqual(groups["16x20 Standout"]["items"][0]["item"], "code:SO1-R1616-H")
        self.assertEqual(O.meridian_code(CAT, "code:SO1-R1616-H"), ("SO1-R1616-H", 1))
        self.assertEqual(groups["5x7 Team"]["qty"], 5)
        rows, left = M.plan_rows(plan, CAT, {"account_email": "a@b.c"}, "Test", lambda it: it["file"] + ".jpg")
        self.assertIn("SO1-R1616-H", [r["product_code"] for r in rows])
        self.assertTrue(any(l["why"] == "no group photo picked" for l in left))

    def test_store_rename_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            b = OrderBook(Path(d) / "o.sqlite3")
            sid = b.save_shoot({"name": "Fall"})["id"]
            e = b.save_extra(sid, {k: v for k, v in SCHOOL.items() if k != "id"})
            self.assertEqual(len(b.extras(sid)[0]["items"]), 3)
            b.rename_team(sid, "Varsity", "Varsity Boys")
            items = b.extras(sid)[0]["items"]
            self.assertIn("Varsity Boys", items[0]["counts"])
            self.assertEqual(items[1]["team"], "Varsity Boys")
            with self.assertRaises(ValueError):
                b.save_extra(sid, {"id": e["id"], "paid_method": "barter"})
            ex = [{**e, "summary": X.summary(e, TP), "who": X.who(e)}]
            secs = R.shoot_summary([], CAT, {"shipping_cents": 0}, ex)
            heads = [s["heading"] for s in secs]
            self.assertIn("School & other orders", heads)
            out = R.invoice_pdf(e, X.summary(e, TP), {"id": sid, "name": "Fall"}, Path(d) / "inv")
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))
            b.delete_extra(e["id"])
            self.assertEqual(b.extras(sid), [])
            b.close()


if __name__ == "__main__":
    unittest.main()
