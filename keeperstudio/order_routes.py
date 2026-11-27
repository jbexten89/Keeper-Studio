"""Server endpoints for the Orders tab. Registered into server.ROUTES."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import analysis as A
from . import extras as X
from . import meridian as M
from . import reports as R
from . import orders as O
from . import school as SC
from . import jobs
from . import paths
from . import shootfile as SF
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


def _open_book():
    start()
    return book


def _close_book() -> None:
    global book
    if book is not None:
        book.close()
        book = None


def on_app_close() -> None:
    """The app is closing: save any pending folder files and back up the order book."""
    try:
        SF.writer.flush()
        if book is not None:
            SF.backup_now(book, "close")
    except Exception:  # noqa: BLE001 - never block closing
        pass


# ------------------------------------------------ keeping orders safe (idea 5) --
def r_backups(b):
    return SF.list_backups()


def r_backup_now(b):
    return SF.backup_now(book, "manual")


def r_backup_second(b):
    folder = str(b.get("folder") or "").strip()
    if folder and not Path(folder).is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    SF.save_settings({"second": folder})
    return {**SF.list_backups(), **({"made": SF.backup_now(book, "manual")} if folder else {})}


def r_backup_restore(b):
    r = SF.restore(_open_book, _close_book, str(b.get("name") or ""))
    return r


def r_folder_link(b):
    """Remember which photo folder a shoot's photos are in, and save its orders file there."""
    sid, folder = int(b["shoot_id"]), str(b.get("folder") or "")
    if folder and not Path(folder).is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if folder:  # never write over another shoot's orders file that this computer still has
        have = SF.read_folder_file(folder)
        mine = (book.shoot(sid) or {}).get("uid")
        other_uid = ((have or {}).get("shoot") or {}).get("uid")
        if other_uid and other_uid != mine:
            other = book.shoot_by_uid(other_uid)
            if other and other["id"] != sid:
                raise ValueError(f"That folder already keeps the orders for {other['name']}.")
    book.set_folder(sid, folder)
    path = SF.write_folder_file(book, sid) if folder else None
    return {"ok": True, "file": str(path) if path else ""}


def r_folder_status(b):
    return SF.folder_status(book, str(b.get("folder") or ""))


def r_folder_import(b):
    """Bring in the orders saved in a photo folder: a new shoot, or newer orders for one that's here."""
    folder = str(b.get("folder") or "")
    d = SF.read_folder_file(folder)
    if not d:
        raise FileNotFoundError("There's no orders file in that folder.")
    st = SF.folder_status(book, folder)
    if st.get("state") == "newer":
        SF.backup_now(book, "manual")  # so the orders being replaced can be got back
        sid = book.import_shoot(d, replace_sid=st["shoot_id"])
    elif st.get("state") == "new":
        sid = book.import_shoot(d)
    else:
        sid = st["shoot_id"]
    book.set_folder(sid, folder)
    return {"shoot_id": sid, "state": st.get("state")}


_MUTATING = {"/api/orders/shoot/save", "/api/orders/save", "/api/orders/delete", "/api/orders/bulk", "/api/orders/bulk-pay",
             "/api/orders/restore", "/api/orders/team-photo", "/api/orders/rename-team", "/api/orders/team-order",
             "/api/orders/extra/save", "/api/orders/extra/delete", "/api/orders/extras-copy", "/api/orders/shipping",
             "/api/orders/import-web", "/api/orders/shoot-hours", "/api/orders/team-drop", "/api/orders/team-list-save", "/api/orders/school-set", "/api/orders/school-send", "/api/orders/school-mark-sent", "/api/orders/school-gmail"}


def _after_change(fn):
    """Note the change and save the shoot's folder file a few seconds later."""
    def run(b):
        out = fn(b)
        try:
            sid = (b or {}).get("shoot_id") or (out.get("shoot_id") if isinstance(out, dict) else None)
            if not sid and isinstance(out, dict) and isinstance(out.get("shoot"), dict):  # shoot/save answers with the shoot
                sid = out["shoot"].get("id")
            if sid:
                book.touch(int(sid))
                SF.writer.touch(book, int(sid))
            else:  # shoot not named (e.g. a delete by envelope id): refresh every linked shoot's file
                for sh in book.shoots():
                    if sh.get("folder"):
                        SF.writer.touch(book, sh["id"])
        except Exception:  # noqa: BLE001 - keeping the copy must never break saving
            pass
        return out
    return run


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
    photos = book.team_photos(sid)
    ex = X.totals(book.extras(sid), _team_photos(sid))
    fam_total = total
    total += ex["sales_cents"]
    paid += ex["paid_cents"]
    lab += ex["lab_cents"]
    keep = total - lab - ship
    teams = book.team_list(sid)
    return {
        "orders": rows, "next_envelope": book.next_envelope(sid),
        # every team on the shoot's list: in use, or carried from last year and not used yet ("planned")
        "teams": [{"name": t["name"], "image": (photos.get(t["name"]) or {}).get("image", ""), "coach": t["coach"],
                   "planned": not t["live"], "count": sum(1 for o in rows if o["team"] == t["name"])} for t in teams],
        "coaches": sorted({o["coach"] for o in rows if o["coach"]}, key=str.lower),
        "school": _school_status(sid, photos),
        "totals": {"orders": len(rows), "family_cents": fam_total, "extras": ex, "total_cents": total, "paid_cents": paid, "due_cents": total - paid,
                   "change_cents": sum(o["summary"].get("change_cents", 0) for o in rows),
                   "change_n": sum(1 for o in rows if o["summary"].get("change_cents")),
                   "short_cents": sum(o["summary"].get("short_cents", 0) for o in rows),
                   "short_n": sum(1 for o in rows if o["summary"].get("short_cents")),
                   "lab_cents": lab, "shipping_cents": ship, "keep_cents": keep,
                   "profit_pct": round(100 * keep / total, 1) if total else None,
                   "unpaid": sum(1 for o in rows if o["summary"]["due_cents"] > 0)
                   + sum(1 for e in book.extras(sid) if X.summary(e, {})["due_cents"] > 0),
                   "no_photo": sum(1 for o in rows if not (o["image"] or o["edited"]) and o["lines"]),
                   "glasses": sum(1 for o in rows if o["glasses"])},
    }


def r_team_list(b):
    sid = int(b["shoot_id"])
    rows = book.orders(sid)
    return {"teams": [{**t, "count": sum(1 for o in rows if o["team"] == t["name"])} for t in book.team_list(sid)],
            "next": book.next_shoot_name(sid)}


def r_team_list_save(b):
    book.save_team_list(int(b["shoot_id"]), b.get("teams") or [])
    return {"ok": True}


# ------------------------------------------------ team 5x7s for the school --
def _school_rows(sid: int, crops: str) -> list[dict]:
    st = book.school(sid)
    return SC.check(book.team_list(sid), _team_photos(sid), crops, st["skip"])


def _school_status(sid: int, photos: dict) -> dict:
    """For Totals: have the team 5x7s gone to the school, and has a team photo changed since?"""
    st = book.school(sid)
    sent = st.get("sent") or None
    imgs = {t: (v or {}).get("image", "") for t, v in photos.items()}
    out = {"needed": any(imgs.values()), "sent_at": sent and sent.get("at"), "teams": len(sent.get("teams", [])) if sent else 0}
    if sent:
        was = {t["name"]: t.get("image", "") for t in sent.get("teams", [])}
        out["changed"] = [t for t, img in imgs.items() if img and t in was and was[t] != img]
        out["new"] = [t for t, img in imgs.items() if img and t not in was and t not in st["skip"]]
    return out


def r_school(b):
    sid, crops = int(b["shoot_id"]), str(b.get("crops_dir") or "")
    st, rows = book.school(sid), _school_rows(sid, str(b.get("crops_dir") or ""))
    sent = st.get("sent") or None
    changed = []
    if sent:
        was = {t["name"]: t.get("image", "") for t in sent.get("teams", [])}
        changed = [r["name"] for r in rows if r["status"] == "ok" and was.get(r["name"]) != r["image"]]
    sh = book.shoot(sid) or {}
    return {"school": st, "rows": rows, "changed": changed, "mail": SC.mail_settings(), "shoot": sh.get("name", ""),
            "estimate": sum(1 for r in rows if r["status"] == "ok") * 1_400_000, "limit": SC.SEND_LIMIT}


def r_school_set(b):
    sid, patch = int(b["shoot_id"]), {}
    if "email" in b:
        patch["email"] = str(b["email"] or "").strip()
    if "skip" in b:
        patch["skip"] = [str(x) for x in b.get("skip") or []]
    return {"school": book.set_school(sid, patch)}


def _school_ready(sid: int, crops: str) -> list[dict]:
    rows = _school_rows(sid, crops)
    todo = [r["name"] for r in rows if r["status"] == "todo"]
    if todo:
        raise ValueError(f"{len(todo)} team{'s' if len(todo) > 1 else ''} not ready: {', '.join(todo[:3])}{'…' if len(todo) > 3 else ''}")
    if not any(r["status"] == "ok" for r in rows):
        raise ValueError("No team photos to send.")
    return rows


def _zip_name(sid: int) -> str:
    return SC.safe_name(f"{(book.shoot(sid) or {}).get('name', 'Shoot')} - Team photos") + ".zip"


def _mark_sent(sid: int, rows: list[dict], to: str, how: str) -> dict:
    sent = {"at": time.time(), "to": to, "how": how,
            "teams": [{"name": r["name"], "image": r["image"]} for r in rows if r["status"] == "ok"]}
    book.set_school(sid, {"sent": sent, "email": to})
    return sent


def r_school_zip(b):
    sid = int(b["shoot_id"])
    rows = _school_ready(sid, str(b.get("crops_dir") or ""))
    return SC.make_zip(rows, Path(b["folder"]) / _zip_name(sid))


def r_school_send(b):
    sid, to = int(b["shoot_id"]), str(b.get("to") or "")
    rows = _school_ready(sid, str(b.get("crops_dir") or ""))
    data, n = SC.zip_for_email(rows)  # built in memory: nothing on disk to be locked
    SC.send(to, str(b.get("subject") or ""), str(b.get("body") or ""), data, _zip_name(sid))
    return {"sent": _mark_sent(sid, rows, to, "app"), "zip": {"bytes": len(data), "teams": n}}


def r_school_gmail(b):
    """Gmail opens a filled-in message; the zip is saved and its folder opened, to drag in."""
    import webbrowser
    sid = int(b["shoot_id"])
    rows = _school_ready(sid, str(b.get("crops_dir") or ""))
    z = SC.make_zip(rows, Path(b["folder"]) / _zip_name(sid), for_email=True)
    webbrowser.open(SC.gmail_compose_url(str(b.get("to") or ""), str(b.get("subject") or ""), str(b.get("body") or "")))
    book.set_school(sid, {"email": str(b.get("to") or "").strip()})
    return z


def r_school_mark_sent(b):
    sid = int(b["shoot_id"])
    return {"sent": _mark_sent(sid, _school_rows(sid, str(b.get("crops_dir") or "")), str(b.get("to") or ""), "gmail")}


def r_mail_settings(b):
    if b.get("set"):
        return SC.save_mail(b.get("from"), b.get("password") or None, bool(b.get("forget")))
    return SC.mail_settings()


def r_mail_test(b):
    return SC.test_login()


def r_team_drop(b):
    book.drop_team(int(b["shoot_id"]), str(b.get("team") or ""))
    return {"ok": True}


def r_team_order(b):
    return {"teams": book.set_team_order(int(b["shoot_id"]), b.get("teams") or [])}


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
    book.plan_team(sid, o.get("team"), o.get("coach"))
    return {"order": _decorate(o, catalog())}


def r_bulk(b):
    f = b.get("fields") or {}
    n = book.bulk_update(int(b["shoot_id"]), b.get("ids") or [], f)
    if f.get("team"):
        book.plan_team(int(b["shoot_id"]), f["team"], f.get("coach", ""))
    return {"changed": n}


def r_bulk_pay(b):
    """Mark many envelopes paid at once: cash/check/venmo/other = paid in full; "" = picture day; "none" = unpaid."""
    sid, ids, m = int(b["shoot_id"]), {int(i) for i in b.get("ids") or []}, str(b.get("method") or "").lower()
    cat = catalog()
    pays = [(o["id"], m, O.calculate(o["lines"], cat)["total_cents"] if m not in ("", "none") else 0)
            for o in book.orders(sid) if o["id"] in ids]
    return {"changed": book.set_payments(sid, pays)}


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


def _summary(b) -> dict:
    sid = int(b["shoot_id"])
    cat = catalog()
    shoot = next((x for x in book.shoots() if x["id"] == sid), {})
    orders = [_decorate(o, cat) for o in book.orders(sid)]
    _, sub = _report_titles({"shoot_id": sid, "kind": "pull"})
    if shoot.get("season"):
        sub += f" · {shoot['season']}"
    extras = [{**e, "summary": X.summary(e, _team_photos(sid)), "who": X.who(e)} for e in book.extras(sid)]
    return {"title": "Shoot summary", "subtitle": sub, "sections": R.shoot_summary(orders, cat, shoot, extras)}


def r_summary(b):
    return _summary(b)


def r_summary_pdf(b):
    s = _summary(b)
    return {"path": str(R.pdf_sections(s["sections"], Path(b["path"]), s["title"], s["subtitle"]))}


def r_analysis(b):
    """Sales analysis for one shoot (optionally one team), or every shoot together."""
    cat = catalog()
    shoots = book.shoots()
    if b.get("shoot_id") == "all":
        orders = [_decorate(o, cat) for s in shoots for o in book.orders(s["id"])]
        ship = sum(int(s.get("shipping_cents") or 0) for s in shoots)
        team = None
    else:
        sid = int(b["shoot_id"])
        orders = [_decorate(o, cat) for o in book.orders(sid)]
        ship = int(next((s for s in shoots if s["id"] == sid), {}).get("shipping_cents") or 0)
        team = b.get("team")
    if b.get("shoot_id") == "all":
        ex = [X.totals(book.extras(s["id"]), _team_photos(s["id"])) for s in shoots]
        ex = {k: sum(e[k] for e in ex) for k in ex[0]} if ex else X.totals([], {})
    else:
        ex = X.totals(book.extras(sid), _team_photos(sid))
    unit = A.unit_lab_cents(cat, M.order_cost_cents)
    out = A.analyze(orders, cat, unit, ship, team, ex)
    out["shoots"] = len(shoots) if b.get("shoot_id") == "all" else 1
    if b.get("shoot_id") == "all":  # each shoot's own numbers, for ranking by profit per hour
        rows = []
        for s in shoots:
            one = A.analyze([_decorate(o, cat) for o in book.orders(s["id"])], cat, unit, int(s.get("shipping_cents") or 0), None,
                            X.totals(book.extras(s["id"]), _team_photos(s["id"])))["selection"]
            rows.append({"id": s["id"], "name": s["name"], "date": s.get("date") or "", "archived": s.get("archived"),
                         "hours": _hours_total(s), "envelopes": one["n"], "profit": one["profit"], "sales": one["sales"]})
        out["per_shoot"] = rows
    return out


def _hours_total(s: dict) -> float:
    try:
        return round(sum(float(v) for v in json.loads(s.get("hours") or "{}").values()), 2)
    except (ValueError, TypeError, AttributeError):
        return 0.0


def r_shoot_hours(b):
    return {"hours": book.set_hours(int(b["shoot_id"]), b.get("hours") or {}), "shoot_id": int(b["shoot_id"])}


# ------------------------------------------------- school & other orders --

def _crop_names() -> set[str] | None:
    try:
        from . import engine
        return {x["name"] for x in engine.sizes()}
    except Exception:  # noqa: BLE001 - without the crop setup, don't flag sizes
        return None


def _extra_view(e: dict, tp: dict, crop_names, found: dict) -> dict:
    e = dict(e)
    e["summary"] = X.summary(e, tp)
    e["who"] = X.who(e)
    ls = X.lines(e, tp, crop_names)
    for l in ls:
        if not l["why"] and found is not None and l["file"]:
            l["found"] = l["file"].lower() in found
            if not l["found"]:
                l["why"] = f"no {l['size']} crop yet"
    e["lines"] = ls
    return e


def r_extras(b):
    sid = int(b["shoot_id"])
    tp = _team_photos(sid)
    ex = book.extras(sid)
    crops = b.get("crops_dir") or ""
    found = None
    if crops and Path(crops).is_dir():
        stems = {l["file"] for e in ex for l in X.lines(e, tp) if l["file"]}
        found = {k: str(v) for k, v in O.find_crops(Path(crops), stems).items()}
    cn = _crop_names()
    return {"extras": [_extra_view(e, tp, cn, found) for e in ex], "totals": X.totals(ex, tp),
            "choices": X.choices(), "crops_checked": found is not None,
            "shoots": [{"id": s["id"], "name": s["name"], "count": len(book.extras(s["id"]))}
                       for s in book.shoots() if s["id"] != sid]}


def r_extra_save(b):
    sid = int(b["shoot_id"])
    e = book.save_extra(sid, b.get("order") or {})
    return {"order": _extra_view(e, _team_photos(sid), _crop_names(), None)}


def r_extra_delete(b):
    book.delete_extra(int(b["id"]))
    return {"ok": True}


def r_extras_copy(b):
    """Copy another shoot's school & other orders here, unpaid; team counts follow the team names."""
    sid, src = int(b["shoot_id"]), int(b["from_shoot_id"])
    teams = book.team_order(sid)
    n = 0
    for e in book.extras(src):
        items = []
        for it in e["items"]:
            it = dict(it)
            if it.get("src") == "teams":
                old = {k: int(v or 0) for k, v in (it.get("counts") or {}).items()}
                vals = [v for v in old.values() if v > 0]
                usual = max(set(vals), key=vals.count) if vals else 1
                it["counts"] = {t: old.get(t, usual) for t in teams}
            elif it.get("src") == "photo":
                continue  # one person's photo from another shoot doesn't carry over
            items.append(it)
        book.save_extra(sid, {"kind": e["kind"], "customer": e["customer"], "contact": e["contact"], "items": items,
                              "notes": e["notes"]})
        n += 1
    return {"copied": n}


def r_invoice_pdf(b):
    sid = int(b["shoot_id"])
    e = next((x for x in book.extras(sid) if x["id"] == int(b["id"])), None)
    if not e:
        raise ValueError("That order is gone.")
    shoot = next((x for x in book.shoots() if x["id"] == sid), {})
    return {"path": str(R.invoice_pdf(e, X.summary(e, _team_photos(sid)), shoot, Path(b["path"])))}


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
    plan = O.lab_plan(rows, catalog(), _team_photos(sid), book.extras(sid))
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


def _photo_finder(folder: str):
    """stem -> the photo's path in the shoot's folder (or None), and whether any photos were found."""
    index: dict[str, Path] = {}
    if folder and Path(folder).is_dir():
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".") and not d.endswith("_out") and d != "_retouched"]
            for f in files:
                stem, ext = os.path.splitext(f)
                if ext.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".hif"):
                    index.setdefault(stem.lower(), Path(root) / f)
    return (lambda stem: index.get(O.frame_stem(stem).lower()) if stem else None), bool(index)


def r_envelopes_pdf(b):
    """Digital envelopes: each envelope drawn like the paper order form, one page each (or just the ids given)."""
    sid = int(b["shoot_id"])
    sh = book.shoot(sid) or {}
    find, found = _photo_finder(str(b.get("folder") or sh.get("folder") or ""))
    ids = {int(i) for i in b.get("ids") or []}
    rows = [o for o in book.orders(sid) if not ids or o["id"] in ids]
    path = R.envelopes_pdf(sh, rows, catalog(), find, Path(b["path"]))
    return {"path": str(path), "photos_found": found, "pages": len(rows)}


def r_matching_pdf(b):
    """Matching sheets: one page per team, each envelope's photo, number and contents, in stuffing order."""
    sid = int(b["shoot_id"])
    sh = book.shoot(sid) or {}
    find, found = _photo_finder(str(b.get("folder") or sh.get("folder") or ""))
    index = found
    path = R.matching_pdf(sh, book.orders(sid), catalog(), book.extras(sid), _team_photos(sid), find, Path(b["path"]))
    return {"path": str(path), "photos_found": bool(index)}


def r_meridian_settings(b):
    import json
    s = meridian_settings()
    for k in M.DEFAULT_SETTINGS:
        if k in b:
            s[k] = str(b[k]).strip()
    _meridian_path().write_text(json.dumps(s, indent=2), encoding="utf-8")
    return {"settings": s, "problems": M.settings_problems(s)}


def r_meridian_report(b):
    path = Path(str(b.get("csv") or ""))
    if not path.is_file():
        raise FileNotFoundError("Build the Meridian order first.")
    return M.report(path)


def r_meridian_build(b):
    sid = int(b["shoot_id"])
    rows = [o for o in book.orders(sid) if o["lines"]]
    plan = O.lab_plan(rows, catalog(), _team_photos(sid), book.extras(sid))
    if not Path(b["crops_dir"]).is_dir():
        raise FileNotFoundError(f"Crops folder not found: {b['crops_dir']}")
    s = meridian_settings()
    bad = M.settings_problems(s)
    if bad:
        raise ValueError(" ".join(bad))
    shoot = next((x for x in book.shoots() if x["id"] == sid), {})
    name = str(b.get("order_name") or shoot.get("name") or "Picture day")
    cat, crops, out = catalog(), Path(b["crops_dir"]), Path(b["out_dir"])
    if not b.get("job"):
        return M.build(plan, cat, crops, out, s, name)

    def run(job):  # in the background, so the window can show a progress bar
        return M.build(plan, cat, crops, out, s, name,
                       lambda done, total, msg: job.update(done=done, total=total, message=msg, current=msg))
    return {"job": jobs.start("meridian", run).id}


def r_lab_build(b):
    sid = int(b["shoot_id"])
    rows = [o for o in book.orders(sid) if o["lines"]]
    plan = O.lab_plan(rows, catalog(), _team_photos(sid), book.extras(sid))
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
    "/api/orders/list": r_list, "/api/orders/save": r_save, "/api/orders/delete": r_delete, "/api/orders/bulk": r_bulk, "/api/orders/bulk-pay": r_bulk_pay,
    "/api/orders/restore": r_restore, "/api/orders/team-photo": r_team_photo,
    "/api/orders/rename-team": r_rename_team, "/api/orders/team-order": r_team_order, "/api/orders/team-drop": r_team_drop, "/api/orders/envelopes-pdf": r_envelopes_pdf, "/api/orders/school": r_school, "/api/orders/school-set": r_school_set,
    "/api/orders/school-zip": r_school_zip, "/api/orders/school-send": r_school_send, "/api/orders/school-gmail": r_school_gmail,
    "/api/orders/school-mark-sent": r_school_mark_sent, "/api/mail-settings": r_mail_settings, "/api/mail-test": r_mail_test, "/api/orders/team-list": r_team_list, "/api/orders/team-list-save": r_team_list_save, "/api/orders/price": r_price,
    "/api/orders/export": r_export, "/api/orders/export-name": r_export_name,
    "/api/orders/crop-list": r_crop_list, "/api/orders/lab-plan": r_lab_plan, "/api/orders/lab-build": r_lab_build,
    "/api/orders/import-web": r_import_web, "/api/orders/open-prices": r_open_prices,
    "/api/orders/report": r_report, "/api/orders/analysis": r_analysis,
    "/api/orders/extras": r_extras, "/api/orders/extra/save": r_extra_save, "/api/orders/extra/delete": r_extra_delete,
    "/api/orders/matching-pdf": r_matching_pdf, "/api/orders/shoot-hours": r_shoot_hours,
    "/api/orders/backups": r_backups, "/api/orders/backup-now": r_backup_now, "/api/orders/backup-second": r_backup_second,
    "/api/orders/backup-restore": r_backup_restore, "/api/orders/folder-link": r_folder_link,
    "/api/orders/folder-status": r_folder_status, "/api/orders/folder-import": r_folder_import,
    "/api/orders/extras-copy": r_extras_copy, "/api/orders/invoice-pdf": r_invoice_pdf, "/api/orders/summary": r_summary, "/api/orders/summary-pdf": r_summary_pdf, "/api/orders/shipping": r_shipping, "/api/orders/meridian-settings": r_meridian_settings, "/api/orders/meridian-build": r_meridian_build, "/api/orders/meridian-report": r_meridian_report,
}

for _k in _MUTATING:
    if _k in ROUTES:
        ROUTES[_k] = _after_change(ROUTES[_k])
