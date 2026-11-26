"""Folder work files: marks that travel with the shoot folder."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from keeperstudio import workfile as W
from keeperstudio.catalog import Catalog


def photos(root: Path, names=("IMG_1.JPG", "IMG_2.JPG", "IMG_3.JPG", "IMG_4.JPG")):
    out = []
    for i, n in enumerate(names):
        f = root / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * (100 + i))
        out.append({"path": str(f), "rel": n, "size": f.stat().st_size})
    return out


class WorkFileTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.cat = Catalog(self.d / "cat.sqlite3")
        self.old = self.d / "Shoots" / "Fall"
        self.ph = photos(self.old)
        key = lambda p: f"{p['path']}|{p['size']}"
        self.cat.put("meta", key(self.ph[0]), {"flag": 1, "rating": 3, "team": True})
        self.cat.put("meta", key(self.ph[1]), {"flag": -1})
        self.cat.put("meta", key(self.ph[2]), {"flag": 0, "rating": 0})  # nothing really marked
        self.cat.put("manual", self.ph[0]["path"], {"8x10": [0.1, 0.1, 0.8, 0.9]})
        self.cat.put("rotate", self.ph[1]["path"], 1.5)
        self.cat.put("collections", "c1", {"id": "c1", "name": "Banners", "keys": [key(self.ph[0])], "smart": None})

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def moved(self):
        new = self.d / "Archive" / "Fall 2026"
        shutil.copytree(self.old, new)
        return new, [{"path": str(new / p["rel"]), "rel": p["rel"], "size": p["size"]} for p in self.ph]

    def test_save_writes_only_marked_photos(self):
        r = W.save(self.cat, str(self.old), self.ph)
        self.assertEqual(r["photos"], 2)
        d = json.loads((self.old / W.NAME).read_text(encoding="utf-8"))
        self.assertEqual(set(d["photos"]), {"IMG_1.JPG", "IMG_2.JPG"})
        self.assertEqual(d["photos"]["IMG_1.JPG"]["manual"], {"8x10": [0.1, 0.1, 0.8, 0.9]})
        self.assertEqual(d["collections"][0]["files"], ["IMG_1.JPG"])

    def test_nothing_marked_leaves_no_file(self):
        empty = self.d / "Empty"
        r = W.save(self.cat, str(empty), photos(empty))
        self.assertTrue(r.get("skipped"))
        self.assertFalse((empty / W.NAME).exists())

    def test_restore_after_a_move_from_the_work_file(self):
        W.save(self.cat, str(self.old), self.ph)
        new, ph2 = self.moved()
        st = W.status(self.cat, str(new), ph2)
        self.assertEqual((st["marks_here"], st["file"]["photos"]), (0, 2))
        self.assertEqual(W.restore_from_file(self.cat, str(new), ph2), 2)
        self.assertEqual(self.cat.get("meta", f"{ph2[0]['path']}|{ph2[0]['size']}")["rating"], 3)
        self.assertEqual(self.cat.get("rotate", ph2[1]["path"]), 1.5)
        c = self.cat.get("collections", "c1")
        self.assertIn(f"{ph2[0]['path']}|{ph2[0]['size']}", c["keys"])
        self.assertEqual(W.marks_here(self.cat, ph2), 2)

    def test_saving_before_restoring_keeps_the_saved_marks(self):
        W.save(self.cat, str(self.old), self.ph)
        new, ph2 = self.moved()
        self.cat.put("meta", f"{ph2[3]['path']}|{ph2[3]['size']}", {"flag": 1})  # marked one photo first
        r = W.save(self.cat, str(new), ph2)
        self.assertEqual(r["photos"], 3)  # the two saved ones are still there, plus the new one
        self.assertEqual(W.restore_from_file(self.cat, str(new), ph2), 3)

    def test_clearing_a_mark_here_removes_it_from_the_file(self):
        W.save(self.cat, str(self.old), self.ph)
        self.cat.put("meta", f"{self.ph[1]['path']}|{self.ph[1]['size']}", {"flag": 0})
        self.cat.delete("rotate", self.ph[1]["path"])
        W.save(self.cat, str(self.old), self.ph)
        d = json.loads((self.old / W.NAME).read_text(encoding="utf-8"))
        self.assertEqual(set(d["photos"]), {"IMG_1.JPG"})

    def test_a_changed_file_is_not_given_old_marks(self):
        W.save(self.cat, str(self.old), self.ph)
        new, ph2 = self.moved()
        ph2[0]["size"] += 1  # edited since
        self.assertEqual(W.restore_from_file(self.cat, str(new), ph2), 1)

    def test_find_moved_without_a_work_file(self):
        new, ph2 = self.moved()
        (new / W.NAME).unlink(missing_ok=True)
        # make the old shoot look like a shoot: mark enough photos
        for p in self.ph[2:]:
            self.cat.put("meta", f"{p['path']}|{p['size']}", {"flag": 1})
        st = W.status(self.cat, str(new), ph2)
        self.assertIsNone(st["file"])
        self.assertEqual(st["moved"]["folder"], str(self.old))
        self.assertEqual(W.restore_moved(self.cat, str(new), ph2, str(self.old)), 4)
        self.assertEqual(self.cat.get("manual", ph2[0]["path"]), {"8x10": [0.1, 0.1, 0.8, 0.9]})
        self.assertIn(f"{ph2[0]['path']}|{ph2[0]['size']}", self.cat.get("collections", "c1")["keys"])

    def test_no_moved_offer_for_a_few_coincidences(self):
        other = self.d / "Other"
        ph3 = photos(other, ("IMG_1.JPG",) + tuple(f"DSC_{i}.JPG" for i in range(30)))
        self.assertIsNone(W.find_moved(self.cat, str(other), ph3))


if __name__ == "__main__":
    unittest.main()
