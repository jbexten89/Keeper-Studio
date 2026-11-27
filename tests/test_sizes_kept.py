import unittest

from keeperstudio import engine


class SizesKeptTest(unittest.TestCase):
    def test_sizes_on_off_not_part_of_a_check(self):
        self.assertNotIn("disabled_sizes", engine._PLAN_SETTINGS)

    def test_switched_off_sizes_are_left_out(self):
        plan = {"path": "a.jpg", "status": "ok", "missing": ["3_5x3_5", "11x14"],
                "boxes": [{"name": "8x10"}, {"name": "11x14"}, {"name": "needed"}]}
        out = engine.for_sizes(plan, {"disabled_sizes": ["11x14"]})
        self.assertEqual([b["name"] for b in out["boxes"]], ["8x10", "needed"])
        self.assertEqual(out["missing"], ["3_5x3_5"])
        self.assertEqual(len(plan["boxes"]), 3)  # the saved check isn't changed
        self.assertIs(engine.for_sizes(plan, {}), plan)


if __name__ == "__main__":
    unittest.main()
