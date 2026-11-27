import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from keeperstudio import school as SC
from keeperstudio.orderbook import OrderBook


class SchoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        crops = self.root / "crops" / "Orders"
        crops.mkdir(parents=True)
        Image.new("RGB", (3500, 2500), "navy").save(crops / "IMG_1_7x5.jpg")
        Image.new("RGB", (3500, 2500), "teal").save(crops / "IMG_2_7x5.jpg")
        self.teams = [{"name": "Varsity Boys"}, {"name": "JV Girls"}, {"name": "7th Grade"}, {"name": "Cheer"}]
        self.photos = {"Varsity Boys": "IMG_1.jpg", "JV Girls": "IMG_2.jpg", "7th Grade": "IMG_3.jpg"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_team_is_checked(self):
        rows = {r["name"]: r for r in SC.check(self.teams, self.photos, str(self.root / "crops"), ["Cheer"])}
        self.assertEqual(rows["Varsity Boys"]["status"], "ok")
        self.assertEqual(rows["7th Grade"]["why"], "5×7 not cropped yet")
        self.assertEqual(rows["Cheer"]["status"], "skip")
        rows = {r["name"]: r for r in SC.check(self.teams, self.photos, str(self.root / "crops"), [])}
        self.assertEqual(rows["Cheer"]["why"], "No group photo picked")

    def test_zip_has_300dpi_5x7s_named_by_team_in_order(self):
        rows = SC.check(self.teams[:2], self.photos, str(self.root / "crops"), [])
        z = SC.make_zip(rows, self.root / "out" / "Winter Sports 2026 - Team photos.zip")
        self.assertEqual(z["teams"], 2)
        with zipfile.ZipFile(z["path"]) as f:
            self.assertEqual(f.namelist(), ["01 Varsity Boys.jpg", "02 JV Girls.jpg"])
            f.extract("01 Varsity Boys.jpg", self.root)
        with Image.open(self.root / "01 Varsity Boys.jpg") as im:
            self.assertEqual(im.size, (2100, 1500))
            self.assertEqual(round(im.info["dpi"][0]), 300)

    def test_app_password_is_kept_and_read_back(self):
        with mock.patch("keeperstudio.paths.data_dir", return_value=self.root):
            self.assertEqual(SC.save_mail("me@gmail.com", "abcd efgh ijkl mnop"), {"from": "me@gmail.com", "has_password": True})
            self.assertNotIn("abcdefgh", (self.root / "mail.json").read_text())
            self.assertEqual(SC._login(), ("me@gmail.com", "abcdefghijklmnop"))
            self.assertFalse(SC.save_mail(forget=True)["has_password"])

    def test_send_attaches_the_zip(self):
        z = self.root / "t.zip"; z.write_bytes(b"PK" + b"0" * 100)
        with mock.patch("keeperstudio.paths.data_dir", return_value=self.root), mock.patch("smtplib.SMTP_SSL") as smtp:
            SC.save_mail("me@gmail.com", "abcdefghijklmnop")
            r = SC.send("ad@school.org", "Winter Sports 2026 - team photos", "Hi", z)
            smtp.return_value.login.assert_called_with("me@gmail.com", "abcdefghijklmnop")
            msg = smtp.return_value.send_message.call_args[0][0]
            self.assertEqual(msg["To"], "ad@school.org")
            self.assertEqual([p.get_filename() for p in msg.iter_attachments()], ["t.zip"])
            self.assertEqual(r["to"], ["ad@school.org"])
            with self.assertRaises(ValueError):
                SC.send("not an address", "s", "b", z)

    def test_gmail_compose_link(self):
        u = SC.gmail_compose_url("ad@school.org", "Winter Sports 2026 - team photos", "Hi")
        self.assertTrue(u.startswith("https://mail.google.com/mail/?view=cm"))
        self.assertIn("to=ad%40school.org", u)

    def test_school_email_carries_to_next_year(self):
        book = OrderBook(self.root / "a.sqlite3")
        a = book.save_shoot({"name": "Winter Sports 2025", "date": "2025-12-06"})["id"]
        book.school(a); book.set_school(a, {"email": "ad@school.org", "skip": ["Cheer"]})
        b = book.save_shoot({"name": "Winter Sports 2026", "date": "2026-12-05"})["id"]
        self.assertEqual(book.school(b), {"email": "ad@school.org", "skip": [], "sent": None})


if __name__ == "__main__":
    unittest.main()
