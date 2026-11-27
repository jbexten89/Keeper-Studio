import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keeperstudio import order_routes as RT
from keeperstudio import shootfile as SF
from keeperstudio.orderbook import OrderBook


class FolderLinkTest(unittest.TestCase):
    def test_never_writes_over_another_shoots_orders_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); folder = root / "Winter Sports"; folder.mkdir()
            book = OrderBook(root / "a.sqlite3")
            try:
                a = book.save_shoot({"name": "Winter Sports", "date": "2026-11-18"})["id"]
                b = book.save_shoot({"name": "Test shoot", "date": "2026-12-01"})["id"]
                with mock.patch.object(RT, "book", book):
                    RT.r_folder_link({"shoot_id": a, "folder": str(folder)})
                    with self.assertRaises(ValueError):
                        RT.r_folder_link({"shoot_id": b, "folder": str(folder)})
                    self.assertEqual(SF.read_folder_file(folder)["shoot"]["name"], "Winter Sports")
                    RT.r_folder_link({"shoot_id": a, "folder": str(folder)})  # its own folder is fine
            finally:
                book.close()


if __name__ == "__main__":
    unittest.main()
