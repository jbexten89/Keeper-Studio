import tempfile
import unittest
from pathlib import Path

from keeperstudio import reports as R
from tests.test_orders import CAT, cart, order


class EnvelopesPdfTest(unittest.TestCase):
    def test_one_page_per_envelope_with_the_logo(self):
        orders = [order("Avery", "Varsity", cart(("pkg-a", 1), ("ac-5x7-team", 1)), id=1, envelope="2"),
                  order("Blake", "JV", cart(("pkg-c", 1)), id=2, envelope="1")]
        orders[0].update(parent="Dana", address="1 Main St", phone="419-555-0100", paid_method="cash", paid_cents=5000)
        with tempfile.TemporaryDirectory() as d:
            p = R.envelopes_pdf({"name": "Winter Sports 2026", "date": "2026-12-05"}, orders, CAT, lambda s: None, Path(d) / "env")
            data = p.read_bytes()
        self.assertEqual(p.suffix, ".pdf")
        self.assertGreaterEqual(data.count(b"/Type /Page"), 3)  # 2 pages + the pages tree
        self.assertIsNotNone(R._logo_path())


if __name__ == "__main__":
    unittest.main()
