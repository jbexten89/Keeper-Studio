import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keeperstudio import shootfile as SF
from keeperstudio.orderbook import OrderBook


class ShootFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data"), "LOCALAPPDATA": str(self.root / "data")})
        self.env.start()
        self.book = OrderBook(self.root / "a.sqlite3")
        sh = self.book.save_shoot({"name": "Fall Sports", "date": "2026-10-04"})
        self.sid = sh["id"]
        self.book.save_order(self.sid, {"envelope": "1", "athlete": "", "team": "JV", "paid_method": "none",
                                        "lines": [{"product_id": "A", "qty": 1}]})
        self.book.save_order(self.sid, {"envelope": "2", "athlete": "Kid Two", "team": "JV", "lines": []})
        self.book.set_team_photo(self.sid, "JV", "IMG_5001")
        self.book.save_extra(self.sid, {"kind": "school", "items": [{"size": "8x10", "qty": 2}]})
        self.folder = self.root / "Fall Sports"
        self.folder.mkdir()

    def tearDown(self):
        self.book.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_shoot_gets_a_uid(self):
        self.assertEqual(len(self.book.shoot(self.sid)["uid"]), 32)

    def test_folder_file_round_trip_to_another_pc(self):
        self.book.set_folder(self.sid, str(self.folder))
        p = SF.write_folder_file(self.book, self.sid)
        self.assertTrue(p.is_file())
        other = OrderBook(self.root / "b.sqlite3")  # the other computer
        st = SF.folder_status(other, str(self.folder))
        self.assertEqual(st["state"], "new")
        self.assertEqual(st["file"]["envelopes"], 2)
        new_sid = other.import_shoot(SF.read_folder_file(self.folder))
        self.assertEqual(len(other.orders(new_sid)), 2)
        self.assertEqual(other.team_photos(new_sid)["JV"]["image"], "IMG_5001")
        self.assertEqual(len(other.extras(new_sid)), 1)
        self.assertEqual(other.shoot(new_sid)["uid"], self.book.shoot(self.sid)["uid"])
        self.assertEqual(SF.folder_status(other, str(self.folder))["state"], "same")
        other.close()

    def test_newer_file_replaces_the_shoot(self):
        self.book.set_folder(self.sid, str(self.folder))
        SF.write_folder_file(self.book, self.sid)
        other = OrderBook(self.root / "b.sqlite3")
        sid2 = other.import_shoot(SF.read_folder_file(self.folder))
        # more envelopes typed on the first PC
        self.book.save_order(self.sid, {"envelope": "3", "athlete": "", "team": "JV", "lines": []})
        self.book.touch(self.sid)
        other._db.execute("UPDATE shoots SET changed=changed-60"); other._db.commit()  # this PC's copy is a minute older
        SF.write_folder_file(self.book, self.sid)
        st = SF.folder_status(other, str(self.folder))
        self.assertEqual(st["state"], "newer")
        other.import_shoot(SF.read_folder_file(self.folder), replace_sid=sid2)
        self.assertEqual(len(other.orders(sid2)), 3)
        other.close()

    def test_not_an_orders_file(self):
        (self.folder / SF.NAME).write_text(json.dumps({"hello": 1}))
        self.assertIsNone(SF.read_folder_file(self.folder))
        with self.assertRaises(ValueError):
            self.book.import_shoot({"hello": 1})

    def test_backup_and_restore(self):
        made = SF.backup_now(self.book, "manual")
        self.assertTrue(Path(made["file"]).is_file())
        lst = SF.list_backups()
        self.assertEqual(lst["items"][0]["envelopes"], 2)
        # a mistake after the backup
        for o in self.book.orders(self.sid):
            self.book.delete_order(o["id"])
        self.assertEqual(len(self.book.orders(self.sid)), 0)
        holder = {"b": self.book}

        def open_b():
            if holder["b"] is None:
                holder["b"] = OrderBook(self.root / "a.sqlite3")
            return holder["b"]

        def close_b():
            holder["b"].close(); holder["b"] = None

        r = SF.restore(open_b, close_b, lst["items"][0]["name"])
        self.book = holder["b"]
        self.assertEqual(len(self.book.orders(self.sid)), 2)
        # the state before the restore was kept
        names = [i["name"] for i in SF.list_backups()["items"]]
        self.assertIn(r["saved_current"], names)

    def test_second_place(self):
        second = self.root / "usb"; second.mkdir()
        SF.save_settings({"second": str(second)})
        made = SF.backup_now(self.book, "close")
        self.assertTrue(Path(made["second"]).is_file())
        SF.save_settings({"second": str(self.root / "unplugged")})
        made = SF.backup_now(self.book, "close")
        self.assertIn("isn't there", made["second_error"])


if __name__ == "__main__":
    unittest.main()


class HoursTest(unittest.TestCase):
    def test_hours_saved_and_travel_with_the_shoot(self):
        with tempfile.TemporaryDirectory() as d:
            book = OrderBook(Path(d) / "o.sqlite3")
            sid = book.save_shoot({"name": "Fall Sports 2026"})["id"]
            self.assertEqual(book.set_hours(sid, {"shoot": "3.5", "edit": 6, "lab": "", "delivery": "1.5"}),
                             {"shoot": 3.5, "edit": 6.0, "delivery": 1.5})
            with self.assertRaises(ValueError):
                book.set_hours(sid, {"shoot": "lots"})
            data = book.export_shoot(sid)
            self.assertEqual(json.loads(data["shoot"]["hours"])["edit"], 6.0)
            other = OrderBook(Path(d) / "p.sqlite3")
            sid2 = other.import_shoot(data)
            self.assertEqual(json.loads(other.shoot(sid2)["hours"])["shoot"], 3.5)
            book.close(); other.close()
