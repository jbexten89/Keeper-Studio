"""Picture-day orders: the catalog, prices, and everything worked out from an order.

Ported from the Photography Orders website (jbexten89/photography-orders,
lib/catalog.ts, pricing.ts, pull-sheet.ts, crop-list.ts, roes.ts) so the desktop
app prices an envelope exactly the way the website priced an online order.

Pure functions only: no SQLite, no files except reading prices.yaml. Storage is
in orderbook.py. All money is integer cents, never floats.

An *order* here is a plain dict as stored by the order book:

    {"id", "shoot_id", "envelope", "athlete", "team", "coach", "parent", "phone",
     "email", "glasses", "frames", "image", "edited", "notes",
     "paid_method", "paid_cents", "lines": [{"product_id", "qty"}]}
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

MAX_QTY = 20

# Physical size in inches (for sorting largest first) and how the lab sells it.
PRINT_SIZES = {
    "8x10": {"label": "8x10", "plural": "8x10", "w": 8, "h": 10},
    "5x7": {"label": "5x7", "plural": "5x7", "w": 5, "h": 7},
    "4x6": {"label": "4x6", "plural": "4x6", "w": 4, "h": 6},
    "wallet": {"label": "Wallet", "plural": "Wallets", "w": 2.5, "h": 3.5, "sheet": 8},
    "memory-mate": {"label": "Memory Mate", "plural": "Memory Mates", "w": 10, "h": 7},
}
MEMORY_MATE = "memory-mate"


def cents(dollars) -> int:
    """'18', 18, 18.0 or '$18.00' -> 1800, rounded to the cent without float error."""
    s = str(dollars if dollars is not None else 0).replace("$", "").replace(",", "").strip() or "0"
    return int((Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(c: int) -> str:
    sign = "-" if c < 0 else ""
    c = abs(int(c))
    return f"{sign}${c // 100:,}.{c % 100:02d}"


# --------------------------------------------------------------- catalog --

@dataclass
class Product:
    id: str
    type: str  # package | alacarte | misc
    label: str
    price: int  # cents; for a la carte, the price on its own
    with_package: int = 0  # a la carte only
    letter: str = ""
    badge: str = ""
    contents: dict = field(default_factory=dict)  # package only: size -> qty
    size: str = ""  # a la carte only
    unit: int = 1
    team: bool = False
    pack: int = 0  # misc only
    crop: str = ""  # misc only

    def to_json(self) -> dict:
        d = {"id": self.id, "type": self.type, "label": self.label, "price": self.price}
        if self.type == "package":
            d.update(letter=self.letter, badge=self.badge, contents=self.contents,
                     summary=", ".join(content_label(s, q) for s, q in self.contents.items()))
        elif self.type == "alacarte":
            d.update(with_package=self.with_package, size=self.size, unit=self.unit, team=self.team,
                     unit_label=f"{self.unit} — {self.label}", short=short_label(self))
        else:
            d.update(unit=self.unit, pack=self.pack, crop=self.crop, unit_label=f"{self.unit} — {self.label}",
                     short=short_label(self))
        return d


@dataclass
class Catalog:
    products: list
    crop_individual: dict
    crop_team: dict
    roes_items: dict  # lab item -> {"name", "code"}
    roes_delimiter: str = ";"
    source: str = ""
    warnings: list = field(default_factory=list)
    meridian_items: dict = field(default_factory=dict)  # lab item -> {"code", "per", "same_as"}

    def __post_init__(self):
        self.by_id = {p.id: p for p in self.products}

    @property
    def packages(self):
        return [p for p in self.products if p.type == "package"]

    def get(self, pid: str) -> Product | None:
        return self.by_id.get(pid)

    def label_for(self, pid: str) -> str:
        p = self.get(pid)
        if not p:
            return pid
        return p.label if p.type == "package" else f"{p.unit} — {p.label}"

    def to_json(self) -> dict:
        return {"products": [p.to_json() for p in self.products], "source": self.source,
                "warnings": self.warnings, "unmapped_roes": unmapped_roes(self)}


def short_label(p: Product) -> str:
    """'8x10', '8x10 Team', 'Set of 3 4x6', '8 Wallets', '4x5 Magnet'."""
    if p.unit <= 1:
        return p.label
    return f"Set of {p.unit} {p.label}" if p.label[:1].isdigit() else f"{p.unit} {p.label}"


def content_label(size: str, qty: int) -> str:
    s = PRINT_SIZES.get(size, {"label": size, "plural": size})
    return f"{qty} — {s['label'] if qty == 1 else s['plural']}"


def load_catalog(path: Path | None) -> Catalog:
    """Read prices.yaml. A missing or broken file falls back to the packet's prices."""
    import yaml
    warnings: list[str] = []
    data = None
    if path and Path(path).is_file():
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(f"prices.yaml could not be read ({exc}); using the packet's prices.")
    elif path:
        warnings.append(f"prices.yaml not found at {path}; using the packet's prices.")
    if not isinstance(data, dict):
        data = yaml.safe_load(DEFAULT_PRICES)
        source = "built-in"
    else:
        source = str(path)
    products: list[Product] = []
    seen: set[str] = set()

    def add(p: Product):
        if p.id in seen:
            warnings.append(f"Product id {p.id} appears twice in prices.yaml; the second was ignored.")
            return
        seen.add(p.id)
        products.append(p)

    for raw in data.get("packages") or []:
        contents = {str(k): int(v) for k, v in (raw.get("contents") or {}).items()}
        bad = [k for k in contents if k not in PRINT_SIZES]
        if bad:
            warnings.append(f"{raw.get('name')}: unknown size {', '.join(bad)}.")
        add(Product(id=str(raw["id"]), type="package", label=str(raw.get("name") or raw["id"]),
                    price=cents(raw.get("price")), letter=str(raw.get("letter") or ""),
                    badge=str(raw.get("badge") or ""), contents=contents))
    for raw in data.get("alacarte") or []:
        add(Product(id=str(raw["id"]), type="alacarte", label=str(raw.get("label") or raw["id"]),
                    price=cents(raw.get("price")), with_package=cents(raw.get("with_package", raw.get("price"))),
                    size=str(raw.get("size") or ""), unit=int(raw.get("unit") or 1), team=bool(raw.get("team"))))
    for raw in data.get("misc") or []:
        add(Product(id=str(raw["id"]), type="misc", label=str(raw.get("label") or raw["id"]),
                    price=cents(raw.get("price")), unit=int(raw.get("unit") or 1), pack=int(raw.get("pack") or 0),
                    crop=str(raw.get("crop") or "")))
    crops = data.get("crop_sizes") or {}
    roes = data.get("roes") or {}
    return Catalog(
        products=products,
        crop_individual={str(k): str(v) for k, v in (crops.get("individual") or DEFAULT_CROPS["individual"]).items()},
        crop_team={str(k): str(v) for k, v in (crops.get("team") or DEFAULT_CROPS["team"]).items()},
        roes_items=roes_items(roes.get("items")),
        roes_delimiter=str(roes.get("delimiter") or ";"),
        source=source, warnings=warnings,
        meridian_items=meridian_items((data.get("meridian") or {}).get("items")),
    )


def roes_items(raw) -> dict:
    """The lab items ROES orders, from prices.yaml; any item missing keeps its default.

    An item with same_as (the landscape team prints) has no code of its own: it
    uses the code of the size it is printed as.
    """
    out = {k: dict(v) for k, v in DEFAULT_ROES_ITEMS.items()}
    for k, v in (raw or {}).items() if isinstance(raw, dict) else []:
        v = v if isinstance(v, dict) else {"code": v}
        base = out.get(str(k), {})
        out[str(k)] = {"name": str(v.get("name") or base.get("name") or k), "code": str(v.get("code") or "").strip(),
                       "same_as": str(v.get("same_as") or (base.get("same_as") if "code" not in v else "") or "")}
    return out


# Meridian's bulk order CSV: the product code each lab item is ordered as.
# per (optional): how many of Meridian's items one of ours is. An item
# without a code isn't sent; Lab order lists it.
DEFAULT_MERIDIAN_ITEMS = {
    "8x10": {"code": "R1680A"}, "5x7": {"code": "RA1657"}, "4x6": {"code": "R1646"},
    "wallet": {"code": "PKG-8-Wallets"},
    "8x10-team": {"same_as": "8x10"}, "5x7-team": {"same_as": "5x7"},
    "misc-magnet-4x5": {"code": "MAG45"}, "misc-magnet-5x7": {"code": "MAG57"},
    "misc-mini-wallets-8": {"code": "R1688"}, "misc-wallet-magnets-4": {"code": "RA78B"},
    "misc-photo-key-ring": {"code": "R606-2"}, "misc-photo-badge": {"code": "R73"},
}


def meridian_items(raw) -> dict:
    out = {k: dict(v) for k, v in DEFAULT_MERIDIAN_ITEMS.items()}
    for k, v in (raw or {}).items() if isinstance(raw, dict) else []:
        v = v if isinstance(v, dict) else {"code": v}
        out[str(k)] = {"code": str(v.get("code") or "").strip(), "per": int(v.get("per") or 1),
                       "same_as": str(v.get("same_as") or "")}
    return out


def meridian_code(catalog: "Catalog", key: str) -> tuple[str, int]:
    """(product code, Meridian items per one of ours); code is blank when not set.

    "code:R1616" is a Meridian code picked directly (school & other orders)."""
    if key.startswith("code:"):
        return key[5:], 1
    it = catalog.meridian_items.get(key) or {}
    if it.get("same_as") and not it.get("code"):
        base = catalog.meridian_items.get(it["same_as"]) or {}
        return str(base.get("code") or ""), int(it.get("per") or base.get("per") or 1)
    return str(it.get("code") or ""), int(it.get("per") or 1)


def roes_code(catalog: "Catalog", key: str) -> str:
    """Meridian's code for a lab item, following same_as; blank when not filled in yet."""
    it = catalog.roes_items.get(key) or {}
    if it.get("same_as") and not it.get("code"):
        return (catalog.roes_items.get(it["same_as"]) or {}).get("code", "")
    return it.get("code", "")


DEFAULT_ROES_ITEMS = {
    "8x10": {"name": "8 x 10", "code": ""}, "5x7": {"name": "5 x 7", "code": ""}, "4x6": {"name": "4 x 6", "code": ""},
    "wallet": {"name": "8 Wallets", "code": ""},
    "8x10-team": {"name": "8 x 10 (team, landscape)", "code": "", "same_as": "8x10"},
    "5x7-team": {"name": "5 x 7 (team, landscape)", "code": "", "same_as": "5x7"}, "misc-mini-wallets-8": {"name": "8 - Mini Wallets", "code": ""},
    "misc-wallet-magnets-4": {"name": "Wallet Magnets", "code": ""}, "misc-magnet-4x5": {"name": "4 x 5 Magnet", "code": ""},
    "misc-magnet-5x7": {"name": "5 x 7 Magnet", "code": ""}, "misc-photo-key-ring": {"name": "Key Chain", "code": ""},
    "misc-photo-badge": {"name": "Photo Badge", "code": ""},
}

DEFAULT_CROPS = {"individual": {"8x10": "8x10", "5x7": "5x7", "4x6": "4x6", "wallet": "2_5x3_5"},
                 "team": {"8x10": "10x8", "5x7": "7x5"}}


# --------------------------------------------------------------- pricing --

def normalize(lines, catalog: Catalog) -> list[dict]:
    """Drop zero/negative quantities and unknown products, merge duplicates, cap at MAX_QTY."""
    merged: dict[str, int] = {}
    for line in lines or []:
        try:
            qty = int(math.floor(float(line.get("qty") or 0)))
        except (TypeError, ValueError):
            continue
        pid = str(line.get("product_id") or "")
        if qty <= 0 or not catalog.get(pid):
            continue
        merged[pid] = min(MAX_QTY, merged.get(pid, 0) + qty)
    return [{"product_id": k, "qty": v} for k, v in merged.items()]


def calculate(lines, catalog: Catalog) -> dict:
    """The website's pricing rules.

    1. Any package unlocks the with-package price on every a la carte item.
    2. Remove the last package and a la carte goes back to full price.
    3. Keepsakes (misc) are one price whatever else is in the order.
    """
    norm = normalize(lines, catalog)
    has_package = any(catalog.get(l["product_id"]).type == "package" for l in norm)
    priced = []
    for l in norm:
        p = catalog.get(l["product_id"])
        standalone = p.price
        unit = p.with_package if (p.type == "alacarte" and has_package) else p.price
        priced.append({
            "product_id": p.id, "label": catalog.label_for(p.id), "type": p.type, "qty": l["qty"],
            "unit_cents": unit, "line_cents": unit * l["qty"], "discount": p.type == "alacarte" and has_package,
            "standalone_cents": standalone, "savings_cents": (standalone - unit) * l["qty"],
        })
    total = sum(x["line_cents"] for x in priced)
    return {"has_package": has_package, "lines": priced, "total_cents": total,
            "savings_cents": sum(x["savings_cents"] for x in priced), "item_count": sum(x["qty"] for x in priced)}


def order_summary(order: dict, catalog: Catalog) -> dict:
    """Totals plus what is still owed. Payment is due on picture day."""
    t = calculate(order.get("lines"), catalog)
    paid = int(order.get("paid_cents") or 0)
    # On a prepaid shoot an envelope with nothing typed in was paid in full on picture day.
    auto = bool(order.get("prepaid")) and paid == 0 and not (order.get("paid_method") or "")
    if auto:
        paid = t["total_cents"]
    pk = []
    for l in t["lines"]:
        p = catalog.get(l["product_id"])
        if p.type == "package":
            pk.append(p.letter + (f"×{l['qty']}" if l["qty"] > 1 else ""))
    extras = []
    for l in t["lines"]:
        if l["type"] != "package":
            name = short_label(catalog.get(l["product_id"]))
            extras.append(f"{l['qty']}× {name}" if l["qty"] > 1 else name)
    # Paid more than the total: the extra is change owed back, not money collected.
    change = max(0, paid - t["total_cents"])
    return {**t, "paid_cents": paid - change, "handed_cents": paid, "change_cents": change,
            "due_cents": max(0, t["total_cents"] - paid), "paid_auto": auto,
            "packages": " + ".join(pk), "extras": ", ".join(extras)}


def paid_label(order: dict, summary: dict | None = None) -> str:
    """How an envelope was paid, in words."""
    s = summary or order.get("summary") or {}
    if s.get("paid_auto"):
        return "Picture day"
    m = order.get("paid_method") or ""
    return "Not paid" if m in ("", "none") else m.title()


# ------------------------------------------------- prints (pull sheet) --

def to_order_units(size: str, count: int) -> int:
    sheet = PRINT_SIZES.get(size, {}).get("sheet")
    return math.ceil(count / sheet) if sheet else count


def print_columns(catalog: Catalog) -> list[tuple[str, str]]:
    """Every print size, largest first, with a Team column where one is sold."""
    sizes = sorted((k for k in PRINT_SIZES if k != MEMORY_MATE), key=lambda k: -PRINT_SIZES[k]["w"] * PRINT_SIZES[k]["h"])
    cols = []
    for k in sizes:
        s = PRINT_SIZES[k]
        cols.append((k, f"{s['label']} sheets ({s['sheet']} per sheet)" if s.get("sheet") else s["plural"]))
        if k == "5x7" or any(p.type == "alacarte" and p.team and p.size == k for p in catalog.products):
            cols.append((f"{k}:team", f"{s['label']} Team"))
    return cols


def expand(order: dict, catalog: Catalog) -> dict:
    """What one family's order comes to, in lab units.

    prints: {"5x7": 3, "5x7:team": 1, "wallet": 1 (sheets), ...}
    misc:   {product_id: packs}
    mates:  Memory Mates to assemble (each uses an individual 5x7 and a team 5x7)
    """
    prints: dict[str, int] = {}
    misc: dict[str, int] = {}
    mates = 0
    for l in normalize(order.get("lines"), catalog):
        p, q = catalog.get(l["product_id"]), l["qty"]
        if p.type == "package":
            for size, n in p.contents.items():
                if size == MEMORY_MATE:
                    mates += n * q
                    prints["5x7"] = prints.get("5x7", 0) + n * q
                    prints["5x7:team"] = prints.get("5x7:team", 0) + n * q
                else:
                    prints[size] = prints.get(size, 0) + n * q
        elif p.type == "alacarte":
            key = f"{p.size}:team" if p.team else p.size
            prints[key] = prints.get(key, 0) + p.unit * q
        else:
            misc[p.id] = misc.get(p.id, 0) + p.unit * q
    prints = {k: to_order_units(k.split(":")[0], v) for k, v in prints.items()}
    for pid, pieces in list(misc.items()):
        p = catalog.get(pid)
        misc[pid] = math.ceil(pieces / p.pack) if p.pack else pieces
    return {"prints": prints, "misc": misc, "mates": mates}


def _sort_key(o: dict):
    """Teams in the shoot's own order (team_rank, set when loaded), then A-Z; athletes A-Z."""
    return (int(o.get("team_rank", 10_000)), str(o.get("team") or "").lower(), str(o.get("athlete") or "").lower())


def team_ranks(orders: list[dict]) -> dict[str, int]:
    return {o.get("team") or "": int(o.get("team_rank", 10_000)) for o in orders}


def by_team_order(names, orders: list[dict]):
    """Team names in the shoot's own order; ones it doesn't know go last, A-Z."""
    r = team_ranks(orders)
    return sorted(names, key=lambda t: (t in ("", "No team"), r.get(t, 10_000), str(t).lower()))


def pull_sheet_csv(orders: list[dict], catalog: Catalog) -> str:
    cols = print_columns(catalog)
    misc = [p for p in catalog.products if p.type == "misc"]
    head = ["Envelope", "Team", "Athlete", "Coach", "Glasses", "Packages", "Memory Mates to make",
            *[c[1] for c in cols], *[f"{p.label} (set of {p.pack})" if p.pack else p.label for p in misc],
            "Frames shot", "Final pick", "Total", "Paid", "Due", "Parent", "Phone", "Notes"]
    rows = [head]
    for o in sorted(orders, key=_sort_key):
        e, s = expand(o, catalog), order_summary(o, catalog)
        blank = lambda n: str(n) if n else ""  # blank, not 0, so a printed sheet shows only what's needed
        rows.append([str(o.get("envelope") or ""), o.get("team") or "", o.get("athlete") or "", o.get("coach") or "",
                     "GLASSES" if o.get("glasses") else "", s["packages"], blank(e["mates"]),
                     *[blank(e["prints"].get(k, 0)) for k, _ in cols], *[blank(e["misc"].get(p.id, 0)) for p in misc],
                     o.get("frames") or "", o.get("edited") or o.get("image") or "",
                     money(s["total_cents"]), money(s["paid_cents"]), money(s["due_cents"]) if s["due_cents"] else "",
                     o.get("parent") or "", o.get("phone") or "", o.get("notes") or ""])
    # A totals row, so the bottom of the sheet is the lab order for the whole shoot.
    body = rows[1:]
    n_glasses = sum(1 for r in body if r[4])
    first = 7  # first print column
    tot = lambda i: str(sum(int(r[i]) for r in body if r[i])) if any(r[i] for r in body) else ""
    rows.append(["TOTAL", f"{len(body)} athlete{'s' if len(body) != 1 else ''}", "", "",
                 f"{n_glasses} in glasses" if n_glasses else "", "", tot(6),
                 *[tot(i) for i in range(first, first + len(cols) + len(misc))],
                 "", "", money(sum(cents(r[-6]) for r in body)), money(sum(cents(r[-5]) for r in body)),
                 money(sum(cents(r[-4] or 0) for r in body)), "", "", ""])
    return to_csv(rows)


def line_items_csv(orders: list[dict], catalog: Catalog) -> str:
    """One row per item bought, like the website's /admin export, for the books."""
    rows = [["Envelope", "Team", "Athlete", "Coach", "Item", "Qty", "Unit price", "Line total", "Paid by", "Parent", "Phone", "Email", "Notes"]]
    for o in sorted(orders, key=_sort_key):
        s = order_summary(o, catalog)
        for l in calculate(o.get("lines"), catalog)["lines"]:
            rows.append([str(o.get("envelope") or ""), o.get("team") or "", o.get("athlete") or "", o.get("coach") or "",
                         l["label"], str(l["qty"]), money(l["unit_cents"]), money(l["line_cents"]),
                         paid_label(o, s), o.get("parent") or "", o.get("phone") or "",
                         o.get("email") or "", o.get("notes") or ""])
    return to_csv(rows)


# ------------------------------------------------------------- crop list --

def frame_stem(name: str | None) -> str:
    n = str(name or "").strip()
    return re.sub(r"\.[^.\\/]+$", "", n.replace("\\", "/").split("/")[-1]) if n else ""


def needed_sizes(order: dict, catalog: Catalog) -> tuple[list[str], list[str], list[str]]:
    """(individual print sizes, team print sizes, keepsake crop sizes) this order needs cropped."""
    ind: set[str] = set()
    team: set[str] = set()
    keep: set[str] = set()
    for l in normalize(order.get("lines"), catalog):
        p = catalog.get(l["product_id"])
        if p.type == "package":
            for size in p.contents:
                if size == MEMORY_MATE:  # assembled from an individual 5x7 and a team 5x7
                    ind.add("5x7")
                    team.add("5x7")
                else:
                    ind.add(size)
        elif p.type == "alacarte":
            (team if p.team else ind).add(p.size)
        elif p.crop:
            keep.add(p.crop)
    by_area = lambda k: -PRINT_SIZES[k]["w"] * PRINT_SIZES[k]["h"]
    return sorted(ind, key=by_area), sorted(team, key=by_area), sorted(keep)


def crop_list(orders: list[dict], catalog: Catalog, team_photos: dict | None = None) -> dict:
    """Exactly which cropped files have to exist, and nothing more.

    Only what was bought is cropped (Package G needs one 5x7, not seven sizes),
    and team crops are made once per team however many kids ordered them.
    team_photos: {team name: group frame stem}.
    """
    team_photos = team_photos or {}
    teams: dict[str, dict[str, int]] = {}
    athletes = []
    for o in sorted(orders, key=_sort_key):
        frame = frame_stem(o.get("edited") or o.get("image"))
        ind, tm, keep = needed_sizes(o, catalog)
        jobs = [{"size": s, "crop": catalog.crop_individual.get(s, s), "label": PRINT_SIZES[s]["label"]} for s in ind]
        jobs += [{"size": c, "crop": c, "label": f"{c.replace('_', '.')} keepsake"} for c in keep
                 if c not in {j["crop"] for j in jobs}]
        for j in jobs:
            j["file"] = f"{frame}_{j['crop']}" if frame else ""
        for s in tm:
            t = teams.setdefault(o.get("team") or "", {})
            t[s] = t.get(s, 0) + 1
        athletes.append({"order_id": o.get("id"), "envelope": o.get("envelope"), "athlete": o.get("athlete") or "",
                         "team": o.get("team") or "", "frame": frame, "glasses": bool(o.get("glasses")), "jobs": jobs})
    team_list = []
    for name in by_team_order(teams, orders):
        frame = frame_stem(team_photos.get(name))
        sizes = [{"size": s, "crop": catalog.crop_team.get(s, s), "label": f"{PRINT_SIZES[s]['label']} Team",
                  "ordered_by": n} for s, n in sorted(teams[name].items(), key=lambda kv: -kv[1])]
        for s in sizes:
            s["file"] = f"{frame}_{s['crop']}" if frame else ""
        team_list.append({"team": name, "frame": frame, "sizes": sizes})
    return {"athletes": athletes, "teams": team_list}


def crop_list_csv(orders, catalog, team_photos=None) -> str:
    cl = crop_list(orders, catalog, team_photos)
    rows = [["Source", "Team", "Athlete", "Envelope", "Glasses", "Crop to", "File to make", "Note"]]
    for t in cl["teams"]:
        for s in t["sizes"]:
            rows.append(["TEAM PHOTO", t["team"], "", "", "", s["label"], s["file"],
                         f"Crop once — {s['ordered_by']} {'order needs' if s['ordered_by'] == 1 else 'orders need'} it"
                         if t["frame"] else "No team photo picked yet"])
    for a in cl["athletes"]:
        for j in a["jobs"]:
            rows.append(["INDIVIDUAL", a["team"], a["athlete"], str(a["envelope"] or ""), "GLASSES" if a["glasses"] else "",
                         j["label"], j["file"], "" if a["frame"] else "No photo picked yet"])
    return to_csv(rows)


# ----------------------------------------------------------- lab order --

def lab_plan(orders: list[dict], catalog: Catalog, team_photos: dict | None = None,
             extras: list[dict] | None = None) -> dict:
    """Every file the lab prints, with how many of each, grouped by print size.

    Quantities are in lab units: one wallet sheet, one 4x6 print. A team 5x7 is
    one file printed as many times as there are Memory Mates and team 5x7s.
    """
    team_photos = team_photos or {}
    items: dict[tuple, dict] = {}

    def add(group, crop, file, qty, who, label, why="", item=""):
        if qty <= 0:
            return
        key = (group, file or f"?{who}")
        it = items.setdefault(key, {"group": group, "crop": crop, "label": label, "file": file, "qty": 0, "for": [],
                                    "item": item,
                                    "why": why or ("" if file else "no photo picked")})
        it["qty"] += qty
        if who not in it["for"]:
            it["for"].append(who)

    for o in orders:
        frame = frame_stem(o.get("edited") or o.get("image"))
        who = o.get("athlete") or f"Envelope {o.get('envelope') or '?'}"
        e = expand(o, catalog)
        for key, qty in e["prints"].items():
            size, _, team = key.partition(":")
            if team:
                tname = o.get("team") or ""
                tframe = frame_stem(team_photos.get(tname))
                crop = catalog.crop_team.get(size, size)
                add(f"{PRINT_SIZES[size]['label']} Team", crop, f"{tframe}_{crop}" if tframe else "", qty,
                    f"{tname} team" if tframe else f"{tname} team (no group photo picked)", f"{PRINT_SIZES[size]['label']} Team",
                    item=f"{size}-team")
            else:
                crop = catalog.crop_individual.get(size, size)
                label = f"{PRINT_SIZES[size]['label']} sheet" if PRINT_SIZES[size].get("sheet") else PRINT_SIZES[size]["label"]
                add(PRINT_SIZES[size]["label"], crop, f"{frame}_{crop}" if frame else "", qty, who, label, item=size)
        # Keepsakes go to the lab as the units bought: one "8 Mini Wallets" is one item to print.
        for l in normalize(o.get("lines"), catalog):
            p = catalog.get(l["product_id"])
            if p.type == "misc":
                why = "" if p.crop or not frame else "no crop size set for it (Prices…)"
                add(p.label, p.crop, f"{frame}_{p.crop}" if (frame and p.crop) else "", l["qty"], who, p.label, why, item=p.id)
    if extras:  # school & other orders (not on any envelope)
        from . import extras as X
        X.add_to_plan(add, extras, team_photos)
    groups: dict[str, list] = {}
    for it in items.values():
        groups.setdefault(it["group"], []).append(it)
    order = ["16x20", "11x14"] + [PRINT_SIZES[k]["label"] for k in ("8x10", "5x7", "4x6", "wallet")]
    out = []
    for g in sorted(groups, key=lambda g: (order.index(g) if g in order else 50 + ("Team" in g), g)):
        rows = sorted(groups[g], key=lambda it: (not it["file"], it["file"].lower()))
        out.append({"group": g, "items": rows, "files": sum(1 for r in rows if r["file"]),
                    "qty": sum(r["qty"] for r in rows)})
    return {"groups": out}


def find_crops(crops_dir: Path, stems: set[str]) -> dict[str, Path]:
    """Map lower-cased 'IMG_5371_5x7' -> the file Crop wrote, searching the folder tree once."""
    want = {s.lower() for s in stems if s}
    found: dict[str, Path] = {}
    if not want or not Path(crops_dir).is_dir():
        return found
    # Prefer the flat Orders folder Crop writes, then anywhere below.
    for p in sorted(Path(crops_dir).rglob("*"), key=lambda p: (p.parent.name.lower() != "orders", len(p.parts))):
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
            k = p.stem.lower()
            if k in want and k not in found:
                found[k] = p
    return found


def safe_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]+', "-", str(s or ""))).strip() or "Untitled"


def build_lab_folder(plan: dict, crops_dir: Path, out_dir: Path, one_per_print: bool) -> dict:
    """Copy just the files the lab needs into out_dir/<size>/ plus lab-order.csv.

    one_per_print: two 4x6s of a photo become two files (…_1, …_2), so the
    Meridian website can take a whole size folder with every quantity at 1.
    Otherwise each file is copied once and the quantity is in lab-order.csv.
    """
    import shutil
    stems = {it["file"] for g in plan["groups"] for it in g["items"] if it["file"]}
    found = find_crops(Path(crops_dir), stems)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [["Print size", "File", "Qty", "For", "Copied as"]]
    missing, copied = [], 0
    for g in plan["groups"]:
        sub = out_dir / safe_name(g["group"])
        for it in g["items"]:
            src = found.get(it["file"].lower()) if it["file"] else None
            names = []
            if src:
                sub.mkdir(parents=True, exist_ok=True)
                if one_per_print and it["qty"] > 1:
                    for i in range(1, it["qty"] + 1):
                        dst = sub / f"{src.stem}_{i}{src.suffix}"
                        shutil.copy2(src, dst)
                        names.append(dst.name)
                else:
                    dst = sub / src.name
                    shutil.copy2(src, dst)
                    names.append(dst.name)
                copied += len(names)
            else:
                missing.append({"group": g["group"], "file": it["file"], "for": it["for"], "qty": it["qty"],
                                "why": it["why"] if not it["file"] else "not found in the crops folder"})
            rows.append([g["group"], it["file"] or f"({it['why']})", str(it["qty"]), "; ".join(it["for"]),
                         " ".join(names) if names else "MISSING"])
    (out_dir / "lab-order.csv").write_text(to_csv(rows), encoding="utf-8")
    return {"out_dir": str(out_dir), "copied": copied, "missing": missing, "csv": str(out_dir / "lab-order.csv")}


# ------------------------------------------------------------------ ROES --

def lab_items(order: dict, catalog: Catalog) -> list[tuple[str, int]]:
    """What one envelope is at the lab: individual prints, never packages.

    Package F -> [("5x7", 1), ("4x6", 2)]. Wallets are sheets of 8, a Memory Mate
    is an individual 5x7 plus a team 5x7, keepsakes are the units bought.
    """
    e = expand(order, catalog)
    items = [(k.replace(":team", "-team"), q) for k, q in e["prints"].items() if q]
    for l in normalize(order.get("lines"), catalog):
        if catalog.get(l["product_id"]).type == "misc":
            items.append((l["product_id"], l["qty"]))
    rank = ["8x10", "5x7", "4x6", "wallet", "8x10-team", "5x7-team"]
    return sorted(items, key=lambda kv: (rank.index(kv[0]) if kv[0] in rank else len(rank), kv[0]))


def unmapped_roes(catalog: Catalog) -> list[str]:
    """ROES items (that something in prices.yaml can order) still without Meridian's code."""
    used = {"8x10", "5x7", "4x6", "wallet"} | {f"{s}-team" for s in catalog.crop_team} | \
           {p.id for p in catalog.products if p.type == "misc"}
    return [catalog.roes_items.get(k, {"name": k})["name"] for k in sorted(used)
            if not (catalog.roes_items.get(k) or {}).get("same_as") and not roes_code(catalog, k)]


def with_ext(name: str) -> str:
    """ROES finds images by file name. Frames are kept without an extension, and
    Windows matches IMG_5371.jpg to IMG_5371.JPG, so .jpg is added when missing."""
    return name if not name or re.search(r"\.[A-Za-z0-9]{2,4}$", name) else name + ".jpg"


def roes_csv(orders: list[dict], catalog: Catalog, team_photos: dict | None = None) -> str:
    """A ROES Events import: one row per athlete, so ROES packs each kid's prints in one envelope.

    CustID, IndivImage, GroupIMG, Package is ROES's documented minimum. The
    Package cell lists the envelope's individual prints (packages are worked out
    here, not at the lab), separated by the delimiter in prices.yaml; two of a
    print repeats it, because ROES has no quantity column.
    """
    team_photos = team_photos or {}
    rows = [["CustID", "IndivImage", "GroupIMG", "Package", "First Name", "Last Name", "Team", "Coach", "Envelope"]]
    for o in sorted(orders, key=_sort_key):
        codes = []
        for key, qty in lab_items(o, catalog):
            it = catalog.roes_items.get(key) or {"name": key}
            codes += [roes_code(catalog, key) or it["name"]] * qty
        first, _, last = (o.get("athlete") or "").strip().partition(" ")
        image = with_ext((o.get("edited") or o.get("image") or "").strip())
        group = with_ext((team_photos.get(o.get("team") or "") or "").strip())
        rows.append([f"E{o.get('envelope') or o.get('id')}", image, group, catalog.roes_delimiter.join(codes),
                     first, last.strip(), o.get("team") or "", o.get("coach") or "", str(o.get("envelope") or "")])
    return to_csv(rows)


# --------------------------------------------- website CSV import --

def parse_web_csv(text: str, catalog: Catalog) -> tuple[list[dict], list[str]]:
    """Orders from the website's /admin CSV (one row per line item), grouped by Order #."""
    text = text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    need = {"Team", "Athlete", "Item", "Qty", "Order #"}
    if not reader.fieldnames or not need.issubset(set(reader.fieldnames)):
        raise ValueError("This doesn't look like the website's order export (needs Team, Athlete, Item, Qty and Order # columns).")
    by_label = {}
    for p in catalog.products:
        by_label[p.label.lower()] = p.id
        by_label[catalog.label_for(p.id).lower()] = p.id
        by_label[catalog.label_for(p.id).replace("—", "-").lower()] = p.id
    orders: dict[str, dict] = {}
    problems: list[str] = []
    for row in reader:
        num = (row.get("Order #") or "").strip()
        if not num:
            continue
        o = orders.setdefault(num, {
            "web_order": num, "athlete": (row.get("Athlete") or "").strip(), "team": (row.get("Team") or "").strip(),
            "coach": (row.get("Coach") or "").strip(), "parent": (row.get("Parent") or "").strip(),
            "phone": (row.get("Phone") or "").strip(), "email": (row.get("Email") or "").strip(),
            "notes": (row.get("Notes") or "").strip(), "lines": [], "paid_cents": 0,
            "paid_method": "" if (row.get("Paid") or "").strip() in ("", "Not paid") else "card",
        })
        item = (row.get("Item") or "").strip()
        pid = by_label.get(item.lower()) or by_label.get(item.replace("—", "-").lower())
        if not pid:
            problems.append(f"Order {num}: '{item}' isn't in prices.yaml and was left out.")
            continue
        try:
            qty = int(row.get("Qty") or 0)
        except ValueError:
            qty = 0
        o["lines"].append({"product_id": pid, "qty": qty})
        if o["paid_method"]:
            o["paid_cents"] += cents(row.get("Line total") or 0)
    return list(orders.values()), problems


# ----------------------------------------------------------------- utils --

def to_csv(rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for r in rows:
        w.writerow(["" if v is None else str(v) for v in r])
    return "﻿" + buf.getvalue()  # the BOM makes Excel read UTF-8


# The packet's prices, used when prices.yaml is missing or broken. Kept identical
# to the shipped prices.yaml (a test checks it).
DEFAULT_PRICES = r"""# Keeper Studio — what Jamie Bexten Photography sells.
#
# Transcribed from the printed picture-day packet. The Orders tab reads every
# price from this file, so a price change each season is an edit here and
# nowhere else. Your copy lives in %LOCALAPPDATA%\KeeperStudio\prices.yaml
# (Orders > Prices… opens it) and is kept when you update the app; this file
# in the repository is the starting copy.
#
# Prices are in dollars. Sizes are: 8x10, 5x7, 4x6, wallet, memory-mate.
# A Memory Mate is assembled here from a team 5x7 and an individual 5x7.

packages:
  - {id: pkg-a, letter: A, name: Package A, price: 40.00, badge: "Best Value!",
     contents: {8x10: 1, memory-mate: 1, 5x7: 2, 4x6: 2, wallet: 8}}
  - {id: pkg-b, letter: B, name: Package B, price: 35.00,
     contents: {memory-mate: 1, 5x7: 2, 4x6: 2, wallet: 8}}
  - {id: pkg-c, letter: C, name: Package C, price: 30.00,
     contents: {memory-mate: 1, 5x7: 1, 4x6: 1, wallet: 8}}
  - {id: pkg-d, letter: D, name: Package D, price: 25.00,
     contents: {memory-mate: 1, 5x7: 1, 4x6: 1}}
  - {id: pkg-e, letter: E, name: Package E, price: 20.00,
     contents: {5x7: 1, 4x6: 1, wallet: 8}}
  - {id: pkg-f, letter: F, name: Package F, price: 18.00,
     contents: {5x7: 1, 4x6: 2}}
  - {id: pkg-g, letter: G, name: Package G, price: 15.00,
     contents: {memory-mate: 1}}

# A la carte: the lower price applies only when the order has a package.
# unit: how many prints one unit is ("3 - 4x6" is 3 prints).
alacarte:
  - {id: ac-8x10,      label: 8x10,      size: 8x10,   unit: 1, price: 15.00, with_package: 10.00}
  - {id: ac-8x10-team, label: 8x10 Team, size: 8x10,   unit: 1, price: 15.00, with_package: 10.00, team: true}
  - {id: ac-5x7,       label: 5x7,       size: 5x7,    unit: 1, price: 10.00, with_package: 8.00}
  - {id: ac-5x7-team,  label: 5x7 Team,  size: 5x7,    unit: 1, price: 10.00, with_package: 8.00, team: true}
  - {id: ac-4x6-3,     label: 4x6,       size: 4x6,    unit: 3, price: 12.00, with_package: 8.00}
  - {id: ac-wallets-8, label: Wallets,   size: wallet, unit: 8, price: 12.00, with_package: 8.00}

# Keepsakes: one price, never discounted. pack: how many come in one lab pack.
# crop: the Crop size the keepsake is printed from (a size name from
# config.yaml, e.g. 4x5 or 2_5x3_5). A blank crop lists the keepsake in the
# lab order without a file.
misc:
  - {id: misc-mini-wallets-8,   label: Mini Wallets,   unit: 8, price: 6.00,  crop: 1_7x2_2}
  - {id: misc-wallet-magnets-4, label: Wallet Magnets, unit: 4, price: 10.00, pack: 4, crop: 2_5x3_5}
  - {id: misc-magnet-4x5,       label: 4x5 Magnet,     unit: 1, price: 7.00,  crop: 4x5}
  - {id: misc-magnet-5x7,       label: 5x7 Magnet,     unit: 1, price: 10.00, crop: 5x7}
  - {id: misc-photo-key-ring,   label: Photo Key Ring, unit: 1, price: 6.00,  crop: 1_8x2_8}
  - {id: misc-photo-badge,      label: Photo Badge,    unit: 1, price: 6.00,  crop: 3_5x3_5}

# Which Crop size each print is cut to. Names match the folders and file
# suffixes Crop > Export prints writes (IMG_5371_5x7.JPG, IMG_5373_7x5.JPG).
crop_sizes:
  individual: {8x10: 8x10, 5x7: 5x7, 4x6: 4x6, wallet: 2_5x3_5}
  team:       {8x10: 10x8, 5x7: 7x5}

# ROES event import (Orders > Export > ROES file). Packages are never sent to
# the lab: each envelope goes over as the individual prints it comes to (Package F
# = one 5x7 and two 4x6), the same items as the Sports group in Meridian's ROES.
# name: the ROES item it is. code: the single-item package set up in ROES for
# it (Jamie's codes: 8x10, 5x7, 4x6, WAL, MWAL, MAG57, MAG45, MAGW, BADGE, KEY). same_as: the
# team prints are the same ROES item as the individual size, printed landscape
# from the group photo's 10x8 / 7x5 crop, so they use that size's code. A guessed code
# silently orders the wrong product, so a blank code exports the name instead and
# the ROES button shows a warning until every code is filled in.
roes:
  delimiter: ";"
  items:
    8x10:                  {name: "8 x 10",              code: "8x10"}
    5x7:                   {name: "5 x 7",               code: "5x7"}
    4x6:                   {name: "4 x 6",               code: "4x6"}
    wallet:                {name: "8 Wallets",           code: "WAL"}
    8x10-team:             {name: "8 x 10 (team, landscape)", same_as: 8x10}
    5x7-team:              {name: "5 x 7 (team, landscape)",  same_as: 5x7}
    misc-mini-wallets-8:   {name: "8 - Mini Wallets",    code: "MWAL"}
    misc-wallet-magnets-4: {name: "Wallet Magnets",      code: "MAGW"}
    misc-magnet-4x5:       {name: "4 x 5 Magnet",        code: "MAG45"}
    misc-magnet-5x7:       {name: "5 x 7 Magnet",        code: "MAG57"}
    misc-photo-key-ring:   {name: "Key Chain",           code: "KEY"}
    misc-photo-badge:      {name: "Photo Badge",         code: "BADGE"}

# Meridian bulk order CSV (Orders > Lab order > Meridian bulk order). The codes
# come from Meridian's product list (keeperstudio/meridian/products.csv). per
# (optional): how many Meridian items one of ours is. Leave a code blank for
# something with no bulk-upload product yet; Lab order lists those so you can
# order them on the website.
meridian:
  items:
    8x10:                  {code: R1680A}
    5x7:                   {code: RA1657}
    4x6:                   {code: R1646}
    wallet:                {code: PKG-8-Wallets}
    8x10-team:             {same_as: 8x10}
    5x7-team:              {same_as: 5x7}
    misc-magnet-4x5:       {code: MAG45}
    misc-magnet-5x7:       {code: MAG57}
    misc-mini-wallets-8:   {code: R1688}
    misc-wallet-magnets-4: {code: RA78B}
    misc-photo-key-ring:   {code: R606-2}
    misc-photo-badge:      {code: R73}
"""
