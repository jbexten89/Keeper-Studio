"""Keeping orders safe.

Two things, both automatic:

* Each shoot's orders are also saved in its photo folder, as "Keeper Studio
  orders.json". Copy the folder to another PC (or restore it from a backup)
  and the envelopes, payments and team photos come with it.
* The whole order book is copied to backups/ each day it's opened and each time
  the app closes, with an optional second copy somewhere else (a OneDrive
  folder or a USB stick). Any copy can be put back from Shoot > Backups.
"""

from __future__ import annotations

import json
import platform
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from . import paths

NAME = "Keeper Studio orders.json"
KEEP_CLOSE = 14  # backups made when the app closes
KEEP_SECOND = 14


# ------------------------------------------------------------- folder file --
def folder_file(folder: str | Path) -> Path:
    return Path(folder) / NAME


def write_folder_file(book, sid: int) -> Path | None:
    """Save one shoot into its photo folder. Quietly does nothing without a folder."""
    sh = book.shoot(sid)
    if not sh or not sh.get("folder"):
        return None
    folder = Path(sh["folder"])
    if not folder.is_dir():
        return None
    data = book.export_shoot(sid)
    data["saved"] = time.time()
    data["computer"] = platform.node()
    dst = folder_file(folder)
    tmp = dst.with_name(dst.name + ".part")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dst)
    return dst


def read_folder_file(folder: str | Path) -> dict | None:
    p = folder_file(folder)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("format") == "keeper-studio-orders" else None


def folder_status(book, folder: str) -> dict:
    """What the orders file in this folder means for this PC's order book."""
    d = read_folder_file(folder)
    if not d:
        return {"file": None}
    sh = d.get("shoot") or {}
    info = {"name": sh.get("name") or "", "date": sh.get("date") or "", "envelopes": len(d.get("orders") or []),
            "saved": d.get("saved") or 0, "changed": sh.get("changed") or 0, "uid": sh.get("uid") or ""}
    here = book.shoot_by_uid(info["uid"])
    if not here:
        return {"file": info, "state": "new"}
    newer = float(info["changed"] or 0) > float(here.get("changed") or 0) + 1
    return {"file": info, "state": "newer" if newer else "same", "shoot_id": here["id"],
            "here_envelopes": len(book.orders(here["id"])), "here_changed": here.get("changed") or 0}


class FolderWriter:
    """Writes a shoot's folder file a few seconds after its last change."""

    def __init__(self, delay: float = 3.0):
        self.delay = delay
        self._pending: set[int] = set()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self.book = None
        self.last_error = ""

    def touch(self, book, sid: int | None) -> None:
        self.book = book
        with self._lock:
            if sid:
                self._pending.add(int(sid))
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        with self._lock:
            ids, self._pending = self._pending, set()
            self._timer = None
        for sid in ids:
            try:
                write_folder_file(self.book, sid)
                self.last_error = ""
            except Exception as e:  # noqa: BLE001 - a backup copy must never break saving
                self.last_error = f"{type(e).__name__}: {e}"


writer = FolderWriter()


# --------------------------------------------------------------- backups --
def backups_dir() -> Path:
    return paths.data_dir() / "backups"


def _settings_path() -> Path:
    return paths.data_dir() / "backup.json"


def settings() -> dict:
    try:
        d = json.loads(_settings_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(d: dict) -> dict:
    s = {**settings(), **d}
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(s, indent=1), encoding="utf-8")
    return s


def _prune(folder: Path, pattern: str, keep: int) -> None:
    for old in sorted(folder.glob(pattern))[:-keep]:
        old.unlink(missing_ok=True)


def backup_now(book, kind: str = "close") -> dict:
    """Copy the order book to backups/ (and the second place, if one is set)."""
    folder = backups_dir()
    name = f"orders-{time.strftime('%Y-%m-%d-%H%M%S')}-{kind}.sqlite3"
    dst = book.backup_to(folder / name)
    _prune(folder, f"orders-*-{kind}.sqlite3", KEEP_CLOSE)
    out = {"file": str(dst), "second": "", "second_error": ""}
    second = settings().get("second") or ""
    if second:
        try:
            sd = Path(second)
            if not sd.is_dir():
                raise FileNotFoundError(f"{second} isn't there (drive unplugged?)")
            shutil.copy2(dst, sd / name)
            _prune(sd, "orders-*.sqlite3", KEEP_SECOND)
            out["second"] = str(sd / name)
        except Exception as e:  # noqa: BLE001
            out["second_error"] = str(e)
    save_settings({"last": time.time(), "last_second_error": out["second_error"]})
    return out


def _describe(p: Path) -> dict:
    st = p.stat()
    kind = "before-restore" if "before-restore" in p.name else "close" if p.name.endswith("-close.sqlite3") else "manual" if p.name.endswith("-manual.sqlite3") else "daily"
    shoots = envelopes = 0
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        shoots = con.execute("SELECT COUNT(*) FROM shoots").fetchone()[0]
        envelopes = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        con.close()
    except sqlite3.Error:
        pass
    return {"name": p.name, "time": st.st_mtime, "size": st.st_size, "kind": kind, "shoots": shoots, "envelopes": envelopes}


def list_backups() -> dict:
    folder = backups_dir()
    items = sorted((_describe(p) for p in folder.glob("orders-*.sqlite3")), key=lambda x: -x["time"]) if folder.is_dir() else []
    s = settings()
    return {"folder": str(folder), "items": items, "second": s.get("second") or "", "last": s.get("last") or 0,
            "last_second_error": s.get("last_second_error") or ""}


def restore(open_book, close_book, name: str) -> dict:
    """Put a backup back. The order book as it is now is saved first, so this can be undone."""
    src = backups_dir() / Path(name).name
    if not src.is_file() or not src.name.startswith("orders-"):
        raise FileNotFoundError("That backup isn't there any more.")
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)  # check it opens before touching anything
    con.execute("SELECT COUNT(*) FROM shoots").fetchone()
    book = open_book()
    saved = book.backup_to(backups_dir() / f"orders-{time.strftime('%Y-%m-%d-%H%M%S')}-before-restore.sqlite3")
    live = book.path
    close_book()
    out = sqlite3.connect(str(live))
    con.backup(out)
    out.close()
    con.close()
    for extra in (live.with_name(live.name + "-wal"), live.with_name(live.name + "-shm")):
        extra.unlink(missing_ok=True)
    open_book()
    return {"restored": src.name, "saved_current": saved.name}
