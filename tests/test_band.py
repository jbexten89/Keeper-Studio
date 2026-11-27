import unittest
from types import SimpleNamespace

from keeperstudio import engine

R = SimpleNamespace
CFG = SimpleNamespace(landscape_ratios=[R(name="10x8", width=10, height=8), R(name="7x5", width=7, height=5)])


class VisibleTest(unittest.TestCase):
    def test_height_share_centred_on_photo(self):
        b = engine.visible_boxes((3000, 2000), 0.86, CFG)
        for box in b.values():
            self.assertAlmostEqual(box.height, 1720, delta=4)
            self.assertAlmostEqual(box.top + box.height / 2, 1000, delta=3)
            self.assertAlmostEqual(box.left + box.width / 2, 1500, delta=3)
        self.assertGreater(b["7x5"].width, b["10x8"].width)  # 5x7 is wider, same height

    def test_full_height(self):
        box = engine.visible_boxes((3000, 2000), 1.0, CFG)["7x5"]
        self.assertEqual((box.top, box.height), (0, 2000))

    def test_never_runs_off_the_photo(self):
        for box in engine.visible_boxes((2200, 2000), 1.0, CFG).values():
            self.assertGreaterEqual(box.left, 0); self.assertGreaterEqual(box.top, 0)
            self.assertLessEqual(box.left + box.width, 2200); self.assertLessEqual(box.top + box.height, 2000)


if __name__ == "__main__":
    unittest.main()
