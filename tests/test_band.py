import unittest
from types import SimpleNamespace

from keeperstudio import engine

R = SimpleNamespace
CFG = SimpleNamespace(landscape_margin_fraction=0.08,
                      landscape_ratios=[R(name="10x8", width=10, height=8), R(name="7x5", width=7, height=5)])


class BandTest(unittest.TestCase):
    def test_band_height_and_centred_on_team(self):
        b = engine.band_boxes((3000, 2000), 0.17, 0.21, CFG, (1200, 1900))
        box = b["10x8"]
        self.assertAlmostEqual(box.top, 340, delta=4)
        self.assertAlmostEqual(box.height, 1240, delta=8)
        self.assertAlmostEqual(box.left + box.width / 2, 1550, delta=4)
        self.assertGreater(b["7x5"].width, box.width)  # 5x7 is wider, same height

    def test_wide_team_grows_evenly_and_stays_inside(self):
        b = engine.band_boxes((3000, 2000), 0.17, 0.21, CFG, (500, 2500))["10x8"]
        self.assertLessEqual(b.left, 500 - 1)
        self.assertGreaterEqual(b.left + b.width, 2500)
        self.assertGreater(b.height, 1240)
        mid = b.top + b.height / 2
        self.assertAlmostEqual(mid, (340 + 1580) / 2, delta=6)

    def test_no_team_found_centres_on_photo(self):
        b = engine.band_boxes((3000, 2000), 0.17, 0.21, CFG, None)["10x8"]
        self.assertAlmostEqual(b.left + b.width / 2, 1500, delta=4)

    def test_never_runs_off_the_photo(self):
        for box in engine.band_boxes((3000, 2000), 0.0, 0.0, CFG, (0, 3000)).values():
            self.assertGreaterEqual(box.left, 0); self.assertGreaterEqual(box.top, 0)
            self.assertLessEqual(box.left + box.width, 3000); self.assertLessEqual(box.top + box.height, 2000)


if __name__ == "__main__":
    unittest.main()
