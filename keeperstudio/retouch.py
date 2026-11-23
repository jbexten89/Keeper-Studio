"""Retouch: swap the eyes from a no-glasses frame into a photo with glasses glare.

The photographer's own Photoshop routine, automated:
  copy the eyes from the no-glasses frame -> paste as a layer -> line it up at
  50% -> hidden layer mask -> brush the eyes back in.

Here the frames are lined up from face landmarks (both eyes and the chin), the
user confirms or nudges the alignment, paints the mask, and the result is saved
as a copy in a `_retouched` folder beside the photo. The camera file is never
changed. Everything downstream (previews, Crop, Composite, Extract) uses the
retouched copy when there is one, via `source_path`.
"""
from __future__ import annotations

import base64
import io
import json
import math
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

EDIT_DIR = "_retouched"

_sessions: dict[str, dict] = {}
_lock = threading.Lock()


# ---- where retouched copies live -------------------------------------------------
def edit_file(path: str | Path) -> Path:
    p = Path(path)
    return p.parent / EDIT_DIR / p.name


def side_file(path: str | Path) -> Path:
    p = Path(path)
    return p.parent / EDIT_DIR / f"{p.stem}.retouch.json"


def mask_file(path: str | Path) -> Path:
    p = Path(path)
    return p.parent / EDIT_DIR / f"{p.stem}.mask.png"


def source_path(path: str | Path) -> str:
    """The file to read for a photo: its retouched copy when there is one."""
    e = edit_file(path)
    return str(e) if e.is_file() else str(path)


def info(paths: list[str]) -> dict:
    """Which photos are retouched, and which photos were used as eye donors."""
    edits, donors = {}, {}
    for p in paths:
        e = edit_file(p)
        if not e.is_file():
            continue
        meta = {}
        try:
            meta = json.loads(side_file(p).read_text(encoding="utf-8"))
        except Exception:
            pass
        edits[p] = {"mtime": int(e.stat().st_mtime), "donor": meta.get("donor")}
        if meta.get("donor"):
            donors[meta["donor"]] = p
    return {"edits": edits, "donors": donors}


# ---- geometry --------------------------------------------------------------------
def _similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares rotation + uniform scale + shift taking src points to dst (3x3)."""
    ms, md = src.mean(0), dst.mean(0)
    s, d = src - ms, dst - md
    a = (s[:, 0] * d[:, 0] + s[:, 1] * d[:, 1]).sum()
    b = (s[:, 0] * d[:, 1] - s[:, 1] * d[:, 0]).sum()
    n = (s ** 2).sum()
    a, b = a / n, b / n
    m = np.array([[a, -b, 0.0], [b, a, 0.0], [0, 0, 1.0]])
    m[:2, 2] = md - m[:2, :2] @ ms
    return m


def _adjust(adj: dict, w: int, h: int) -> np.ndarray:
    """The user's nudge: scale and rotate about the region centre, then shift."""
    s = float(adj.get("s", 1) or 1)
    r = math.radians(float(adj.get("r", 0) or 0))
    dx, dy = float(adj.get("dx", 0) or 0), float(adj.get("dy", 0) or 0)
    cx, cy = w / 2, h / 2
    c, sn = math.cos(r) * s, math.sin(r) * s
    return np.array([[c, -sn, cx - c * cx + sn * cy + dx],
                     [sn, c, cy - sn * cx - c * cy + dy],
                     [0, 0, 1.0]])


def _warp(img: Image.Image, donor_to_out: np.ndarray, size: tuple[int, int]) -> Image.Image:
    inv = np.linalg.inv(donor_to_out)
    return img.transform(size, Image.AFFINE, tuple(inv[:2].ravel()), resample=Image.BICUBIC)


# Mesh points glare can't hide: nose, mouth, chin, jaw, cheeks and forehead.
# (Eye, lid and brow points are left out: behind glare they are guesses.)
STABLE = [1, 2, 4, 5, 6, 19, 94, 168, 195, 197, 0, 13, 14, 17, 61, 291, 78, 308,
          152, 148, 377, 176, 400, 10, 151, 109, 338, 234, 454, 93, 323, 132, 361, 58, 288, 205, 425]


def _mesh(detector, img: Image.Image):
    """Full face mesh (478 points) of the main face, measured on a crop around it for precision."""
    import mediapipe as mp
    rgb = np.asarray(img)
    faces = detector.detect(rgb)
    if not faces:
        return None
    f = max(faces, key=lambda f: abs(f.eye_left[0] - f.eye_right[0]) + abs(f.chin[1] - f.eye_left[1]))
    ex, ey = (f.eye_left[0] + f.eye_right[0]) / 2, (f.eye_left[1] + f.eye_right[1]) / 2
    fh = max(abs(f.chin[1] - ey) * 2.2, abs(f.eye_left[0] - f.eye_right[0]) * 3)
    H, W = rgb.shape[:2]
    x0, y0 = int(max(0, ex - fh)), int(max(0, ey - fh))
    x1, y1 = int(min(W, ex + fh)), int(min(H, ey + fh * 1.2))
    inner = getattr(detector, "_inner", detector)
    lm = getattr(inner, "_landmarker", None)
    if lm is None:
        return None
    tile = np.ascontiguousarray(rgb[y0:y1, x0:x1])
    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=tile))
    if not res.face_landmarks:
        return None
    th, tw = tile.shape[:2]
    pts = np.array([(p.x * tw + x0, p.y * th + y0) for p in res.face_landmarks[0]], dtype=float)
    a, b = inner._eye_centres(pts)
    eyes = np.array(sorted([a, b], key=lambda e: e[0]), dtype=float)
    return pts, eyes


def _jpeg(img: Image.Image, q: int = 92) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, "JPEG", quality=q)
    return b.getvalue()


# ---- the session: prepare, preview, save -----------------------------------------
def prepare(path: str, donor: str, detector, raw_load) -> dict:
    """Line the donor frame up with the photo and cut out the working area."""
    tgt = raw_load(Path(path))
    don = raw_load(Path(donor))
    W, H = tgt.image.size
    tm, dm = _mesh(detector, tgt.image), _mesh(detector, don.image)
    found = bool(tm and dm)
    if found:
        # line the frames up on the parts of the face glare can't hide...
        base = _similarity(dm[0][STABLE], tm[0][STABLE])
        # ...and take the eye positions from the clear frame, carried across
        eyes = (np.c_[dm[1], np.ones(2)] @ base.T)[:, :2]
    else:
        # No face in one of them: start from "same spot, same size" and let the user line it up.
        sx, sy = W / don.image.size[0], H / don.image.size[1]
        base = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1.0]])
        if tm:
            eyes = tm[1]
        elif dm:
            eyes = (np.c_[dm[1], np.ones(2)] @ base.T)[:, :2]
        else:
            eyes = np.array([[W * 0.46, H * 0.3], [W * 0.54, H * 0.3]])
    ed = float(np.hypot(*(eyes[0] - eyes[1])))
    mid = eyes.mean(0)
    rw, rh = 2.7 * ed, 1.6 * ed
    x0 = int(max(0, min(W - 1, mid[0] - rw / 2)))
    y0 = int(max(0, min(H - 1, mid[1] + 0.05 * ed - rh / 2)))
    x1 = int(min(W, mid[0] + rw / 2))
    y1 = int(min(H, mid[1] + 0.05 * ed + rh / 2))
    w, h = max(8, x1 - x0), max(8, y1 - y0)
    pad = int(0.3 * min(w, h))
    to_region = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1.0]]) @ base
    to_padded = np.array([[1, 0, pad], [0, 1, pad], [0, 0, 1.0]]) @ to_region
    region = tgt.image.crop((x0, y0, x0 + w, y0 + h))
    donor_prev = _warp(don.image, to_padded, (w + 2 * pad, h + 2 * pad))
    sid = uuid.uuid4().hex[:12]
    saved_adj, saved_mask = None, None
    try:
        meta = json.loads(side_file(path).read_text(encoding="utf-8"))
        if meta.get("donor") == donor and meta.get("region") == [x0, y0, w, h]:
            saved_adj = meta.get("adjust")
            if mask_file(path).is_file():
                saved_mask = "data:image/png;base64," + base64.b64encode(mask_file(path).read_bytes()).decode()
    except Exception:
        pass
    with _lock:
        for k in [k for k, v in _sessions.items() if time.time() - v["t"] > 3600]:
            _sessions.pop(k, None)
        _sessions[sid] = {"t": time.time(), "path": path, "donor": donor, "region": (x0, y0, w, h),
                          "base": base, "imgs": {"target": _jpeg(region, 94), "donor": _jpeg(donor_prev, 94)}}
    lens = [[float(x - x0), float(y - y0 + 0.04 * ed)] for x, y in eyes]
    return {"id": sid, "found": found, "region": [x0, y0, w, h], "pad": pad, "ed": ed / 1.0,
            "eyes": lens, "lens_r": [0.46 * ed, 0.34 * ed], "adjust": saved_adj, "mask": saved_mask}


def image(sid: str, which: str) -> bytes:
    with _lock:
        s = _sessions.get(sid)
    if not s:
        raise KeyError("retouch session expired - open the photo in Retouch again")
    return s["imgs"][which]


def _match_colour(don: np.ndarray, tgt: np.ndarray) -> np.ndarray:
    """Even out exposure/colour between frames, measured on skin above and below the eyes."""
    h = tgt.shape[0]
    band = max(2, int(h * 0.18))
    rows = np.r_[0:band, h - band:h]
    t, d = tgt[rows].reshape(-1, 3).astype(np.float32), don[rows].reshape(-1, 3).astype(np.float32)
    out = don.astype(np.float32)
    for c in range(3):
        sd, st = d[:, c].std() + 1e-3, t[:, c].std() + 1e-3
        g = float(np.clip(st / sd, 0.85, 1.2))
        out[..., c] = (out[..., c] - d[:, c].mean()) * g + t[:, c].mean()
    return np.clip(out, 0, 255)


def save(path: str, sid: str, adjust: dict, mask_png: str, match: bool, raw_load) -> dict:
    from photocropper import imageio
    with _lock:
        s = _sessions.get(sid)
    if not s or s["path"] != path:
        raise KeyError("retouch session expired - open the photo in Retouch again")
    x0, y0, w, h = s["region"]
    raw = base64.b64decode(mask_png.split(",", 1)[1])
    m = Image.open(io.BytesIO(raw)).convert("RGBA").split()[-1]
    if m.size != (w, h):
        m = m.resize((w, h), Image.BILINEAR)
    mask = np.asarray(m, dtype=np.float32)[..., None] / 255.0
    tgt = raw_load(Path(path))
    don = raw_load(Path(s["donor"]))
    to_region = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1.0]]) @ s["base"]
    donor_reg = np.asarray(_warp(don.image, _adjust(adjust, w, h) @ to_region, (w, h)), dtype=np.float32)
    region = np.asarray(tgt.image.crop((x0, y0, x0 + w, y0 + h)), dtype=np.float32)
    if match:
        donor_reg = _match_colour(donor_reg, region)
    out = region * (1 - mask) + donor_reg * mask
    img = tgt.image.copy()
    img.paste(Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB"), (x0, y0))
    dest = edit_file(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    kw = {"quality": 95, "subsampling": 0}
    ex = imageio._rewrite_exif(tgt.exif_bytes, img.size)
    if ex:
        kw["exif"] = ex
    if tgt.icc_profile:
        kw["icc_profile"] = tgt.icc_profile
    tmp = dest.with_suffix(".tmp.jpg")
    img.save(tmp, "JPEG", **kw)
    tmp.replace(dest)
    mask_file(path).write_bytes(raw)
    side_file(path).write_text(json.dumps({
        "donor": s["donor"], "region": [x0, y0, w, h], "adjust": adjust, "match": match,
        "original": Path(path).name, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, indent=2), encoding="utf-8")
    return {"edited": str(dest)}


def remove(path: str) -> dict:
    gone = []
    for f in (edit_file(path), side_file(path), mask_file(path)):
        if f.is_file():
            f.unlink()
            gone.append(f.name)
    d = edit_file(path).parent
    try:
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    except OSError:
        pass
    return {"removed": gone}
