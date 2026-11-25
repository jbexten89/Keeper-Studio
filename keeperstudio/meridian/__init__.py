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
        with open(PRODUCTS, encoding="utf-8-sig", newline="") as f:
            _products = {r["product_code"].strip(): r for r in csv.DictReader(f)}
    return _products


def _choices(text: str) -> list[str]:
    import re
    return [re.sub(r"\(\+\$[\d.]+\)|\[default\]", "", p).strip() for p in (text or "").split("|") if p.strip()]


def product_name(code: str) -> str:
    p = products().get(code)
    return p["product_name"] if p else ""


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
    argv = [str(CHECKER), str(order_csv), str(PRODUCTS), str(DESIGNS)] + ([str(folder)] if folder else [])
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
    if rows:
        write_csv(rows, path)
        result = check(path, out_dir)
    else:
        result = {"ok": False, "report": "Nothing to order.", "errors": ["Nothing in this shoot can go in the CSV."],
                  "warnings": [], "total": ""}
    files = len({r["file_name"] for r in rows})
    return {"out_dir": str(out_dir), "csv": str(path) if rows else "", "items": len(rows), "files": files,
            "left_out": left_out, **result}


def _group_of(plan: dict, item: dict) -> str:
    for g in plan["groups"]:
        if any(x is item for x in g["items"]):
            return g["group"]
    return "Prints"
