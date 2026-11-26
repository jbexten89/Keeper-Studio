"""Folder work files: a shoot's marks saved inside the shoot folder.

The catalog remembers marks by each photo's full path, so moving, renaming or
copying a folder (or opening it on another PC) loses them. Keeper Studio also
keeps `Keeper Studio work.json` in the folder it opened, matched by each
photo's place in the folder and its file size, and offers to restore from it
when a folder's marks are missing. For folders moved before there was a work
file, `find_moved` looks for the same photos (name and size) elsewhere in the
catalog.

Saved per photo: flag, stars, label, team photo and other marks ("meta"),
framing placed by hand ("manual"), crop style ("styles") and rotation
("rotate"); plus the plain (not smart) collections the folder's photos are in.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

NAME = "Keeper Studio work.json"
BY_PATH = ("manual", "styles", "rotate")  # stores keyed by the photo's path; "meta" is keyed by path|size
SKIP_COLLECTIONS = {"__smart__"}


def _has_marks(m) -> bool:
    return isinstance(m, dict) and any(v not in (None, 0, "", False, []) for v in m.values())


def _photo_marks(cat, p: dict) -> dict:
    """Everything the catalog holds for one photo, or {}."""
    out = {}
    m = cat.get("meta", f"{p['path']}|{p['size']}")
    if _has_marks(m):
        out["meta"] = m
    for store in BY_PATH:
        v = cat.get(store, p["path"])
        if v not in (None, {}, 0):
            out[store] = v
    return out


def _collections(cat, keys: dict[str, str]) -> list[dict]:
    """Plain collections holding any of these photos: [{id, name, files: [rel]}]."""
    out = []
    for _, c in cat.entries("collections"):
        if not isinstance(c, dict) or c.get("smart"):
            continue
        files = [keys[k] for k in c.get("keys") or [] if k in keys]
        if files:
            out.append({"id": c.get("id"), "name": c.get("name"), "files": files})
    return out


def marks_here(cat, photos: list[dict]) -> int:
    """How many of these photos already have marks in the catalog."""
    return sum(1 for p in photos if _photo_marks(cat, p))


def file_path(root: str) -> Path | None:
    r = Path(root)
    return r / NAME if r.is_dir() else None  # a .zip opens read-only: no work file


def read(root: str) -> dict | None:
    f = file_path(root)
    if not f or not f.is_file():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("photos"), dict) else None
    except (OSError, ValueError):
        return None


def _known(cat, p: dict) -> bool:
    """Has the catalog ever recorded anything for this photo here (even marks since cleared)?"""
    if cat.get("meta", f"{p['path']}|{p['size']}") is not None:
        return True
    return any(cat.get(s, p["path"]) is not None for s in BY_PATH)


def save(cat, root: str, photos: list[dict]) -> dict:
    """Write the folder's work file. Returns {saved, photos, path} or {error}.

    The catalog wins for any photo it knows about here; a photo it has never seen
    in this spot keeps what the work file already had, so saving after a move
    (before restoring) never throws the saved marks away."""
    f = file_path(root)
    if not f:  # a .zip opens read-only: its marks stay in the catalog only
        return {"saved": 0, "photos": 0, "path": "", "skipped": True, "zip": True}
    old = read(root)
    old_photos = (old or {}).get("photos") or {}
    snap, keys, carried = {}, {}, set()
    for p in photos:
        keys[f"{p['path']}|{p['size']}"] = p["rel"]
        m = _photo_marks(cat, p)
        if m:
            snap[p["rel"]] = {"size": p["size"], **m}
        elif not _known(cat, p) and p["rel"] in old_photos and int(old_photos[p["rel"]].get("size") or -1) == int(p["size"]):
            snap[p["rel"]] = old_photos[p["rel"]]
            carried.add(p["rel"])
    colls = _collections(cat, keys)
    for c in (old or {}).get("collections") or []:  # keep memberships of photos carried over
        keep = [r for r in c.get("files") or [] if r in carried]
        if not keep:
            continue
        mine = next((x for x in colls if x.get("id") == c.get("id") or x.get("name") == c.get("name")), None)
        if mine:
            mine["files"] = list(dict.fromkeys([*mine["files"], *keep]))
        else:
            colls.append({"id": c.get("id"), "name": c.get("name"), "files": keep})
    if not snap and not colls and not old:
        return {"saved": 0, "photos": 0, "path": str(f), "skipped": True}  # nothing to keep: don't litter the folder
    data = {"app": "Keeper Studio", "kind": "folder work", "version": 1, "saved": time.time(),
            "folder": str(root), "photos": snap, "collections": colls}
    tmp = f.with_name(NAME + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"error": f"Couldn't save the work file in this folder ({e.strerror or e})."}
    return {"saved": data["saved"], "photos": len(snap), "path": str(f)}


def _apply(cat, photos_by: dict, marks_for, collections: list[dict] | None) -> int:
    """Copy marks onto this folder's photos. marks_for(p) -> {store: value} or None."""
    n = 0
    meta, by_path = [], {s: [] for s in BY_PATH}
    for p in photos_by.values():
        m = marks_for(p)
        if not m:
            continue
        n += 1
        if m.get("meta") is not None:
            meta.append((f"{p['path']}|{p['size']}", m["meta"]))
        for s in BY_PATH:
            if m.get(s) is not None:
                by_path[s].append((p["path"], m[s]))
    if meta:
        cat.put_many("meta", meta)
    for s, items in by_path.items():
        if items:
            cat.put_many(s, items)
    for c in collections or []:
        keys = [f"{photos_by[r]['path']}|{photos_by[r]['size']}" for r in c.get("files") or [] if r in photos_by]
        if not keys:
            continue
        cur = cat.get("collections", c.get("id") or "") if c.get("id") else None
        if not cur:  # same name already here? add to it; otherwise make it
            cur = next((v for _, v in cat.entries("collections")
                        if isinstance(v, dict) and not v.get("smart") and v.get("name") == c.get("name")), None)
        if cur:
            cur = {**cur, "keys": list(dict.fromkeys([*(cur.get("keys") or []), *keys]))}
        else:
            cur = {"id": c.get("id") or f"c{int(time.time() * 1000)}", "name": c.get("name") or "Restored",
                   "keys": keys, "smart": None, "created": time.time()}
        cat.put("collections", cur["id"], cur)
    return n


def restore_from_file(cat, root: str, photos: list[dict]) -> int:
    d = read(root)
    if not d:
        return 0
    by_rel = {p["rel"]: p for p in photos}
    saved = d.get("photos") or {}

    def marks_for(p):
        m = saved.get(p["rel"])
        return m if m and int(m.get("size") or -1) == int(p["size"]) else None
    return _apply(cat, by_rel, marks_for, d.get("collections"))


def find_moved(cat, root: str, photos: list[dict]) -> dict | None:
    """The folder these photos were marked in before they moved: {folder, photos} or None.

    Matches by file name and size against every photo with marks in the catalog
    that isn't in this folder."""
    want = {(Path(p["path"]).name.lower(), int(p["size"])) for p in photos}
    here = str(Path(root))
    hits: dict[tuple, list[str]] = {}
    for k, v in cat.entries("meta"):
        path, _, size = k.rpartition("|")
        if not path or not size.isdigit() or not _has_marks(v) or path.startswith(here):
            continue
        nk = (Path(path).name.lower(), int(size))
        if nk in want:
            hits.setdefault(nk, []).append(path)
    if not hits:
        return None
    folders = Counter(str(Path(p).parent) for ps in hits.values() for p in ps)
    best, n = folders.most_common(1)[0]
    if n < max(3, len(photos) // 5):  # a handful of coincidences isn't a moved shoot
        return None
    return {"folder": best, "photos": n}


def restore_moved(cat, root: str, photos: list[dict], old_folder: str) -> int:
    old = Path(old_folder)

    def marks_for(p):
        op = str(old / Path(p["path"]).name)
        m = _photo_marks(cat, {"path": op, "size": p["size"]})
        if not m:  # the photo may sit in a sub-folder of the old shoot
            op = str(old / p["rel"]) if p.get("rel") else op
            m = _photo_marks(cat, {"path": op, "size": p["size"]})
        return m or None
    by = {p["rel"]: p for p in photos}
    old_keys = {f"{old / Path(p['path']).name}|{p['size']}": p["rel"] for p in photos}
    colls = _collections(cat, old_keys)
    return _apply(cat, by, marks_for, colls)


def status(cat, root: str, photos: list[dict]) -> dict:
    """What the UI needs to decide whether to offer a restore."""
    here = marks_here(cat, photos)
    d = read(root)
    out = {"marks_here": here, "file": None, "moved": None}
    if d:
        by_rel = {p["rel"]: p for p in photos}
        n = sum(1 for r, m in (d.get("photos") or {}).items() if r in by_rel and int(m.get("size") or -1) == int(by_rel[r]["size"]))
        out["file"] = {"photos": n, "saved": d.get("saved"), "folder": d.get("folder")}
    elif not here:
        out["moved"] = find_moved(cat, root, photos)
    return out
