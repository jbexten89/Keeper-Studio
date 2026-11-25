"""Server endpoints for the Orders tab. Registered into server.ROUTES."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import meridian as M
from . import reports as R
from . import orders as O
from . import paths
from .orderbook import OrderBook

book: OrderBook | None = None
_cat: tuple[float, O.Catalog] | None = None


def prices_path() -> Path:
    """The user's prices live with their catalog in app data, so app updates never reset them."""
    p = paths.data_dir() / "prices.yaml"
    if not p.exists():
        try:
            p.write_text(O.DEFAULT_PRICES, encoding="utf-8")
        except OSError:
            pass
    return p


def catalog() -> O.Catalog:
    """prices.yaml, re-read whenever the file changes so an edit shows up without a restart."""
    global _cat
    p = prices_path()
    try:
        m = p.stat().st_mtime
    except OSError:
        m = -1.0
    if _cat is None or _cat[0] != m:
        _cat = (m, O.load_catalog(p))
    return _cat[1]


def start() -> None:
    global book
    if book is None:
        book = OrderBook(paths.data_dir() / "orders.sqlite3", paths.data_dir() / "backups")


def _decorate(o: dict, cat: O.Catalog) -> dict:
    o = dict(o)
    o["summary"] = O.order_summary(o, cat)
    _add_lab_cost(o["summary"], o, cat)
    return o


def _add_lab_cost(summary: dict, order: dict, cat: O.Catalog) -> None:
    """Meridian's estimated cost of the envelope, and what's left after it."""
    try:
        c = M.order_cost_cents(order, cat)
    except Exception:  # noqa: BLE001 - an estimate must never break the order list
        c = {"cents": 0, "unpriced": ["?"]}
    summary["lab_cents"] = c["cents"]
    summary["lab_unpriced"] = c["unpriced"]
    summary["keep_cents"] = summary["total_cents"] - c["cents"]


def _team_photos(sid: int) -> dict[str, str]:
    return {t: v["image"] for t, v in book.team_photos(sid).items() if v.get("image")}


def r_catalog(b):
    return {"catalog": catalog().to_json(), "prices_path": str(prices_path())}


def r_shoots(b):
    return {"shoots": book.shoots()}


def r_shoot_save(b):
    return {"shoot": book.save_shoot(b.get("shoot") or {}), "shoots": book.shoots()}


def r_shoot_delete(b):
    book.delete_shoot(int(b["id"]))
    return {"shoots": book.shoots()}


def r_list(b):
    sid = int(b["shoot_id"])
    cat = catalog()
    rows = [_decorate(o, cat) for o in book.orders(sid)]
    total = sum(o["summary"]["total_cents"] for o in rows)
    paid = sum(o["summary"]["paid_cents"] for o in rows)
    lab = sum(o["summary"]["lab_cents"] for o in rows)
    shoot = next((x for x in book.shoots() if x["id"] == sid), {})
    ship = int(shoot.get("shipping_cents") or 0)
    keep = total - lab - ship
    photos = book.team_photos(sid)
    teams = sorted({o["team"] for o in rows if o["team"]} | set(photos), key=str.lower)
    return {
        "orders": rows, "next_envelope": book.next_envelope(sid),
        "teams": [{"name": t, "image": (photos.get(t) or {}).get("image", ""),
                   "count": sum(1 for o in rows if o["team"] == t)} for t in teams],
        "coaches": sorted({o["coach"] for o in rows if o["coach"]}, key=str.lower),
        "totals": {"orders": len(rows), "total_cents": total, "paid_cents": paid, "due_cents": total - paid,
                   "lab_cents": lab, "shipping_cents": ship, "keep_cents": keep,
                   "profit_pct": round(100 * keep / total, 1) if total else None,
                   "unpaid": sum(1 for o in rows if o["summary"]["due_cents"] > 0),
                   "no_photo": sum(1 for o in rows if not (o["image"] or o["edited"]) and o["lines"]),
                   "glasses": sum(1 for o in rows if o["glasses"])},
    }


def r_shipping(b):
    try:
        c = O.cents(b.get("amount") or 0)
    except Exception:  # noqa: BLE001 - anything that isn't an amount
        raise ValueError("Type the shipping as an amount, like 12.50.") from None
    if c < 0:
        raise ValueError("Shipping can't be negative.")
    book.set_shipping(int(b["shoot_id"]), c)
    return {"ok": True}


def r_save(b):
    sid = int(b["shoot_id"])
    o = book.save_order(sid, b.get("order") or {})
    return {"order": _decorate(o, catalog())}


def r_bulk(b):
    return {"changed": book.bulk_update(int(b["shoot_id"]), b.get("ids") or [], b.get("fields") or {})}


def r_delete(b):
    return {"deleted": book.delete_order(int(b["id"]))}


def r_restore(b):
    return {"order": _decorate(book.restore_order(b["order"]), catalog())}


def r_team_photo(b):
    book.set_team_photo(int(b["shoot_id"]), str(b["team"]), str(b.get("image") or ""))
    return {"ok": True}


def r_rename_team(b):
    return {"changed": book.rename_team(int(b["shoot_id"]), str(b["old"]), str(b["new"]))}


def r_price(b):
    """Live total for the editor, priced by the same code that prices saved orders."""
    cat = catalog()
    o = {"lines": b.get("lines") or [], "paid_cents": b.get("paid_cents") or 0, "team": b.get("team") or ""}
    summary = O.order_summary(o, cat)
    _add_lab_cost(summary, o, cat)
    return {"summary": summary}


EXPORTS = {
    "pull": ("pull sheet", lambda os_, c, tp: O.pull_sheet_csv(os_, c)),
    "crop": ("crop list", lambda os_, c, tp: O.crop_list_csv(os_, c, tp)),
    "roes": ("ROES import", lambda os_, c, tp: O.roes_csv(os_, c, tp)),
    "items": ("orders", lambda os_, c, tp: O.line_items_csv(os_, c)),
}


def _export_text(b) -> str:
    sid, kind = int(b["shoot_id"]), b["kind"]
    if kind not in EXPORTS:
        raise ValueError("Unknown export.")
    rows = book.orders(sid)
    if b.get("team"):
        rows = [o for o in rows if o["team"] == b["team"]]
    return EXPORTS[kind][1](rows, catalog(), _team_photos(sid))


def _report_titles(b) -> tuple[str, str]:
    s = next((x for x in book.shoots() if x["id"] == int(b["shoot_id"])), {})
    bits = [s.get("name") or "Shoot"]
    if s.get("date"):
        try:
            import datetime as dt
            bits.append(dt.date.fromisoformat(s["date"]).strftime("%b %d, %Y").replace(" 0", " "))
        except ValueError:
            bits.append(s["date"])
    if b.get("team"):
        bits.append(f"{b['team']} only")
    return R.TITLES[b["kind"]], " · ".join(bits)


def r_report(b):
    """The export as a formatted table, for the preview."""
    title, subtitle = _report_titles(b)
    return {"title": title, "subtitle": subtitle, **R.table(_export_text(b), b["kind"])}


def r_export(b):
    kind, dest = b["kind"], b["path"]
    text = _export_text(b)
    if b.get("format") == "pdf" or str(dest).lower().endswith(".pdf"):
        title, subtitle = _report_titles(b)
        out = R.pdf(R.table(text, kind), Path(dest), title, subtitle)
        return {"path": str(out), "unmapped": []}
    dest = Path(dest)
    if dest.suffix.lower() != ".csv":
        dest = dest.with_suffix(".csv")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return {"path": str(dest), "unmapped": O.unmapped_roes(catalog()) if kind == "roes" else []}


def export_name(shoot: dict, kind: str) -> str:
    return f"{O.safe_name(shoot.get('name') or 'Shoot')} - {EXPORTS[kind][0]}.csv"


def r_export_name(b):
    s = next((x for x in book.shoots() if x["id"] == int(b["shoot_id"])), {})
    return {"filename": export_name(s, b["kind"])}


def r_crop_list(b):
    sid = int(b["shoot_id"])
    rows = book.orders(sid)
    return O.crop_list(rows, catalog(), _team_photos(sid))


def r_lab_plan(b):
    sid = int(b["shoot_id"])
    rows = [o for o in book.orders(sid) if o["lines"]]
    plan = O.lab_plan(rows, catalog(), _team_photos(sid))
    crops = b.get("crops_dir") or ""
    stems = {it["file"] for g in plan["groups"] for it in g["items"] if it["file"]}
    found = O.find_crops(Path(crops), stems) if crops else {}
    for g in plan["groups"]:
        for it in g["items"]:
            it["found"] = str(found[it["file"].lower()]) if it["file"] and it["file"].lower() in found else ""
    plan["crops_dir"] = crops
    plan["crops_exists"] = bool(crops) and Path(crops).is_dir()
    cat = catalog()
    for g in plan["groups"]:
        for it in g["items"]:
            code, per = O.meridian_code(cat, it.get("item") or "")
            it["mcode"], it["mname"], it["mqty"] = code, M.product_name(code), it["qty"] * per
    plan["meridian"] = meridian_settings()
    return plan


def _meridian_path() -> Path:
    return paths.data_dir() / "meridian.json"


def meridian_settings() -> dict:
    import json
    try:
        got = json.loads(_meridian_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = {}
    return {**M.DEFAULT_SETTINGS, **{k: v for k, v in got.items() if k in M.DEFAULT_SETTINGS}}


def r_meridian_settings(b):
    import json
    s = meridian_settings()
    for k in M.DEFAULT_SETTINGS:
        if k in b:
            s[k] = str(b[k]).strip()
    _meridian_path().write_text(json.dumps(s, indent=2), encoding="utf-8")
    return {"settings": s, "problems": M.settings_problems(s)}


def r_meridian_build(b):
    sid = int(b["shoot_id"])
    rows = [o for o in book.orders(sid) if o["lines"]]
    plan = O.lab_plan(rows, catalog(), _team_photos(sid))
    if not Path(b["crops_dir"]).is_dir():
        raise FileNotFoundError(f"Crops folder not found: {b['crops_dir']}")
    s = meridian_settings()
    bad = M.settings_problems(s)
    if bad:
        raise ValueError(" ".join(bad))
    shoot = next((x for x in book.shoots() if x["id"] == sid), {})
    name = str(b.get("order_name") or shoot.get("name") or "Picture day")
    return M.build(plan, catalog(), Path(b["crops_dir"]), Path(b["out_dir"]), s, name)


def r_lab_build(b):
    sid = int(b["shoot_id"])
    rows = [o for o in book.orders(sid) if o["lines"]]
    plan = O.lab_plan(rows, catalog(), _team_photos(sid))
    if not Path(b["crops_dir"]).is_dir():
        raise FileNotFoundError(f"Crops folder not found: {b['crops_dir']}")
    return O.build_lab_folder(plan, Path(b["crops_dir"]), Path(b["out_dir"]), bool(b.get("one_per_print")))


def r_import_web(b):
    sid = int(b["shoot_id"])
    text = Path(b["path"]).read_text(encoding="utf-8-sig")
    got, problems = O.parse_web_csv(text, catalog())
    have = {o["web_order"] for o in book.orders(sid) if o["web_order"]}
    added = skipped = 0
    for o in got:
        if o["web_order"] in have:
            skipped += 1
            continue
        o["envelope"] = book.next_envelope(sid)
        book.save_order(sid, o)
        added += 1
    return {"added": added, "skipped": skipped, "problems": problems}


def r_open_prices(b):
    p = prices_path()
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # type: ignore[attr-defined]
    return {"path": str(p)}


ROUTES = {
    "/api/orders/catalog": r_catalog, "/api/orders/shoots": r_shoots,
    "/api/orders/shoot/save": r_shoot_save, "/api/orders/shoot/delete": r_shoot_delete,
    "/api/orders/list": r_list, "/api/orders/save": r_save, "/api/orders/delete": r_delete, "/api/orders/bulk": r_bulk,
    "/api/orders/restore": r_restore, "/api/orders/team-photo": r_team_photo,
    "/api/orders/rename-team": r_rename_team, "/api/orders/price": r_price,
    "/api/orders/export": r_export, "/api/orders/export-name": r_export_name,
    "/api/orders/crop-list": r_crop_list, "/api/orders/lab-plan": r_lab_plan, "/api/orders/lab-build": r_lab_build,
    "/api/orders/import-web": r_import_web, "/api/orders/open-prices": r_open_prices,
    "/api/orders/report": r_report, "/api/orders/shipping": r_shipping, "/api/orders/meridian-settings": r_meridian_settings, "/api/orders/meridian-build": r_meridian_build,
}
