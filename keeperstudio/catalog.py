"""The catalog: a small key/value store in SQLite.

The interface keeps flags, ratings, labels, collections, manual crop placements
and settings here, in named stores. One file per user, shared by every shoot,
so marks survive restarts and re-opening a folder.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class Catalog:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS kv (store TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
            " PRIMARY KEY (store, key))"
        )
        self._db.commit()

    def get(self, store: str, key: str):
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE store=? AND key=?", (store, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put_many(self, store: str, items: list[tuple[str, object]]) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT INTO kv (store, key, value) VALUES (?, ?, ?)"
                " ON CONFLICT(store, key) DO UPDATE SET value=excluded.value",
                [(store, k, json.dumps(v)) for k, v in items],
            )
            self._db.commit()

    def put(self, store: str, key: str, value) -> None:
        self.put_many(store, [(key, value)])

    def delete(self, store: str, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM kv WHERE store=? AND key=?", (store, key))
            self._db.commit()

    def entries(self, store: str) -> list[tuple[str, object]]:
        with self._lock:
            rows = self._db.execute("SELECT key, value FROM kv WHERE store=?", (store,)).fetchall()
        return [(k, json.loads(v)) for k, v in rows]
