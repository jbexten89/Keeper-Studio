"""Meridian Professional Imaging's bulk order CSV.

Meridian sent the files in this folder: their product list (products.csv), the
designs for memory mates and trader cards (designs.csv), the column template,
an example, their instructions and their checker (validate_order.py). Orders >
Lab order > Meridian bulk order writes one folder Meridian can take whole: the
cropped files in a sub-folder per print size, and <shoot>-meridian-order.csv
beside them with a row per file, already checked with validate_order.py.

Every print is a file Crop already cut to the print's shape, so each row says
crop=exact and Meridian prints it as it is.
"""

from __future__ import annotations

import contextlib
import gc
import csv
import io
import runpy
import shutil
import sys
import warnings
from pathlib import Path

from .. import orders as O

HERE = Path(__file__).resolve().parent
PRODUCTS = HERE / "products.csv"
# Optional: products Meridian confirmed that aren't in their products.csv yet
# (same columns). The checker reads them together with Meridian's list.
PRODUCTS_EXTRA = HERE / "products-extra.csv"
DESIGNS = HERE / "designs.csv"
CHECKER = HERE / "validate_order.py"
COLUMNS = ["order_name", "account_email", "color_correction", "delivery", "item_id", "product_code", "design_name",
           "quantity", "file_name", "image_order", "text_fields", "finish", "mounting", "texture", "other_options",
           "crop", "crop_focus", "caption", "notes"]
DEFAULT_SETTINGS = {"account_email": "", "delivery": "ship", "color_correction": "no", "finish": "Matte"}

_products: dict | None = None


def products() -> dict[str, dict]:
    global _products
    if _products is None:
        _products = {}
        for path in (PRODUCTS, PRODUCTS_EXTRA):
            if path.is_file():
                with open(path, encoding="utf-8-sig", newline="") as f:
                    _products.update({r["product_code"].strip(): r for r in csv.DictReader(f)})
    return _products


def _all_products_csv(folder) -> Path:
    """Meridian's list plus the extra products, as one file for their checker."""
    out = Path(folder) / "_products.csv"
    with open(PRODUCTS, encoding="utf-8-sig", newline="") as f:
        head = next(csv.reader(f))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=head)
        w.writeheader()
        w.writerows(products().values())
    return out


def _choices(text: str) -> list[str]:
    import re
    return [re.sub(r"\(\+\$[\d.]+\)|\[default\]", "", p).strip() for p in (text or "").split("|") if p.strip()]


def product_name(code: str) -> str:
    p = products().get(code)
    return p["product_name"] if p else ""


def _upcharge(text: str, choice: str) -> float:
    import re
    for p in (text or "").split("|"):
        name = re.sub(r"\(\+\$[\d.]+\)|\[default\]", "", p).strip()
        if name.lower() == (choice or "").lower():
            m = re.search(r"\(\+\$([\d.]+)\)", p)
            return float(m.group(1)) if m else 0.0
    return 0.0


def order_cost_cents(order: dict, catalog: O.Catalog, settings: dict | None = None) -> dict:
    """Estimated lab cost of one envelope at Meridian's list prices.

    Counts every print and keepsake the envelope sends to the lab (team prints
    included), whether or not a photo is picked yet. Shipping, tax and
    discounts aren't in Meridian's list, so this is an estimate.
    Returns {"cents": total, "unpriced": [labels with no Meridian code]}.
    """
    finish = ((settings or {}).get("finish") or DEFAULT_SETTINGS["finish"])
    plan = O.lab_plan([order], catalog, {})
    total, unpriced = 0.0, []
    for g in plan["groups"]:
        for it in g["items"]:
            code, per = O.meridian_code(catalog, it.get("item") or "")
            p = products().get(code)
            if not p or not p.get("base_price_usd"):
                unpriced.append(g["group"])
                continue
            unit = float(p["base_price_usd"]) + _upcharge(p["finish_choices"], finish)
            total += unit * it["qty"] * per
    return {"cents": int(round(total * 100)), "unpriced": unpriced}


def settings_problems(s: dict) -> list[str]:
    out = []
    if "@" not in (s.get("account_email") or ""):
        out.append("Fill in the email of your Meridian account.")
    if s.get("delivery") not in ("ship", "pickup"):
        out.append("Choose Ship or Pickup.")
    return out


def plan_rows(plan: dict, catalog: O.Catalog, settings: dict, order_name: str,
              file_for) -> tuple[list[dict], list[dict]]:
    """The CSV rows for a lab plan, and what can't go in it (and why).

    file_for(item) gives the file's path inside the order folder, or "" when the
    crop wasn't found.
    """
    s = {**DEFAULT_SETTINGS, **{k: v for k, v in (settings or {}).items() if v}}
    rows, left_out = [], []
    n = 0
    for g in plan["groups"]:
        for it in g["items"]:
            code, per = O.meridian_code(catalog, it.get("item") or "")
            p = products().get(code)
            why = ""
            if not it["file"]:
                why = it["why"] or "no photo"
            elif not code:
                why = "no Meridian product code for it yet (Prices…)"
            elif not p or not p["how_to_order"].startswith("Bulk upload"):
                why = f"{code} isn't one of Meridian's bulk-upload products"
            name = file_for(it) if not why else ""
            if not why and not name:
                why = "not found in the crops folder"
            if why:
                left_out.append({"group": g["group"], "file": it["file"], "qty": it["qty"], "for": it["for"], "why": why})
                continue
            n += 1
            finish = s["finish"] if s["finish"].lower() in [c.lower() for c in _choices(p["finish_choices"])] else ""
            who = ", ".join(it["for"])
            rows.append({
                "order_name": order_name, "account_email": s["account_email"], "color_correction": s["color_correction"],
                "delivery": s["delivery"], "item_id": str(n), "product_code": code, "design_name": "",
                "quantity": str(it["qty"] * per), "file_name": name, "image_order": "", "text_fields": "",
                "finish": finish, "mounting": "", "texture": "", "other_options": "", "crop": "exact",
                "crop_focus": "", "caption": "", "notes": ("For " + who)[:80] if who else "",
            })
    return rows, left_out


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def check(order_csv: Path, folder: Path | None = None) -> dict:
    """Run Meridian's own validate_order.py; returns its report and whether it passed."""
    import tempfile
    tmp = tempfile.TemporaryDirectory()
    argv = [str(CHECKER), str(order_csv), str(_all_products_csv(tmp.name)), str(DESIGNS)] + ([str(folder)] if folder else [])
    out = io.StringIO()
    old = sys.argv
    code = 0
    try:
        sys.argv = argv
        # Meridian's script leaves its files open; collect them straight away so
        # Windows doesn't keep the order CSV locked.
        with contextlib.redirect_stdout(out), warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            try:
                runpy.run_path(str(CHECKER), run_name="__main__")
            except SystemExit as e:
                code = int(e.code or 0) if not isinstance(e.code, str) else 1
            gc.collect()
    finally:
        sys.argv = old
        tmp.cleanup()
    text = out.getvalue()
    lines = text.splitlines()
    return {"ok": code == 0, "report": text,
            "errors": [l.strip() for l in lines if l.startswith("ERROR")],
            "warnings": [l.strip() for l in lines if l.startswith("WARN")],
            "total": next((l.split("$")[-1].strip() for l in lines if "Estimated total" in l), "")}


def build(plan: dict, catalog: O.Catalog, crops_dir: Path, out_dir: Path, settings: dict, order_name: str) -> dict:
    """Copy each cropped file once into out_dir/<size>/, write the order CSV beside them and check it."""
    stems = {it["file"] for g in plan["groups"] for it in g["items"] if it["file"]}
    found = O.find_crops(Path(crops_dir), stems)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def file_for(it):
        src = found.get(it["file"].lower())
        if not src:
            return ""
        sub = O.safe_name(_group_of(plan, it))
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out_dir / sub / src.name)
        return f"{sub}/{src.name}"

    rows, left_out = plan_rows(plan, catalog, settings, order_name, file_for)
    name = O.safe_name(order_name) + "-meridian-order.csv"
    path = out_dir / name
    pdf_path = ""
    if rows:
        write_csv(rows, path)
        result = check(path, out_dir)
        try:  # a printable copy beside the CSV; the order itself is the CSV
            from .. import reports
            t = report(path)
            pdf_path = str(reports.pdf(t, path.with_suffix(".pdf"), t["title"], t["subtitle"]))
        except Exception:  # noqa: BLE001 - never lose the order over its printout
            pdf_path = ""
    else:
        result = {"ok": False, "report": "Nothing to order.", "errors": ["Nothing in this shoot can go in the CSV."],
                  "warnings": [], "total": ""}
    files = len({r["file_name"] for r in rows})
    return {"out_dir": str(out_dir), "csv": str(path) if rows else "", "pdf": pdf_path, "items": len(rows), "files": files,
            "left_out": left_out, **result}


def report(order_csv) -> dict:
    """The order CSV as a readable table: one row per file, grouped by print size, with
    Meridian's product name and list price, and the order settings in the subtitle."""
    with open(order_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    head = ["Item", "Code", "Product", "Qty", "File", "Finish", "Each", "Est. cost", "For"]
    out, total_qty, total = [], 0, 0.0
    groups = {}
    for r in rows:
        groups.setdefault(r["file_name"].split("/")[0] if "/" in r["file_name"] else "", []).append(r)
    for g, rs in groups.items():
        out.append({"kind": "group", "label": f"{g or 'Files'}  ·  {len(rs)} {'file' if len(rs) == 1 else 'files'}"})
        for r in rs:
            p = products().get(r["product_code"]) or {}
            each = float(p.get("base_price_usd") or 0) + _upcharge(p.get("finish_choices", ""), r.get("finish", ""))
            qty = int(r.get("quantity") or 0)
            total_qty += qty
            total += each * qty
            out.append({"kind": "row", "cells": [r["item_id"], r["product_code"], p.get("product_name", ""), str(qty),
                                                 r["file_name"].split("/")[-1], r.get("finish", ""),
                                                 O.money(round(each * 100)), O.money(round(each * qty * 100)),
                                                 (r.get("notes") or "").removeprefix("For ")]})
    first = rows[0] if rows else {}
    out.append({"kind": "total", "cells": ["TOTAL", "", f"{len(rows)} items", str(total_qty), "", "", "",
                                            O.money(round(total * 100)), "before shipping and tax"]})
    sub = " · ".join(x for x in [first.get("order_name", ""), first.get("account_email", ""),
                                  "Ship" if first.get("delivery") == "ship" else "Pickup" if first.get("delivery") else "",
                                  "Color correction: " + (first.get("color_correction") or "no")] if x)
    return {"title": "Meridian order", "subtitle": sub, "head": head, "rows": out,
            "align": ["num", "text", "text", "num", "text", "text", "money", "money", "text"]}


def _group_of(plan: dict, item: dict) -> str:
    for g in plan["groups"]:
        if any(x is item for x in g["items"]):
            return g["group"]
    return "Prints"
