"""The order book: shoots, envelopes and team photos, kept on this computer.

Its own SQLite file (orders.sqlite3) beside the catalog in the user's app-data
folder, so orders survive app updates and never mix with flags and ratings.
A dated copy is kept in backups/ each day the order book is opened.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS shoots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  date TEXT NOT NULL DEFAULT '',
  season TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0,
  shipping_cents INTEGER NOT NULL DEFAULT 0,
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  shoot_id INTEGER NOT NULL REFERENCES shoots(id) ON DELETE CASCADE,
  envelope TEXT NOT NULL DEFAULT '',
  athlete TEXT NOT NULL DEFAULT '',
  team TEXT NOT NULL DEFAULT '',
  coach TEXT NOT NULL DEFAULT '',
  parent TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  glasses INTEGER NOT NULL DEFAULT 0,
  frames TEXT NOT NULL DEFAULT '',
  image TEXT NOT NULL DEFAULT '',
  edited TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  paid_method TEXT NOT NULL DEFAULT '',
  paid_cents INTEGER NOT NULL DEFAULT 0,
  lines TEXT NOT NULL DEFAULT '[]',
  web_order TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_shoot ON orders(shoot_id);
CREATE TABLE IF NOT EXISTS team_photos (
  shoot_id INTEGER NOT NULL REFERENCES shoots(id) ON DELETE CASCADE,
  team TEXT NOT NULL,
  image TEXT NOT NULL DEFAULT '',
  coach TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (shoot_id, team)
);
CREATE TABLE IF NOT EXISTS extra_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  shoot_id INTEGER NOT NULL REFERENCES shoots(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT '',
  customer TEXT NOT NULL DEFAULT '',
  contact TEXT NOT NULL DEFAULT '',
  items TEXT NOT NULL DEFAULT '[]',
  paid_method TEXT NOT NULL DEFAULT '',
  paid_cents INTEGER NOT NULL DEFAULT 0,
  check_no TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS extra_orders_shoot ON extra_orders(shoot_id);
"""
EXTRA_FIELDS = ("kind", "customer", "contact", "items", "paid_method", "paid_cents", "check_no", "notes")

ORDER_FIELDS = ("envelope", "athlete", "team", "coach", "parent", "phone", "email", "glasses", "frames",
                "image", "edited", "notes", "paid_method", "paid_cents", "accepted_cents", "lines", "web_order")
PAID_METHODS = ("", "cash", "check", "venmo", "card", "other", "none")  # "none": owes it all, even on a prepaid shoot; "card" kept for old envelopes


class OrderBook:
    def __init__(self, path: Path, backups: Path | None = None):
        self.path = Path(path)
        if backups and self.path.is_file():
            self._daily_backup(backups)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        """Add columns that came after a user's order book was created."""
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(shoots)")}
        if "shipping_cents" not in cols:
            self._db.execute("ALTER TABLE shoots ADD COLUMN shipping_cents INTEGER NOT NULL DEFAULT 0")
        if "prepaid" not in cols:  # families pay inside the envelope on picture day
            self._db.execute("ALTER TABLE shoots ADD COLUMN prepaid INTEGER NOT NULL DEFAULT 0")
        if "team_order" not in cols:  # the order teams are listed in, as the user arranged them
            self._db.execute("ALTER TABLE shoots ADD COLUMN team_order TEXT NOT NULL DEFAULT '[]'")
        if "uid" not in cols:  # stays the same when the shoot is copied to another PC (folder orders file)
            self._db.execute("ALTER TABLE shoots ADD COLUMN uid TEXT NOT NULL DEFAULT ''")
        if "folder" not in cols:  # the shoot's photo folder, where its orders file is kept
            self._db.execute("ALTER TABLE shoots ADD COLUMN folder TEXT NOT NULL DEFAULT ''")
        if "hours" not in cols:  # time spent on the shoot, by part: {"shoot": 3.5, "edit": 6, ...} (JSON)
            self._db.execute("ALTER TABLE shoots ADD COLUMN hours TEXT NOT NULL DEFAULT ''")
        if "changed" not in cols:  # last time anything in the shoot changed
            self._db.execute("ALTER TABLE shoots ADD COLUMN changed REAL NOT NULL DEFAULT 0")
        for r in self._db.execute("SELECT id FROM shoots WHERE uid=''").fetchall():
            self._db.execute("UPDATE shoots SET uid=? WHERE id=?", (uuid.uuid4().hex, r["id"]))
        ocols = {r["name"] for r in self._db.execute("PRAGMA table_info(orders)")}
        if "accepted_cents" not in ocols:  # came up short and the shortfall was let go
            self._db.execute("ALTER TABLE orders ADD COLUMN accepted_cents INTEGER NOT NULL DEFAULT 0")

    # ---------------------------------------------------------- backups --
    def backup_to(self, dst: Path) -> Path:
        """A consistent copy of the whole order book (safe while it's open)."""
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".part")
        out = sqlite3.connect(str(tmp))
        with self._lock:
            self._db.commit()
            self._db.backup(out)
        out.close()
        tmp.replace(dst)
        return dst

    # ---------------------------------------- one shoot, as a portable file --
    def touch(self, sid: int) -> None:
        with self._lock:
            self._db.execute("UPDATE shoots SET changed=? WHERE id=?", (time.time(), int(sid)))
            self._db.commit()

    def shoot(self, sid: int) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM shoots WHERE id=?", (int(sid),)).fetchone()
        return dict(r) if r else None

    def shoot_by_uid(self, uid: str) -> dict | None:
        if not uid:
            return None
        with self._lock:
            r = self._db.execute("SELECT * FROM shoots WHERE uid=?", (str(uid),)).fetchone()
        return dict(r) if r else None

    def set_folder(self, sid: int, folder: str) -> None:
        with self._lock:
            self._db.execute("UPDATE shoots SET folder=? WHERE id=?", (str(folder or ""), int(sid)))
            self._db.commit()

    SHOOT_KEYS = ("name", "date", "season", "notes", "archived", "shipping_cents", "prepaid", "team_order", "created", "uid", "changed", "hours")

    HOUR_PARTS = ("shoot", "edit", "lab", "delivery")

    def set_hours(self, sid: int, hours: dict) -> dict:
        """Hours spent on a shoot, by part (shooting, culling & editing, envelopes & lab, delivery)."""
        clean = {}
        for k in self.HOUR_PARTS:
            try:
                v = float(str((hours or {}).get(k, "")).strip() or 0)
            except ValueError:
                raise ValueError("Hours must be numbers, like 3.5.")
            if v < 0 or v > 500:
                raise ValueError("That many hours doesn't look right.")
            if v:
                clean[k] = round(v, 2)
        with self._lock:
            self._db.execute("UPDATE shoots SET hours=? WHERE id=?", (json.dumps(clean) if clean else "", int(sid)))
            self._db.commit()
        return clean

    def export_shoot(self, sid: int) -> dict:
        """Everything about one shoot except the photos: envelopes, payments, team photos, school & other orders."""
        sh = self.shoot(sid)
        if not sh:
            raise ValueError("That shoot isn't in the order book.")
        with self._lock:
            orders = [dict(r) for r in self._db.execute("SELECT * FROM orders WHERE shoot_id=? ORDER BY id", (int(sid),)).fetchall()]
            teams = [dict(r) for r in self._db.execute("SELECT team, image, coach FROM team_photos WHERE shoot_id=?", (int(sid),)).fetchall()]
            extras = [dict(r) for r in self._db.execute("SELECT * FROM extra_orders WHERE shoot_id=? ORDER BY id", (int(sid),)).fetchall()]
        for o in orders + extras:
            o.pop("id", None); o.pop("shoot_id", None)
        return {"format": "keeper-studio-orders", "version": 1,
                "shoot": {k: sh.get(k) for k in self.SHOOT_KEYS}, "orders": orders, "team_photos": teams, "extras": extras}

    def import_shoot(self, data: dict, replace_sid: int | None = None) -> int:
        """Bring in a shoot from an orders file. With replace_sid, its contents replace that shoot's."""
        if not isinstance(data, dict) or data.get("format") != "keeper-studio-orders":
            raise ValueError("That isn't a Keeper Studio orders file.")
        sh = dict(data.get("shoot") or {})
        ocols = {r["name"] for r in self._db.execute("PRAGMA table_info(orders)")}
        ecols = {r["name"] for r in self._db.execute("PRAGMA table_info(extra_orders)")}
        with self._lock:
            try:
                if replace_sid:
                    sid = int(replace_sid)
                    for t in ("orders", "team_photos", "extra_orders"):
                        self._db.execute(f"DELETE FROM {t} WHERE shoot_id=?", (sid,))
                    keys = [k for k in self.SHOOT_KEYS if k in sh and k not in ("created", "uid")]
                    if keys:
                        self._db.execute(f"UPDATE shoots SET {', '.join(f'{k}=?' for k in keys)} WHERE id=?", (*[sh[k] for k in keys], sid))
                else:
                    keys = [k for k in self.SHOOT_KEYS if k in sh]
                    if "name" not in keys:
                        raise ValueError("The orders file has no shoot name.")
                    sid = self._db.execute(f"INSERT INTO shoots ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                                           [sh[k] for k in keys]).lastrowid
                for o in data.get("orders") or []:
                    o = {k: v for k, v in o.items() if k in ocols and k not in ("id", "shoot_id")}
                    if isinstance(o.get("lines"), list):
                        o["lines"] = json.dumps(o["lines"])
                    o.setdefault("created", time.time()); o.setdefault("updated", time.time())
                    self._db.execute(f"INSERT INTO orders (shoot_id, {', '.join(o)}) VALUES (?, {', '.join('?' * len(o))})", (sid, *o.values()))
                for t in data.get("team_photos") or []:
                    self._db.execute("INSERT OR REPLACE INTO team_photos (shoot_id, team, image, coach) VALUES (?,?,?,?)",
                                     (sid, str(t.get("team") or ""), str(t.get("image") or ""), str(t.get("coach") or "")))
                for e in data.get("extras") or []:
                    e = {k: v for k, v in e.items() if k in ecols and k not in ("id", "shoot_id")}
                    if isinstance(e.get("items"), list):
                        e["items"] = json.dumps(e["items"])
                    e.setdefault("created", time.time()); e.setdefault("updated", time.time())
                    self._db.execute(f"INSERT INTO extra_orders (shoot_id, {', '.join(e)}) VALUES (?, {', '.join('?' * len(e))})", (sid, *e.values()))
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return sid

    def _daily_backup(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            dst = folder / f"orders-{time.strftime('%Y-%m-%d')}.sqlite3"
            if not dst.exists():
                src = sqlite3.connect(str(self.path))
                out = sqlite3.connect(str(dst))
                src.backup(out)
                out.close()
                src.close()
            for old in sorted(folder.glob("orders-*.sqlite3"))[:-30]:  # keep a month
                old.unlink(missing_ok=True)
        except Exception:
            pass  # a failed backup must never stop the app opening

    # ------------------------------------------------------------ shoots --
    def shoots(self, include_archived: bool = True) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM orders o WHERE o.shoot_id=s.id) AS n FROM shoots s"
                + ("" if include_archived else " WHERE archived=0")
                + " ORDER BY archived, CASE WHEN date='' THEN 1 ELSE 0 END, date DESC, created DESC").fetchall()
        return [dict(r) for r in rows]

    def set_shipping(self, sid: int, cents: int) -> None:
        """What Meridian charged to ship the shoot's order, typed in by hand."""
        with self._lock:
            self._db.execute("UPDATE shoots SET shipping_cents=? WHERE id=?", (max(0, int(cents)), int(sid)))
            self._db.commit()

    def save_shoot(self, data: dict) -> dict:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Give the shoot a name.")
        vals = (name, str(data.get("date") or ""), str(data.get("season") or ""), str(data.get("notes") or ""),
                1 if data.get("archived") else 0)
        with self._lock:
            if data.get("id"):
                self._db.execute("UPDATE shoots SET name=?, date=?, season=?, notes=?, archived=? WHERE id=?",
                                 (*vals, int(data["id"])))
                sid = int(data["id"])
                if "prepaid" in data:
                    self._db.execute("UPDATE shoots SET prepaid=? WHERE id=?", (1 if data["prepaid"] else 0, sid))
            else:  # new shoots: families pay on picture day unless told otherwise
                sid = self._db.execute("INSERT INTO shoots (name, date, season, notes, archived, created, prepaid, uid, changed) VALUES (?,?,?,?,?,?,?,?,?)",
                                       (*vals, time.time(), 0 if data.get("prepaid") is False else 1, uuid.uuid4().hex, time.time())).lastrowid
            self._db.commit()
            return dict(self._db.execute("SELECT * FROM shoots WHERE id=?", (sid,)).fetchone())

    def delete_shoot(self, sid: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM shoots WHERE id=?", (int(sid),))
            self._db.commit()

    # ------------------------------------------------------------ orders --
    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["lines"] = json.loads(d.get("lines") or "[]")
        d["glasses"] = bool(d.get("glasses"))
        return d

    def _prepaid(self, sid: int) -> bool:
        r = self._db.execute("SELECT prepaid FROM shoots WHERE id=?", (int(sid),)).fetchone()
        return bool(r and r["prepaid"])

    def orders(self, sid: int) -> list[dict]:
        rank = {t: i for i, t in enumerate(self.team_order(sid))}
        with self._lock:
            rows = self._db.execute("SELECT * FROM orders WHERE shoot_id=? ORDER BY id", (int(sid),)).fetchall()
            pre = self._prepaid(sid)
        return [{**self._row(r), "prepaid": pre, "team_rank": rank.get(r["team"], 10_000)} for r in rows]

    def get(self, oid: int) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM orders WHERE id=?", (int(oid),)).fetchone()
            pre = self._prepaid(r["shoot_id"]) if r else False
        return {**self._row(r), "prepaid": pre} if r else None

    # ---------------------------------------------------------- team order --
    def team_order(self, sid: int) -> list[str]:
        """Every team in the shoot: as arranged, then any others in the order they were first used."""
        with self._lock:
            r = self._db.execute("SELECT team_order FROM shoots WHERE id=?", (int(sid),)).fetchone()
            saved = json.loads((r["team_order"] if r else "") or "[]")
            seen = [x["team"] for x in self._db.execute(
                "SELECT team, MIN(created) c FROM orders WHERE shoot_id=? AND team<>'' GROUP BY team ORDER BY c, team",
                (int(sid),)).fetchall()]
            photos = [x["team"] for x in self._db.execute(
                "SELECT team FROM team_photos WHERE shoot_id=? ORDER BY rowid", (int(sid),)).fetchall()]
        live = set(seen) | set(photos)
        out = [t for t in saved if t in live]
        for t in seen + photos:
            if t not in out:
                out.append(t)
        return out

    def set_team_order(self, sid: int, names: list[str]) -> list[str]:
        clean = []
        for n in names or []:
            n = str(n or "").strip()
            if n and n not in clean:
                clean.append(n)
        with self._lock:
            self._db.execute("UPDATE shoots SET team_order=? WHERE id=?", (json.dumps(clean), int(sid)))
            self._db.commit()
        return self.team_order(sid)

    def next_envelope(self, sid: int) -> str:
        with self._lock:
            rows = self._db.execute("SELECT envelope FROM orders WHERE shoot_id=?", (int(sid),)).fetchall()
        nums = [int(r[0]) for r in rows if str(r[0]).strip().isdigit()]
        return str(max(nums) + 1) if nums else "1"

    def save_order(self, sid: int, data: dict) -> dict:
        clean = {}
        for k in ORDER_FIELDS:
            if k not in data:
                continue
            v = data[k]
            if k == "glasses":
                v = 1 if v else 0
            elif k in ("paid_cents", "accepted_cents"):
                v = max(0, int(v or 0))
            elif k == "lines":
                v = json.dumps([{"product_id": str(l.get("product_id")), "qty": int(l.get("qty") or 0)}
                                for l in (v or []) if int(l.get("qty") or 0) > 0])
            elif k == "paid_method":
                v = str(v or "").lower()
                if v not in PAID_METHODS:
                    v = "other"
            else:
                v = str(v or "").strip()
            clean[k] = v
        now = time.time()
        with self._lock:
            if data.get("id"):
                oid = int(data["id"])
                if clean:
                    sets = ", ".join(f"{k}=?" for k in clean)
                    self._db.execute(f"UPDATE orders SET {sets}, updated=? WHERE id=? AND shoot_id=?",
                                     (*clean.values(), now, oid, int(sid)))
            else:
                cols = ["shoot_id", *clean.keys(), "created", "updated"]
                oid = self._db.execute(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                       (int(sid), *clean.values(), now, now)).lastrowid
            self._db.commit()
            r = self._db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not r:
            raise ValueError("That order no longer exists.")
        return self._row(r)

    def bulk_update(self, sid: int, ids: list[int], fields: dict) -> int:
        """Set team and/or coach on many envelopes at once. Blank fields are left alone."""
        clean = {k: str(fields.get(k) or "").strip() for k in ("team", "coach") if str(fields.get(k) or "").strip()}
        ids = [int(i) for i in ids or []]
        if not clean or not ids:
            return 0
        sets = ", ".join(f"{k}=?" for k in clean)
        with self._lock:
            n = self._db.execute(f"UPDATE orders SET {sets}, updated=? WHERE shoot_id=? AND id IN ({','.join('?' * len(ids))})",
                                 (*clean.values(), time.time(), int(sid), *ids)).rowcount
            self._db.commit()
        return n

    def set_payments(self, sid: int, pays: list[tuple[int, str, int]]) -> int:
        """Set (id, method, paid cents) on many envelopes at once."""
        for _, m, _ in pays:
            if m not in PAID_METHODS:
                raise ValueError("Paid by must be cash, check, Venmo or other.")
        with self._lock:
            n = sum(self._db.execute("UPDATE orders SET paid_method=?, paid_cents=?, accepted_cents=0, updated=? WHERE shoot_id=? AND id=?",
                                     (m, max(0, int(c)), time.time(), int(sid), int(i))).rowcount for i, m, c in pays)
            self._db.commit()
        return n

    def delete_order(self, oid: int) -> dict | None:
        """Deletes and returns the order, so the interface can offer Undo."""
        o = self.get(oid)
        with self._lock:
            self._db.execute("DELETE FROM orders WHERE id=?", (int(oid),))
            self._db.commit()
        return o

    def restore_order(self, o: dict) -> dict:
        data = {k: o.get(k) for k in ORDER_FIELDS}
        return self.save_order(int(o["shoot_id"]), data)

    # ------------------------------------------- school & other orders --
    @staticmethod
    def _extra(r) -> dict:
        d = dict(r)
        d["items"] = json.loads(d.get("items") or "[]")
        return d

    def extras(self, sid: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM extra_orders WHERE shoot_id=? ORDER BY id", (int(sid),)).fetchall()
        return [self._extra(r) for r in rows]

    def save_extra(self, sid: int, data: dict) -> dict:
        vals = {}
        for k in EXTRA_FIELDS:
            if k not in data:
                continue
            v = data[k]
            if k == "items":
                v = json.dumps(v if isinstance(v, list) else [])
            elif k == "paid_cents":
                v = max(0, int(v or 0))
            elif k == "paid_method":
                v = str(v or "").lower()
                if v not in PAID_METHODS:
                    raise ValueError("Paid by must be cash, check, card or other.")
            else:
                v = str(v or "").strip()
            vals[k] = v
        now = time.time()
        with self._lock:
            oid = data.get("id")
            if oid:
                if vals:
                    self._db.execute(f"UPDATE extra_orders SET {', '.join(f'{k}=?' for k in vals)}, updated=? WHERE id=?",
                                     (*vals.values(), now, int(oid)))
            else:
                cols = ["shoot_id", *vals, "created", "updated"]
                cur = self._db.execute(f"INSERT INTO extra_orders ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                       (int(sid), *vals.values(), now, now))
                oid = cur.lastrowid
            self._db.commit()
            r = self._db.execute("SELECT * FROM extra_orders WHERE id=?", (int(oid),)).fetchone()
        return self._extra(r)

    def delete_extra(self, oid: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM extra_orders WHERE id=?", (int(oid),))
            self._db.commit()

    # -------------------------------------------------------- team photos --
    def team_photos(self, sid: int) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute("SELECT team, image, coach FROM team_photos WHERE shoot_id=?", (int(sid),)).fetchall()
        return {r["team"]: {"image": r["image"], "coach": r["coach"]} for r in rows}

    def set_team_photo(self, sid: int, team: str, image: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO team_photos (shoot_id, team, image) VALUES (?,?,?)"
                " ON CONFLICT(shoot_id, team) DO UPDATE SET image=excluded.image",
                (int(sid), str(team), str(image or "").strip()))
            self._db.commit()

    def rename_team(self, sid: int, old: str, new: str) -> int:
        new = str(new or "").strip()
        if not new:
            raise ValueError("A team needs a name.")
        with self._lock:
            n = self._db.execute("UPDATE orders SET team=?, updated=? WHERE shoot_id=? AND team=?",
                                 (new, time.time(), int(sid), old)).rowcount
            exists = self._db.execute("SELECT 1 FROM team_photos WHERE shoot_id=? AND team=?", (int(sid), new)).fetchone()
            r0 = self._db.execute("SELECT team_order FROM shoots WHERE id=?", (int(sid),)).fetchone()
            if r0:
                tord = json.loads(r0["team_order"] or "[]")
                if old in tord:
                    tord = [new if t == old else t for t in tord]
                    self._db.execute("UPDATE shoots SET team_order=? WHERE id=?",
                                     (json.dumps(list(dict.fromkeys(tord))), int(sid)))
            for r in self._db.execute("SELECT id, items FROM extra_orders WHERE shoot_id=?", (int(sid),)).fetchall():
                items, hit = json.loads(r["items"] or "[]"), False
                for it in items:
                    c = it.get("counts") or {}
                    if old in c:
                        c[new] = c.pop(old) + (c.get(new) or 0) if new in c else c.pop(old)
                        hit = True
                    if it.get("team") == old:
                        it["team"], hit = new, True
                if hit:
                    self._db.execute("UPDATE extra_orders SET items=? WHERE id=?", (json.dumps(items), r["id"]))
            if exists:
                self._db.execute("DELETE FROM team_photos WHERE shoot_id=? AND team=?", (int(sid), old))
            else:
                self._db.execute("UPDATE team_photos SET team=? WHERE shoot_id=? AND team=?", (new, int(sid), old))
            self._db.commit()
        return n

    def close(self) -> None:
        with self._lock:
            self._db.close()

