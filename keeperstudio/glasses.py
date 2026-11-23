"""Find photos where the subject is wearing glasses.

Glasses frames add things a bare face doesn't have: a bar across the nose
bridge between the eyes, a rim line under each eye, and frame edges beside the
outer eye corners. Lens glare adds blown-out patches over the eyes. All are
measured on the face lined up so the eyes are level and 100 px apart, against
the face's own skin texture, so lighting and resolution don't matter.

On picture day the photographer shoots the glasses frames and then one without
glasses, so the collection also takes the photo right after each glasses photo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

VERSION = 3


def _face_meshes(img: Image.Image, detector, limit: int = 8):
    """(mesh points, eye centres) for every face in the photo, each measured on a crop around it."""
    import mediapipe as mp
    rgb = np.asarray(img)
    H, W = rgb.shape[:2]
    inner = getattr(detector, "_inner", detector)
    lm = getattr(inner, "_landmarker", None)
    if lm is None:
        return []
    faces = sorted(detector.detect(rgb), key=lambda f: -abs(f.eye_left[0] - f.eye_right[0]))[:limit]
    out = []
    for f in faces:
        ex, ey = (f.eye_left[0] + f.eye_right[0]) / 2, (f.eye_left[1] + f.eye_right[1]) / 2
        fh = max(abs(f.chin[1] - ey) * 2.2, abs(f.eye_left[0] - f.eye_right[0]) * 3)
        x0, y0 = int(max(0, ex - fh)), int(max(0, ey - fh))
        x1, y1 = int(min(W, ex + fh)), int(min(H, ey + fh * 1.2))
        tile = np.ascontiguousarray(rgb[y0:y1, x0:x1])
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=tile))
        if not res.face_landmarks:
            continue
        # the face nearest the tile's centre is the one we cropped around
        th, tw = tile.shape[:2]
        best = min(res.face_landmarks, key=lambda L: (L[168].x * tw + x0 - ex) ** 2 + (L[168].y * th + y0 - ey) ** 2)
        pts = np.array([(q.x * tw + x0, q.y * th + y0) for q in best], dtype=float)
        a, b = inner._eye_centres(pts)
        out.append((pts, np.array(sorted([a, b], key=lambda e: e[0]), dtype=float)))
    return out


def _measure_face(img: Image.Image, e: np.ndarray) -> dict | None:
    ed = float(np.hypot(*(e[0] - e[1])))
    if ed < 12:
        return None  # face too small to judge
    mid = e.mean(0)
    ang = float(np.degrees(np.arctan2(e[1][1] - e[0][1], e[1][0] - e[0][0])))
    box = (int(mid[0] - 1.5 * ed), int(mid[1] - 1.0 * ed), int(mid[0] + 1.5 * ed), int(mid[1] + 1.0 * ed))
    crop = img.rotate(ang, center=(float(mid[0]), float(mid[1])), resample=Image.BICUBIC).crop(box).resize((300, 200), Image.LANCZOS)
    rgb = np.asarray(crop, np.float32)
    g = np.asarray(crop.convert("L").filter(ImageFilter.GaussianBlur(0.8)), np.float32)
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    cx, cy = 150, 100  # the eyes sit at x = 100 and 200

    def P(a, x0, x1, y0, y1):
        return a[cy + y0:cy + y1, cx + x0:cx + x1]

    ref = float(np.median(P(gy, -30, 30, 45, 85)) + np.median(P(gx, -30, 30, 45, 85)) + 1)
    bridge = float(np.percentile(P(gy, -12, 12, -35, 12).max(axis=0), 50)) / ref
    rim = min(float(np.max(P(gy, x - 30, x + 30, 24, 62).mean(axis=1))) for x in (-50, 50)) / ref
    side = min(float(np.max(P(gx, a, b, -30, 40).mean(axis=0))) for a, b in ((-95, -68), (68, 95))) / ref
    # glare: near-white, colourless patches over the lenses (catchlights are far smaller)
    lum = rgb.mean(axis=2)
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    white = (lum > 238) & (sat < 22)
    glare = max(float(P(white, x - 38, x + 38, -24, 28).mean()) for x in (-50, 50))
    score = bridge * 0.5 + rim
    # Tuned on two real shoots (86 faces, 25 with glasses: clear, metal, thick and tortoiseshell
    # frames, with and without glare): bare faces scored at most 1.27, glasses at least 2.06.
    wears = bool(score >= 1.7 or glare >= 0.06)
    return {"glasses": wears, "score": round(score, 2), "bridge": round(bridge, 2), "rim": round(rim, 2),
            "side": round(side, 2), "glare": round(glare, 3)}


def measure(img: Image.Image, detector) -> dict | None:
    """Every face is checked; a photo counts if anyone in it wears glasses."""
    results = [r for _pts, e in _face_meshes(img, detector) if (r := _measure_face(img, e))]
    if not results:
        return None
    best = max(results, key=lambda r: (r["glasses"], r["score"] + r["glare"] * 20))
    return {**best, "faces": len(results), "with_glasses": sum(r["glasses"] for r in results)}


def _key(path: str) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return f"{VERSION}|{path}|{st.st_size}|{int(st.st_mtime)}"


def capture_time(path: str) -> float:
    """EXIF DateTimeOriginal when there is one, else the file date."""
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            raw = ex.get_ifd(0x8769).get(36867) or ex.get(306)
            if raw:
                from datetime import datetime
                sub = ex.get_ifd(0x8769).get(37521) or "0"
                return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S").timestamp() + float("0." + str(sub).strip()[:3] or 0)
    except Exception:
        pass
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def collection_members(found: dict[str, bool], times: dict[str, float]) -> list[str]:
    """Every glasses photo, plus the photo right after it in the same folder (shot without glasses)."""
    by_folder: dict[str, list[str]] = {}
    for p in found:
        by_folder.setdefault(str(Path(p).parent), []).append(p)
    out: list[str] = []
    for paths in by_folder.values():
        paths.sort(key=lambda p: (times.get(p, 0), Path(p).name.lower()))
        for i, p in enumerate(paths):
            if found.get(p):
                out.append(p)
                if i + 1 < len(paths):
                    out.append(paths[i + 1])
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            res.append(p)
    return res


def run(job, paths: list[str], store, detector_factory, load) -> dict:
    """Check every photo (saved answers are reused), then work out the collection."""
    found, times, todo = {}, {}, []
    for p in paths:
        k = _key(p)
        hit = store.get("glasses", k) if (store is not None and k) else None
        if hit:
            found[p], times[p] = bool(hit.get("glasses")), float(hit.get("t", 0))
        else:
            todo.append(p)
    job.update(total=len(paths), done=len(paths) - len(todo), message="Looking for glasses…")
    det = detector_factory() if todo else None
    for i, p in enumerate(todo, 1):
        if job.cancelled:
            break
        job.update(current=Path(p).name)
        try:
            src = load(Path(p))
            img = src.image
            if max(img.size) > 3000:  # plenty for a face, and much faster than a full 30 MP frame
                img = img.copy()
                img.thumbnail((3000, 3000), Image.LANCZOS)
            r = measure(img, det) or {"glasses": False, "score": 0}
        except Exception as exc:
            r = {"glasses": False, "error": f"{type(exc).__name__}: {exc}"}
        r["t"] = capture_time(p)
        found[p], times[p] = bool(r.get("glasses")), r["t"]
        k = _key(p)
        if store is not None and k:
            store.put("glasses", k, r)
        if r.get("glasses"):
            job.add_item({"path": p, **r})
        job.update(done=len(paths) - len(todo) + i)
    members = collection_members(found, times)
    return {"glasses": [p for p, v in found.items() if v], "members": members,
            "checked": len(paths), "cancelled": job.cancelled}
