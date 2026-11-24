"""Tests for the Orders tab's logic: python -m unittest discover tests

The pricing, pull-sheet, crop-list and ROES cases are the website's own tests
(jbexten89/photography-orders, lib/*.test.ts), so an envelope typed into
Keeper Studio comes to the same money and the same prints as an online order.
"""

import csv
import io
import tempfile
import unittest
from pathlib import Path

from keeperstudio import orders as O
from keeperstudio.orderbook import OrderBook

ROOT = Path(__file__).resolve().parent.parent
CAT = O.load_catalog(ROOT / "prices.yaml")


def cart(*pairs):
    return [{"product_id": p, "qty": q} for p, q in pairs]


def order(athlete="Avery", team="U10", lines=(), **kw):
    return {"id": kw.pop("id", 1), "envelope": kw.pop("envelope", "1"), "athlete": athlete, "team": team,
            "coach": "", "lines": list(lines), **kw}


def rows(text):
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


class CatalogTests(unittest.TestCase):
    def test_shipped_prices_match_the_built_in_copy(self):
        self.assertEqual((ROOT / "prices.yaml").read_text(encoding="utf-8"), O.DEFAULT_PRICES)

    def test_reads_the_packet(self):
        self.assertEqual(CAT.warnings, [])
        self.assertEqual([p.letter for p in CAT.packages], list("ABCDEFG"))
        self.assertEqual(CAT.get("pkg-f").price, 1800)
        self.assertEqual(CAT.get("pkg-f").contents, {"5x7": 1, "4x6": 2})

    def test_missing_file_falls_back_to_the_packet(self):
        c = O.load_catalog(Path("/nowhere/prices.yaml"))
        self.assertEqual(c.get("pkg-a").price, 4000)
        self.assertTrue(c.warnings)

    def test_money(self):
        self.assertEqual(O.cents("18"), 1800)
        self.assertEqual(O.cents("$1.10"), 110)
        self.assertEqual(O.cents(0.29), 29)
        self.assertEqual(O.money(6400), "$64.00")
        self.assertEqual(O.money(-500), "-$5.00")


class PricingTests(unittest.TestCase):
    def total(self, *pairs):
        return O.calculate(cart(*pairs), CAT)

    def test_empty(self):
        self.assertEqual(self.total()["total_cents"], 0)

    def test_package_a_alone(self):
        r = self.total(("pkg-a", 1))
        self.assertEqual(r["total_cents"], 4000)
        self.assertTrue(r["has_package"])

    def test_8x10_alone_is_full_price(self):
        r = self.total(("ac-8x10", 1))
        self.assertEqual(r["total_cents"], 1500)
        self.assertFalse(r["lines"][0]["discount"])

    def test_package_g_unlocks_the_lower_price(self):
        r = self.total(("pkg-g", 1), ("ac-8x10", 1))
        self.assertEqual(r["total_cents"], 2500)
        self.assertEqual(r["savings_cents"], 500)

    def test_package_a_plus_three_sets_of_4x6(self):
        r = self.total(("pkg-a", 1), ("ac-4x6-3", 3))
        self.assertEqual(r["total_cents"], 6400)
        self.assertEqual(r["savings_cents"], 1200)

    def test_keepsakes_never_discounted(self):
        r = self.total(("pkg-a", 1), ("misc-photo-key-ring", 1))
        self.assertEqual(r["total_cents"], 4600)
        self.assertEqual(r["savings_cents"], 0)

    def test_every_a_la_carte_item_discounted_at_once(self):
        r = self.total(("pkg-g", 1), ("ac-8x10", 1), ("ac-8x10-team", 1), ("ac-5x7", 1), ("ac-5x7-team", 1),
                       ("ac-4x6-3", 1), ("ac-wallets-8", 1))
        self.assertEqual(r["total_cents"], 1500 + 5200)
        self.assertEqual(r["savings_cents"], 2200)

    def test_siblings_and_caps_and_junk(self):
        self.assertEqual(self.total(("pkg-a", 2))["total_cents"], 8000)
        self.assertEqual(self.total(("pkg-a", 99))["lines"][0]["qty"], O.MAX_QTY)
        self.assertEqual(self.total(("pkg-a", 1), ("pkg-a", 1))["lines"][0]["qty"], 2)
        self.assertEqual(self.total(("nope", 3), ("pkg-f", 0), ("pkg-f", -1))["total_cents"], 0)

    def test_carters_envelope(self):
        s = O.order_summary(order(lines=cart(("pkg-f", 1)), paid_cents=1800), CAT)
        self.assertEqual((s["total_cents"], s["due_cents"], s["packages"]), (1800, 0, "F"))


class PullSheetTests(unittest.TestCase):
    def test_expands_a_package(self):
        e = O.expand(order(lines=cart(("pkg-a", 1))), CAT)
        self.assertEqual(e["prints"], {"8x10": 1, "5x7": 3, "5x7:team": 1, "4x6": 2, "wallet": 1})
        self.assertEqual(e["mates"], 1)

    def test_multiplies_and_adds_a_la_carte(self):
        e = O.expand(order(lines=cart(("pkg-f", 2), ("ac-4x6-3", 1), ("ac-wallets-8", 2))), CAT)
        self.assertEqual(e["prints"], {"5x7": 2, "4x6": 7, "wallet": 2})

    def test_team_shot_in_its_own_column(self):
        e = O.expand(order(lines=cart(("ac-8x10-team", 1))), CAT)
        self.assertEqual(e["prints"], {"8x10:team": 1})

    def test_keepsakes_by_piece_and_magnets_by_pack(self):
        e = O.expand(order(lines=cart(("misc-mini-wallets-8", 2), ("misc-wallet-magnets-4", 3))), CAT)
        self.assertEqual(e["misc"], {"misc-mini-wallets-8": 16, "misc-wallet-magnets-4": 3})

    def test_csv_sorts_totals_and_leaves_zeros_blank(self):
        r = rows(O.pull_sheet_csv([order("Zed", "B", cart(("pkg-a", 1)), glasses=True),
                                    order("Avery", "A", cart(("ac-wallets-8", 1)), id=2)], CAT))
        self.assertEqual([x[2] for x in r[1:3]], ["Avery", "Zed"])
        self.assertEqual(r[-1][:2], ["TOTAL", "2 athletes"])
        self.assertEqual(r[-1][4], "1 in glasses")
        self.assertEqual(r[-1][r[0].index("Wallet sheets (8 per sheet)")], "2")
        self.assertNotIn("0", r[1][7:15])
        self.assertIn("5x7 Team", r[0])
        self.assertNotIn("Wallet Team", r[0])


class CropListTests(unittest.TestCase):
    def test_memory_mate_needs_an_individual_and_a_team_5x7(self):
        cl = O.crop_list([order(lines=cart(("pkg-g", 1)), image="IMG_9445.JPG")], CAT, {"U10": "IMG_9946"})
        self.assertEqual([j["file"] for j in cl["athletes"][0]["jobs"]], ["IMG_9445_5x7"])
        self.assertEqual(cl["teams"][0]["sizes"][0]["file"], "IMG_9946_7x5")

    def test_only_what_was_bought_largest_first_with_keeper_names(self):
        a = O.crop_list([order(lines=cart(("pkg-a", 1)), image="IMG_1")], CAT)["athletes"][0]
        self.assertEqual([j["crop"] for j in a["jobs"]], ["8x10", "5x7", "4x6", "2_5x3_5"])
        b = O.crop_list([order(lines=cart(("ac-8x10", 1)), image="IMG_1")], CAT)["athletes"][0]
        self.assertEqual([j["file"] for j in b["jobs"]], ["IMG_1_8x10"])

    def test_team_cropped_once_for_many_orders(self):
        cl = O.crop_list([order(f"K{i}", lines=cart(("pkg-d", 1)), id=i) for i in range(3)], CAT)
        self.assertEqual(cl["teams"][0]["sizes"][0]["ordered_by"], 3)
        team_rows = [x for x in rows(O.crop_list_csv([order(f"K{i}", lines=cart(("pkg-d", 1)), id=i) for i in range(3)], CAT))
                     if x[0] == "TEAM PHOTO"]
        self.assertEqual(len(team_rows), 1)
        self.assertIn("No team photo picked yet", team_rows[0][-1])

    def test_edited_master_wins_and_keepsake_crop(self):
        a = O.crop_list([order(lines=cart(("misc-magnet-4x5", 1), ("misc-photo-badge", 1)), image="IMG_2",
                               edited="Hoffman_final.jpg")], CAT)["athletes"][0]
        self.assertEqual([j["file"] for j in a["jobs"]], ["Hoffman_final_4x5"])

    def test_no_photo_picked(self):
        r = rows(O.crop_list_csv([order("Riley", lines=cart(("pkg-f", 1)))], CAT))
        self.assertTrue(all(x[-1] == "No photo picked yet" for x in r[1:]))


class LabTests(unittest.TestCase):
    def test_carter(self):
        plan = O.lab_plan([order("Carter", lines=cart(("pkg-f", 1)), image="IMG_5371")], CAT)
        got = {(g["group"], it["file"], it["qty"]) for g in plan["groups"] for it in g["items"]}
        self.assertEqual(got, {("5x7", "IMG_5371_5x7", 1), ("4x6", "IMG_5371_4x6", 2)})

    def test_team_5x7_is_one_file_printed_per_mate(self):
        plan = O.lab_plan([order(f"K{i}", lines=cart(("pkg-g", 1)), image=f"IMG_{i}", id=i) for i in range(4)], CAT,
                          {"U10": "IMG_9000"})
        team = next(g for g in plan["groups"] if g["group"] == "5x7 Team")
        self.assertEqual([(it["file"], it["qty"]) for it in team["items"]], [("IMG_9000_7x5", 4)])

    def test_wallets_are_sheets_and_keepsakes_are_units(self):
        plan = O.lab_plan([order(lines=cart(("pkg-a", 1), ("ac-wallets-8", 1), ("misc-mini-wallets-8", 2)), image="IMG_1")], CAT)
        by = {g["group"]: g["items"] for g in plan["groups"]}
        self.assertEqual(by["Wallet"][0]["qty"], 2)
        self.assertEqual((by["Mini Wallets"][0]["file"], by["Mini Wallets"][0]["qty"]), ("", 2))

    def test_build_folder_copies_only_what_is_needed(self):
        with tempfile.TemporaryDirectory() as d:
            crops = Path(d, "crops", "Orders")
            crops.mkdir(parents=True)
            for n in ("IMG_5371_5x7.JPG", "IMG_5371_4x6.JPG", "IMG_5371_8x10.JPG", "IMG_5371_2_5x3_5.JPG"):
                (crops / n).write_bytes(b"x")
            plan = O.lab_plan([order("Carter", lines=cart(("pkg-f", 1)), image="IMG_5371"),
                               order("Riley", lines=cart(("pkg-f", 1)), id=2)], CAT)
            res = O.build_lab_folder(plan, Path(d, "crops"), Path(d, "lab"), one_per_print=True)
            files = sorted(str(p.relative_to(Path(d, "lab"))).replace("\\", "/") for p in Path(d, "lab").rglob("*.JPG"))
            self.assertEqual(files, ["4x6/IMG_5371_4x6_1.JPG", "4x6/IMG_5371_4x6_2.JPG", "5x7/IMG_5371_5x7.JPG"])
            self.assertEqual(len(res["missing"]), 2)
            self.assertTrue(all(m["why"] == "no photo picked" for m in res["missing"]))
            res2 = O.build_lab_folder(plan, Path(d, "crops"), Path(d, "lab2"), one_per_print=False)
            self.assertEqual(res2["copied"], 2)
            self.assertIn("IMG_5371_4x6,2,Carter", Path(res2["csv"]).read_text(encoding="utf-8"))


class RoesTests(unittest.TestCase):
    def test_packages_go_to_the_lab_as_individual_prints(self):
        r = rows(O.roes_csv([order("Carter Newton", lines=cart(("pkg-f", 1)), image="IMG_5371.JPG", envelope="18")],
                            CAT, {"U10": "IMG_9000"}))
        self.assertEqual(r[0][:4], ["CustID", "IndivImage", "GroupIMG", "Package"])
        self.assertEqual(r[1][:4], ["E18", "IMG_5371.JPG", "IMG_9000.jpg", "5x7;4 x 6;4 x 6"])
        self.assertEqual(r[1][4:6], ["Carter", "Newton"])

    def test_jamies_roes_codes(self):
        o = order(lines=cart(("pkg-a", 1), ("misc-magnet-5x7", 1), ("misc-magnet-4x5", 1), ("misc-wallet-magnets-4", 1),
                             ("misc-mini-wallets-8", 1), ("misc-photo-badge", 1), ("misc-photo-key-ring", 1)), image="IMG_1")
        codes = rows(O.roes_csv([o], CAT, {"U10": "IMG_9"}))[1][3].split(";")
        self.assertEqual(codes, ["8x10", "5x7", "5x7", "5x7", "4 x 6", "4 x 6", "WAL", "5x7",
                                 "MAG45", "MAG57", "MWAL", "BADGE", "KEY", "MAGW"])
        self.assertEqual(O.unmapped_roes(CAT), ["4 x 6"])

    def test_memory_mates_wallets_extras_and_keepsakes(self):
        o = order(lines=cart(("pkg-a", 1), ("ac-5x7", 1), ("ac-8x10-team", 1), ("misc-magnet-4x5", 2)), image="IMG_1")
        self.assertEqual(O.lab_items(o, CAT), [("8x10", 1), ("5x7", 4), ("4x6", 2), ("wallet", 1), ("8x10-team", 1),
                                               ("5x7-team", 1), ("misc-magnet-4x5", 2)])

    def test_codes_replace_names_once_filled_in(self):
        c = O.load_catalog(ROOT / "prices.yaml")
        c.roes_items["4x6"]["code"] = "P46"
        r = rows(O.roes_csv([order(lines=cart(("pkg-f", 1)), image="IMG_1")], c))
        self.assertEqual(r[1][3], "5x7;P46;P46")
        self.assertEqual(O.unmapped_roes(c), [])

    def test_unmapped_lists_lab_items_not_packages(self):
        c = O.load_catalog(ROOT / "prices.yaml")
        for it in c.roes_items.values():
            it["code"] = ""
        missing = O.unmapped_roes(c)
        self.assertIn("5 x 7", missing)
        self.assertFalse(any("Package" in m or "team" in m for m in missing))
        self.assertEqual(len(missing), 10)

    def test_team_prints_use_the_individual_code(self):
        c = O.load_catalog(ROOT / "prices.yaml")
        c.roes_items["5x7"]["code"] = "P57"
        r = rows(O.roes_csv([order(lines=cart(("pkg-g", 1)), image="IMG_1")], c, {"U10": "IMG_9000"}))
        self.assertEqual(r[1][2:4], ["IMG_9000.jpg", "P57;P57"])
        self.assertEqual(O.roes_code(c, "8x10-team"), "8x10")
        self.assertEqual(O.roes_items({"5x7-team": {"code": "T57"}})["5x7-team"]["same_as"], "")

    def test_old_prices_file_without_items_still_works(self):
        self.assertEqual(O.roes_items(None)["wallet"]["name"], "8 Wallets")
        self.assertEqual(O.roes_items({"5x7": {"code": "X"}})["5x7"], {"name": "5 x 7", "code": "X", "same_as": ""})


class WebImportTests(unittest.TestCase):
    def test_reads_the_website_export(self):
        text = "﻿Team,Athlete,Coach,Item,Qty,Unit price,Line total,Order #,Paid,Parent,Email,Phone,Address,Notes\r\n" \
               "U10,Carter N,Smith,Package F,1,$18.00,$18.00,JB-1001,11/2/26,Ann,a@x.com,419,,\r\n" \
               "U10,Carter N,Smith,1 — 5x7,1,$8.00,$8.00,JB-1001,11/2/26,Ann,a@x.com,419,,\r\n" \
               "U10,Riley,Smith,Mystery Mug,1,$9.00,$9.00,JB-1002,Not paid,,,,,\r\n"
        got, problems = O.parse_web_csv(text, CAT)
        self.assertEqual(len(got), 2)
        c = got[0]
        self.assertEqual(c["lines"], cart(("pkg-f", 1), ("ac-5x7", 1)))
        self.assertEqual((c["paid_method"], c["paid_cents"]), ("card", 2600))
        self.assertEqual(O.calculate(c["lines"], CAT)["total_cents"], 2600)
        self.assertEqual(len(problems), 1)

    def test_rejects_other_csvs(self):
        with self.assertRaises(ValueError):
            O.parse_web_csv("a,b\n1,2\n", CAT)


class OrderBookTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.book = OrderBook(Path(self.dir.name, "orders.sqlite3"), Path(self.dir.name, "backups"))

    def tearDown(self):
        self.book.close()
        self.dir.cleanup()

    def test_round_trip(self):
        s = self.book.save_shoot({"name": "Montpelier Basketball", "date": "2026-11-15"})
        o = self.book.save_order(s["id"], {"envelope": "18", "athlete": "Carter", "team": "9th", "glasses": True,
                                          "lines": cart(("pkg-f", 1), ("ac-5x7", 0)), "paid_method": "Cash", "paid_cents": 1800})
        self.assertEqual(o["lines"], cart(("pkg-f", 1)))
        self.assertTrue(o["glasses"])
        self.assertEqual(o["paid_method"], "cash")
        self.assertEqual(self.book.next_envelope(s["id"]), "19")
        o2 = self.book.save_order(s["id"], {"id": o["id"], "image": "IMG_5371"})
        self.assertEqual((o2["image"], o2["athlete"]), ("IMG_5371", "Carter"))
        self.assertEqual(self.book.shoots()[0]["n"], 1)

    def test_delete_undo_and_cascade(self):
        s = self.book.save_shoot({"name": "T"})
        o = self.book.save_order(s["id"], {"athlete": "A"})
        gone = self.book.delete_order(o["id"])
        self.assertEqual(self.book.orders(s["id"]), [])
        self.book.restore_order(gone)
        self.assertEqual(len(self.book.orders(s["id"])), 1)
        self.book.delete_shoot(s["id"])
        self.assertEqual(self.book.orders(s["id"]), [])

    def test_team_photos_and_rename(self):
        s = self.book.save_shoot({"name": "T"})
        self.book.save_order(s["id"], {"athlete": "A", "team": "9th grade"})
        self.book.set_team_photo(s["id"], "9th grade", "IMG_5373")
        self.assertEqual(self.book.rename_team(s["id"], "9th grade", "9th Grade Boys"), 1)
        self.assertEqual(self.book.team_photos(s["id"]), {"9th Grade Boys": {"image": "IMG_5373", "coach": ""}})

    def test_needs_a_name(self):
        with self.assertRaises(ValueError):
            self.book.save_shoot({"name": "  "})


if __name__ == "__main__":
    unittest.main()
