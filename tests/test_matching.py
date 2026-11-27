import tempfile
import unittest
from pathlib import Path

from PIL import Image

from keeperstudio import orders as O
from keeperstudio import reports as R

ROOT = Path(__file__).resolve().parent.parent
CAT = O.load_catalog(ROOT / "prices.yaml")


def env(n, team, rank, image, *lines, athlete="", **kw):
    return {"id": n, "envelope": str(n), "athlete": athlete, "team": team, "team_rank": rank, "coach": "Coach Myers",
            "image": image, "edited": "", "lines": [{"product_id": p, "qty": q} for p, q in lines], **kw}


ORDERS = [
    env(47, "7th Boys", 1, "IMG_5031", ("pkg-b", 1), ("ac-8x10-team", 1)),
    env(41, "7th Boys", 1, "IMG_5012", ("pkg-a", 1), ("misc-photo-key-ring", 1)),
    env(3, "8th Girls", 0, "IMG_4001", ("pkg-c", 1)),
    env(83, "7th Boys", 1, "IMG_5084", ("pkg-a", 1)),  # the late envelope
]


class EnvelopeOrderTest(unittest.TestCase):
    def test_lab_items_know_their_team_and_envelope(self):
        plan = O.lab_plan(ORDERS, CAT, {"7th Boys": "IMG_5001"})
        it = next(i for g in plan["groups"] for i in g["items"] if i["file"].startswith("IMG_5031"))
        self.assertEqual((it["team"], it["rank"], it["env"]), ("7th Boys", 1, "47"))

    def test_names_sort_in_stuffing_order(self):
        plan = O.lab_plan(ORDERS, CAT, {"7th Boys": "IMG_5001"})
        items = [i for g in plan["groups"] for i in g["items"] if i["file"] and not i["item"].endswith("-team")]
        names = sorted(O.envelope_order_name(i, i["file"] + ".jpg") for i in items)
        envs = [n.split("_")[1] for n in names]
        # 8th Girls (first team) before 7th Boys; inside a team by envelope number, late #83 last
        first_seen = list(dict.fromkeys(envs))
        self.assertEqual(first_seen, ["E003", "E041", "E047", "E083"])
        self.assertTrue(names[0].startswith("01-8thGirls_E003_IMG_4001"))

    def test_team_print_name(self):
        plan = O.lab_plan(ORDERS, CAT, {"7th Boys": "IMG_5001"})
        it = next(i for g in plan["groups"] for i in g["items"] if i["item"].endswith("-team"))
        self.assertTrue(O.envelope_order_name(it, "IMG_5001_8x10.jpg").startswith("02-7thBoys_TEAM_IMG_5001"))

    def test_contents_spelled_out(self):
        txt = R.envelope_contents(ORDERS[1], CAT)
        self.assertIn("Photo Key Ring", txt)
        self.assertRegex(txt, r"\d× (8x10|5x7)")

    def test_matching_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            photo = Path(d) / "IMG_5031.jpg"
            Image.new("RGB", (400, 500), (90, 140, 200)).save(photo)
            out = R.matching_pdf({"name": "Fall Sports", "date": "2026-10-04"}, ORDERS, CAT,
                                 [{"customer": "For the school", "items": [{"size": "8x10", "src": "team", "team": "7th Boys", "qty": 1}]}],
                                 {"7th Boys": "IMG_5001"}, lambda st: photo if st == "IMG_5031" else None, Path(d) / "m.pdf")
            data = out.read_bytes()
            self.assertTrue(data.startswith(b"%PDF"))
            self.assertGreater(len(data), 3000)


if __name__ == "__main__":
    unittest.main()
