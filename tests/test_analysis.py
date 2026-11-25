"""Sales analysis: what sold, lab cost per item, teams vs the shoot."""

import unittest

from keeperstudio import analysis as A
from keeperstudio import meridian as M
from keeperstudio import orders as O
from tests.test_orders import CAT, cart, order


def deco(o, paid=0, method=""):
    o = {**o, "paid_cents": paid, "paid_method": method}
    s = O.order_summary(o, CAT)
    c = M.order_cost_cents(o, CAT)
    s.update(lab_cents=c["cents"], lab_unpriced=c["unpriced"], keep_cents=s["total_cents"] - c["cents"])
    o["summary"] = s
    return o


ORDERS = [
    deco(order("Avery", "U10", cart(("pkg-a", 1), ("ac-5x7", 2)), id=1), 5600, "cash"),
    deco(order("Blake", "U10", cart(("pkg-f", 1), ("misc-photo-badge", 1)), id=2), 0),
    deco(order("Casey", "U12", cart(("ac-8x10", 1)), id=3), 1500, "card"),
    deco(order("Drew", "U12", (), id=4)),  # envelope with nothing bought
]
LAB = A.unit_lab_cents(CAT, M.order_cost_cents)


class AnalysisTests(unittest.TestCase):
    def test_unit_lab_costs_come_from_meridian(self):
        self.assertEqual(LAB["ac-5x7"], M.order_cost_cents({"lines": cart(("ac-5x7", 1)), "team": "T"}, CAT)["cents"])
        self.assertGreater(LAB["pkg-a"], LAB["pkg-g"])
        self.assertTrue(all(v is None or v >= 0 for v in LAB.values()))

    def test_whole_shoot(self):
        r = A.analyze(ORDERS, CAT, LAB, shipping_cents=1840)
        s = r["selection"]
        self.assertEqual(s["n"], 3)  # Drew bought nothing
        self.assertEqual(s["sales"], 4000 + 1600 + 1800 + 600 + 1500)
        self.assertEqual(s["profit"], s["sales"] - s["lab"] - 1840)
        self.assertEqual((s["ac_env"], s["ks_env"]), (2, 1))
        self.assertEqual([t["team"] for t in r["teams"]], ["U10", "U12"])
        p = {x["id"]: x for x in r["products"]}
        self.assertEqual((p["ac-5x7"]["sold"], p["ac-5x7"]["sold_with_pkg"], p["ac-5x7"]["sales"]), (2, 2, 1600))
        self.assertEqual((p["ac-8x10"]["sold_alone"], p["ac-8x10"]["sales"]), (1, 1500))
        self.assertEqual(p["pkg-a"]["sold"], 1)
        pays = {x["method"]: x for x in r["payments"]}
        self.assertEqual(pays["Cash"]["envelopes"], 1)
        self.assertEqual(pays["Not paid"]["cents"], 1800 + 600)
        self.assertIsNone(r["compare"])

    def test_one_team_is_before_shipping_and_compared(self):
        r = A.analyze(ORDERS, CAT, LAB, shipping_cents=1840, team="U12")
        s = r["selection"]
        self.assertEqual((s["n"], s["sales"], s["shipping"]), (1, 1500, 0))
        self.assertEqual(s["profit"], s["profit_before"])
        self.assertEqual(r["shoot"]["shipping"], 1840)
        p = {x["id"]: x for x in r["products"]}
        self.assertEqual((p["ac-8x10"]["sold"], p["ac-5x7"]["sold"], p["ac-5x7"]["sold_shoot"]), (1, 0, 2))
        labels = [c["label"] for c in r["compare"]]
        self.assertIn("Average order", labels)
        self.assertEqual(r["teams"], [])

    def test_empty_shoot(self):
        r = A.analyze([], CAT, LAB)
        self.assertEqual((r["selection"]["n"], r["selection"]["avg"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
