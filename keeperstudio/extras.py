"""School & other orders: prints for the school, the park, teachers or a sponsor.

They aren't on any envelope. Each order has a customer and items; an item is a
size and a Meridian product (print, standout, canvas…) of either every team's
group photo (a count for each team), one team's group photo, or one photo.
A price of $0 makes it a free print. Money is in cents.
"""

from __future__ import annotations

import re

from . import meridian as M
from . import orders as O

KINDS = {  # quick-add buttons: what a new order of that kind starts with
    "School": {"size": "8x10"},
    "Park": {"size": "5x7"},
    "Teachers": {"size": "5x7"},
}
SIZES = ["4x6", "5x7", "8x10", "11x14", "16x20"]
# The crop file each size is printed from: a portrait crop for one person's
# photo, a landscape crop for a group photo. 16x20 has its own crop; it is the
# same shape as 8x10, so the 8x10 crop stands in when 16x20 is switched off in Crop.
PORTRAIT_CROP = {"4x6": "4x6", "5x7": "5x7", "8x10": "8x10", "11x14": "11x14", "16x20": "16x20"}
STAND_IN = {"16x20": "8x10", "20x16": "10x8"}
GROUP_CROP = {"4x6": "6x4", "5x7": "7x5", "8x10": "10x8", "11x14": "14x11", "16x20": "20x16"}
PRODUCTS = [  # Meridian categories offered, and the short name shown
    ("Professional Prints", "Print"), ("Giclee Prints", "Giclee print"), ("Standouts", "Standout"),
    ("Metal Prints", "Metal"), ("Canvas", "Canvas"), ("Acrylic Prints", "Acrylic"),
    ("Float Frames", "Float frame"), ("Bamboo Wall Panels", "Bamboo panel"),
]
SHORT = dict(PRODUCTS)


def _size_of(p: dict) -> str:
    m = re.match(r"\s*([\d.]+)\s*x\s*([\d.]+)", p.get("print_size_in") or "")
    if not m:
        return ""
    a, b = sorted((float(m.group(1)), float(m.group(2))))
    return f"{a:g}x{b:g}"


def product_code(size: str, product: str, landscape: bool) -> str:
    """Meridian's code for this size and product, in the photo's orientation; "" when it has none."""
    best = ""
    for code, p in M.products().items():
        if p.get("category") != product or _size_of(p) != size or not p.get("how_to_order", "").startswith("Bulk upload"):
            continue
        if "needs design" in p["how_to_order"]:
            continue
        o = (p.get("orientation") or "").lower()
        if o.startswith("either"):
            best = best or code
        elif o == ("landscape" if landscape else "portrait"):
            return code
    return best


def choices() -> dict:
    """Sizes and, for each, the products Meridian makes in it with their lab price."""
    out = {}
    for size in SIZES:
        rows = []
        for cat, short in PRODUCTS:
            code = product_code(size, cat, False) or product_code(size, cat, True)
            if code:
                rows.append({"product": cat, "name": short, "lab_cents": lab_each(code)})
        out[size] = rows
    return {"sizes": SIZES, "products": out, "kinds": KINDS}


def lab_each(code: str) -> int | None:
    p = M.products().get(code)
    if not p or not p.get("base_price_usd"):
        return None
    finish = M.DEFAULT_SETTINGS["finish"]
    return int(round((float(p["base_price_usd"]) + M._upcharge(p.get("finish_choices", ""), finish)) * 100))


def item_qty(it: dict) -> int:
    if it.get("src") == "teams":
        return sum(max(0, int(n or 0)) for n in (it.get("counts") or {}).values())
    return max(0, int(it.get("qty") or 0))


def _parts(it: dict, team_photos: dict) -> list[dict]:
    """The files one item prints: [{frame, qty, label, landscape, team}]."""
    if it.get("src") == "teams":
        return [{"frame": O.frame_stem(team_photos.get(t)), "qty": max(0, int(n or 0)), "label": f"{t} team",
                 "landscape": True, "team": t} for t, n in (it.get("counts") or {}).items() if int(n or 0) > 0]
    if it.get("src") == "team":
        t = it.get("team") or ""
        return [{"frame": O.frame_stem(team_photos.get(t)), "qty": item_qty(it), "label": f"{t} team",
                 "landscape": True, "team": t}]
    return [{"frame": O.frame_stem(it.get("image")), "qty": item_qty(it), "label": it.get("label") or O.frame_stem(it.get("image")),
             "landscape": False, "team": ""}]


def lines(order: dict, team_photos: dict, crop_names: set[str] | None = None) -> list[dict]:
    """Each file to print for one order, with its code, cost and anything stopping it."""
    out = []
    for i, it in enumerate(order.get("items") or []):
        size, product = it.get("size") or "", it.get("product") or "Professional Prints"
        for part in _parts(it, team_photos):
            if part["qty"] <= 0:
                continue
            crop = (GROUP_CROP if part["landscape"] else PORTRAIT_CROP).get(size, size)
            if crop_names is not None and crop not in crop_names and STAND_IN.get(crop) in crop_names:
                crop = STAND_IN[crop]
            code = product_code(size, product, part["landscape"])
            why = ""
            if not part["frame"]:
                why = "no group photo picked" if part["landscape"] else "no photo picked"
            elif crop_names is not None and crop not in crop_names:
                why = f"{size} isn't set up in Crop"
            elif not code:
                why = f"Meridian has no {SHORT.get(product, product).lower()} at {size}"
            out.append({"item": i, "size": size, "product": product, "crop": crop, "code": code,
                        "file": f"{part['frame']}_{crop}" if part["frame"] else "", "qty": part["qty"],
                        "label": part["label"], "team": part["team"], "landscape": part["landscape"], "why": why,
                        "lab_each": lab_each(code) if code else None})
    return out


def summary(order: dict, team_photos: dict) -> dict:
    sales = sum(item_qty(it) * int(it.get("price_cents") or 0) for it in order.get("items") or [])
    ls = lines(order, team_photos)
    lab = sum((l["lab_each"] or 0) * l["qty"] for l in ls)
    paid = int(order.get("paid_cents") or 0)
    return {"sales_cents": sales, "lab_cents": lab, "paid_cents": paid, "due_cents": max(0, sales - paid),
            "prints": sum(item_qty(it) for it in order.get("items") or []), "free": sales == 0,
            "profit_cents": sales - lab, "unpriced": sorted({f"{l['size']} {SHORT.get(l['product'], l['product'])}"
                                                             for l in ls if l["lab_each"] is None})}


def totals(orders: list[dict], team_photos: dict) -> dict:
    t = {"count": len(orders), "sales_cents": 0, "lab_cents": 0, "paid_cents": 0, "due_cents": 0, "prints": 0}
    for o in orders:
        s = summary(o, team_photos)
        for k in ("sales_cents", "lab_cents", "paid_cents", "due_cents", "prints"):
            t[k] += s[k]
    t["profit_cents"] = t["sales_cents"] - t["lab_cents"]
    return t


def who(order: dict) -> str:
    k, c = (order.get("kind") or "").strip(), (order.get("customer") or "").strip()
    return f"{k}: {c}" if k and c and c.lower() != k.lower() else (k or c or "Other order")


def add_to_plan(plan_add, orders: list[dict], team_photos: dict) -> None:
    """Put every school/other print into a lab plan, through lab_plan's add()."""
    for o in orders:
        name = who(o)
        for l in lines(o, team_photos):
            plain = l["product"] == "Professional Prints"
            size_label = l["size"] + (" Team" if l["landscape"] else "")
            group = size_label if plain else f"{l['size']} {SHORT.get(l['product'], l['product'])}"
            plan_add(group, l["crop"], l["file"], l["qty"], f"{name} ({l['label']})", group,
                     l["why"] if not l["file"] else "", item=f"code:{l['code']}" if l["code"] else "")
