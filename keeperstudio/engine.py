"""Keeper Studio's bridge to the PhotoCropper engine.

Every crop the app previews or writes goes through photocropper.pipeline, the
same code PhotoCropper runs, so framing is identical between the two apps.
Previews use the engine's own planning path with file writing switched off.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import threading
from pathlib import Path

from PIL import Image, ImageOps

from photocropper import detectors, enhance, pipeline
from photocropper.config import load as load_config

from . import jobs, library, paths

_engine_lock = threading.RLock()

# ---- straightening -----------------------------------------------------------
# A per-photo angle (degrees, clockwise) set in Crop. The engine loads every
# photo through photocropper.imageio.load; wrapping it rotates the pixels and
# trims to the largest upright rectangle (no blank corners) before detection
# and cropping, so face finding, framing and the written crops all see the
# straightened photo. Photos with no angle are untouched.
rotations: dict[str, float] = {}


def straightened_size(w: float, h: float, deg: float) -> tuple[int, int]:
    """Largest axis-aligned rectangle inside a w x h image rotated by deg."""
    import math
    a = math.radians(abs(deg))
    if a < 1e-9:
        return int(w), int(h)
    sin_a, cos_a = math.sin(a), math.cos(a)
    long_side, short_side = (w, h) if w >= h else (h, w)
    if short_side <= 2 * sin_a * cos_a * long_side or abs(sin_a - cos_a) < 1e-10:
        x = 0.5 * short_side
        wr, hr = (x / sin_a, x / cos_a) if w >= h else (x / cos_a, x / sin_a)
    else:
        cos_2a = cos_a * cos_a - sin_a * sin_a
        wr, hr = (w * cos_a - h * sin_a) / cos_2a, (h * cos_a - w * sin_a) / cos_2a
    return max(1, int(wr)), max(1, int(hr))


def straighten(img, deg: float):
    if not deg:
        return img
    w, h = img.size
    rw, rh = straightened_size(w, h, deg)
    rot = img.rotate(-deg, resample=Image.BICUBIC, expand=False)
    l, t = (w - rw) // 2, (h - rh) // 2
    return rot.crop((l, t, l + rw, t + rh))


def _install_rotation_hook():
    from photocropper import imageio as _io
    if getattr(_io.load, "_ks_wrapped", False):
        return
    orig = _io.load

    def load(path):
        src = orig(path)
        deg = rotations.get(str(path))
        if deg:
            src.image = straighten(src.image, deg)
        return src
    load._ks_wrapped = True
    _io.load = load


_install_rotation_hook()


# ---- balls and logos are not faces -------------------------------------------
# The face model sometimes reads a basketball, volleyball or a logo as a face,
# and a photo with "two faces" is sent to review. A real face sits on a body,
# so when more than one face is found, the pose model (asked for up to a few
# people) decides: faces with nobody's head at them are dropped. If the pose
# model finds no one at all, nothing is dropped and the engine decides as before.
_body_pose = None
_body_lock = threading.Lock()


def _body_heads(rgb) -> list[tuple[float, float]] | None:
    global _body_pose
    import mediapipe as mp
    import numpy as np
    with _body_lock:
        if _body_pose is None:
            cfg = config()
            if not cfg.pose_model_path:
                return None
            from mediapipe.tasks.python import BaseOptions, vision
            _body_pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(Path(cfg.pose_model_path).expanduser())),
                running_mode=vision.RunningMode.IMAGE, num_poses=6))
        res = _body_pose.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    h, w = rgb.shape[:2]
    heads = []
    for lm in res.pose_landmarks or []:
        pts = [lm[i] for i in (0, 2, 5) if getattr(lm[i], "visibility", 1.0) >= 0.3]  # nose, eyes
        if pts:
            heads.append((sum(p.x for p in pts) / len(pts) * w, sum(p.y for p in pts) / len(pts) * h))
    return heads


def real_faces(faces, rgb):
    if len(faces) < 2:
        return faces
    try:
        heads = _body_heads(rgb)
    except Exception:
        return faces
    if not heads:
        return faces
    keep = []
    for f in faces:
        ex, ey = f.eye_mid
        reach = max(f.chin[1] - ey, abs(f.eye_left[0] - f.eye_right[0])) * 1.2
        if any(((hx - ex) ** 2 + (hy - ey) ** 2) ** 0.5 <= reach for hx, hy in heads):
            keep.append(f)
    return keep or faces


class _BodyCheckedDetector:
    def __init__(self, inner):
        self._inner = inner

    def detect(self, image_rgb):
        return real_faces(list(self._inner.detect(image_rgb)), image_rgb)

    def __getattr__(self, name):
        return getattr(self._inner, name)


_orig_build = detectors.build
if not getattr(_orig_build, "_ks_wrapped", False):
    def _build(name, cfg):
        return _BodyCheckedDetector(_orig_build(name, cfg))
    _build._ks_wrapped = True
    detectors.build = _build

SETTINGS_FIELDS = (
    "preschool", "balance_feet", "bottom_margin", "enhance", "enhance_when",
    "landscape", "contact_sheets", "orders", "fit_to_frame", "disabled_sizes", "framing_style",
)
FRAMING_STYLES = ("full", "knee_above", "knee_below")
PHOTO_STYLES = ("full", "knee_above", "knee_below", "preschool")


def with_style(settings: dict, style: str | None) -> dict:
    """The batch settings with one photo's own framing style laid over them."""
    if style not in PHOTO_STYLES:
        return settings
    s = dict(settings)
    if style == "preschool":
        s["preschool"], s["framing_style"] = True, "full"
    else:
        s["preschool"], s["framing_style"] = False, style
    return s


# ---------------------------------------------------------------- config ----

def config():
    return load_config(paths.config_path())


def default_settings(cfg=None) -> dict:
    cfg = cfg or config()
    return {
        "preschool": bool(cfg.preschool),
        "balance_feet": bool(cfg.balance_feet),
        "bottom_margin": float(cfg.bottom_margin_fraction),
        "enhance": bool(cfg.enhance_enabled),
        "enhance_when": cfg.enhance_when,
        "landscape": bool(cfg.landscape_enabled),
        "contact_sheets": bool(cfg.contact_sheet.get("enabled", True)),
        "orders": bool(cfg.orders_folder),
        "fit_to_frame": bool(cfg.fit_to_frame),
        "disabled_sizes": [],
        "framing_style": "full",
    }


def merged_settings(saved: dict | None) -> dict:
    s = default_settings()
    for k, v in (saved or {}).items():
        if k in SETTINGS_FIELDS:
            s[k] = v
    return s


def sizes(cfg=None) -> list[dict]:
    cfg = cfg or config()
    out = []
    for r in cfg.ratios:
        out.append({"name": r.name, "w": r.width, "h": r.height, "kind": "portrait",
                    "own_framing": r.eye_line_fraction is not None or r.headroom_fraction is not None})
    for r in cfg.landscape_ratios:
        out.append({"name": r.name, "w": r.width, "h": r.height, "kind": "landscape", "own_framing": False})
    return out


def run_config(settings: dict):
    """The engine Config for a run with these per-run settings applied."""
    cfg = config()
    off = set(settings.get("disabled_sizes") or [])
    ratios = [r for r in cfg.ratios if r.name not in off]
    land = [r for r in cfg.landscape_ratios if r.name not in off]
    if not ratios:
        raise ValueError("Every portrait size is switched off. Turn at least one on.")
    cfg = dataclasses.replace(
        cfg,
        ratios=ratios,
        landscape_ratios=land,
        landscape_enabled=bool(settings.get("landscape")) and bool(land),
        orders_folder=(cfg.orders_folder or "Orders") if settings.get("orders") else None,
        fit_to_frame=bool(settings.get("fit_to_frame", True)),
    )
    return cfg


# A few framing numbers are offered in the app's Framing Settings dialog. They
# are written back into config.yaml in place, keeping every comment.
# (group, section, key, label, min, max, default when missing from config.yaml)
# section "ratio:NAME" is a value inside that size's entry in the ratios list.
TUNABLES = [
    ("Full length", "framing", "eye_line_fraction", "Eye line", 0.02, 0.6, None),
    ("Full length", "framing", "headroom_fraction", "Headroom", 0.0, 0.5, None),
    ("Full length", "framing", "min_headroom_fraction", "Minimum headroom (shorten to fit)", 0.0, 0.3, None),
    ("Full length", "framing", "foot_margin_fraction", "Top margin (balance feet)", 0.0, 0.4, None),
    ("3/4 length", "framing", "three_quarter_headroom_fraction", "Headroom", 0.0, 0.4, 0.12),
    ("3/4 length", "framing", "knee_offset_fraction", "Distance from the knee", 0.0, 0.6, 0.22),
    ("Preschool", "framing", "preschool_eye_line_fraction", "Eye line", 0.02, 0.6, None),
    ("Preschool", "framing", "preschool_headroom_fraction", "Headroom", 0.0, 0.5, None),
    ("Square (tight)", "ratio:3_5x3_5", "eye_line_fraction", "Eye line", 0.02, 0.8, None),
    ("Square (tight)", "ratio:3_5x3_5", "headroom_fraction", "Headroom", 0.0, 0.6, None),
    ("Group shots", "landscape", "margin_fraction", "Margin around the group", 0.0, 0.5, None),
    ("Face finding", "framing", "eye_to_chin_multiplier", "Crown estimate (eye-to-chin ×)", 0.5, 2.5, None),
    ("Face finding", "detector", "confidence_threshold", "Face detection confidence", 0.05, 0.99, None),
]
TUNE_HELP = {
    "framing.eye_line_fraction": "Where the eyes sit, as a share of the frame height from the top. Higher pulls the frame up and shows more legs.",
    "framing.headroom_fraction": "Space above the head, as a share of the frame height.",
    "framing.min_headroom_fraction": "When the frame runs off the photo, it may shrink headroom down to this before shortening.",
    "framing.foot_margin_fraction": "With Balance feet on: space above the head, matched by the space below the feet.",
    "framing.three_quarter_headroom_fraction": "Space above the head in 3/4 length, as a share of the frame height.",
    "framing.knee_offset_fraction": "How far the bottom edge sits from the knee, as a share of the thigh (above) or shin (below).",
    "framing.preschool_eye_line_fraction": "Eye line for seated preschool framing.",
    "framing.preschool_headroom_fraction": "Headroom for seated preschool framing.",
    "ratio:3_5x3_5.eye_line_fraction": "Where the eyes sit in the tight square.",
    "ratio:3_5x3_5.headroom_fraction": "Space above the head in the tight square.",
    "landscape.margin_fraction": "Space kept around the whole group in group shots.",
    "framing.eye_to_chin_multiplier": "How far above the eyes the top of the head is estimated, in eye-to-chin lengths.",
    "detector.confidence_threshold": "Lower finds more faces (including false ones); higher finds fewer.",
}


def _section_line(lines: list[str], section: str, key: str) -> int | None:
    if section.startswith("ratio:"):
        name = section.split(":", 1)[1]
        in_item = False
        for i, line in enumerate(lines):
            m = re.match(r"^\s*-\s*name\s*:\s*([^#\s]+)", line)
            if m:
                in_item = m.group(1) == name
                continue
            if re.match(r"^[A-Za-z_]", line):
                in_item = False
            if in_item and re.match(rf"^\s+{re.escape(key)}\s*:", line):
                return i
        return None
    in_sec = False
    for i, line in enumerate(lines):
        if re.match(r"^[A-Za-z_]", line):
            in_sec = line.split(":")[0].strip() == section
            continue
        if in_sec and re.match(rf"^  {re.escape(key)}\s*:", line):
            return i
    return None


def _section_end(lines: list[str], section: str) -> int | None:
    """Index just after the last line of a top-level section."""
    start = next((i for i, l in enumerate(lines) if re.match(rf"^{re.escape(section)}\s*:", l)), None)
    if start is None:
        return None
    end = start + 1
    for i in range(start + 1, len(lines)):
        if re.match(r"^[A-Za-z_]", lines[i]):
            break
        if lines[i].strip() and not lines[i].lstrip().startswith("#"):
            end = i + 1
    return end


_extra_cache: dict = {}


def tune_value(section: str, key: str, default: float) -> float:
    """A fine-tuning value read straight from config.yaml (for values the engine itself doesn't know)."""
    p = paths.config_path()
    try:
        m = p.stat().st_mtime
    except OSError:
        return default
    if _extra_cache.get("m") != m:
        _extra_cache.clear()
        _extra_cache["m"] = m
        _extra_cache["vals"] = {(t["section"], t["key"]): t["value"] for t in read_tunables()}
    v = _extra_cache["vals"].get((section, key))
    return default if v is None else v


def read_tunables() -> list[dict]:
    lines = paths.config_path().read_text(encoding="utf-8").splitlines()
    out = []
    for group, section, key, label, lo, hi, default in TUNABLES:
        i = _section_line(lines, section, key)
        val = None
        if i is not None:
            m = re.match(rf"^\s*{re.escape(key)}\s*:\s*([^#\s]+)", lines[i])
            if m:
                try:
                    val = float(m.group(1))
                except ValueError:
                    pass
        if val is None:
            val = default
        out.append({"group": group, "section": section, "key": key, "label": label, "min": lo, "max": hi,
                    "value": val, "help": TUNE_HELP.get(f"{section}.{key}", "")})
    return out


def write_tunables(values: dict) -> None:
    p = paths.config_path()
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    for _group, section, key, _label, lo, hi, _default in TUNABLES:
        k = f"{section}.{key}"
        if k not in values or values[k] is None:
            continue
        v = min(hi, max(lo, float(values[k])))
        i = _section_line(lines, section, key)
        if i is None:
            if section.startswith("ratio:"):
                continue
            end = _section_end(lines, section)  # a value config.yaml doesn't have yet: add it
            if end is None:
                continue
            lines.insert(end, f"  {key}: {v:g}")
            continue
        lines[i] = re.sub(rf"^(\s*{re.escape(key)}\s*:\s*)([^#\s]+)", lambda m: m.group(1) + f"{v:g}", lines[i])
    new = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    backup = p.with_suffix(".yaml.bak")
    shutil.copy2(p, backup)
    p.write_text(new, encoding="utf-8")
    try:
        load_config(p)  # refuse a config the engine cannot read
    except Exception:
        shutil.copy2(backup, p)
        raise
    _Resources.reset()


# ------------------------------------------------------------- resources ----

class _Resources:
    """Models kept loaded between previews (loading them takes seconds)."""

    _lock = threading.Lock()
    _key = None
    detector = None
    pose = None
    segmenter = None
    luts: dict = {}

    @classmethod
    def reset(cls):
        with cls._lock:
            for m in (cls.detector, cls.pose, cls.segmenter):
                try:
                    m and m.close()
                except Exception:
                    pass
            cls.detector = cls.pose = cls.segmenter = None
            cls.luts = {}
            cls._key = None

    @classmethod
    def ensure(cls, cfg, need_pose: bool, need_seg: bool):
        key = os.stat(paths.config_path()).st_mtime
        if cls._key != key:
            cls.reset()
            cls._key = key
        if cls.detector is None:
            cls.detector = detectors.build(cfg.detector["name"], cfg.detector)
        if need_pose and cls.pose is None and cfg.pose_model_path:
            from photocropper.pose import PoseDetector
            cls.pose = PoseDetector(cfg.pose_model_path)
        if need_seg and cls.segmenter is None and cfg.segment_model_path:
            from photocropper.segment import PersonSegmenter
            cls.segmenter = PersonSegmenter(cfg.segment_model_path)

    @classmethod
    def lut(cls, path: str | None):
        if not path:
            return None
        if path not in cls.luts:
            cls.luts[path] = enhance.load_lut(Path(path))
        return cls.luts[path]


def _lut_for(cfg, settings):
    if not settings.get("enhance"):
        return None
    path = cfg.enhance_preschool_lut_path if settings.get("preschool") else cfg.enhance_lut_path
    return _Resources.lut(path)


def graded_preview(path: str, size: int, deg: float, kind: str) -> bytes:
    """The window's preview of a photo with the standard or preschool colour preset applied."""
    import io
    cfg = config()
    lut_path = cfg.enhance_preschool_lut_path if kind == "preschool" else cfg.enhance_lut_path
    if not lut_path:
        raise FileNotFoundError("no colour preset set in config.yaml")
    key = hashlib.sha1(f"{lut_path}|{os.stat(lut_path).st_mtime}".encode()).hexdigest()[:10]
    cached = library._cache_name(path, size, f"g{key}{deg:g}")
    if cached.is_file():
        return cached.read_bytes()
    im = Image.open(io.BytesIO(library.thumbnail(path, size, deg))).convert("RGB")
    out = io.BytesIO()
    enhance.apply_lut(im, _Resources.lut(str(lut_path))).save(out, "JPEG", quality=90)
    data = out.getvalue()
    try:
        cached.write_bytes(data)
    except OSError:
        pass
    return data


def _oriented_size(path: str) -> tuple[int, int]:
    with Image.open(path) as im:
        w, h = im.size
        if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):
            w, h = h, w
    deg = rotations.get(str(path))
    return straightened_size(w, h, deg) if deg else (w, h)


def _status(result, manual) -> tuple[str, str]:
    if result.status == pipeline.OK:
        if manual:
            return "manual", "Placed by hand"
        return ("shortened", "Cropped (frame shortened to fit)") if result.adjusted else ("ok", "Cropped")
    return "review", pipeline.STATUS_LABELS.get(result.status, result.status)


REFERENCE_ASPECT = 4 / 5

# ---- hand-placed group (team) shots ---------------------------------------
# PhotoCropper frames a landscape group shot around the people it finds and
# sends it to review when it can't. A hand-placed group box takes the place of
# the found group: every landscape size is framed to contain the whole box
# (engine's group_crop_box), or, when the photo isn't tall enough for that,
# cut at the box's height and centred on it.

def group_aspect(cfg) -> float:
    return max((r.width / r.height for r in cfg.landscape_ratios), default=1.4)


def group_boxes(manual: dict, cfg, size) -> dict:
    from photocropper.geometry import group_crop_box, manual_crop_box
    a = group_aspect(cfg)
    w = manual["height"] * a
    x0 = manual["center_x"] - w / 2
    bbox = (int(round(max(0, x0))), int(round(max(0, manual["top"]))),
            int(round(min(size[0], x0 + w))), int(round(min(size[1], manual["top"] + manual["height"]))))
    out = {}
    for r in cfg.landscape_ratios:
        box = group_crop_box(bbox, size, r.width, r.height, 0.0)
        if box is None:
            box, _ = manual_crop_box(manual["center_x"], manual["top"], manual["height"], (r.width, r.height), size)
        out[r.name] = box
    return out


_tl = threading.local()  # .group_manual: {path: manual} for the export running on this thread
_orig_process_image = pipeline.process_image


def _process_image(path, detector, config, out_dir, lut=None, pose_detector=None, balance=False,
                   segmenter=None, enhance_when="before", bottom_margin=None, preschool_framing=None):
    m = (getattr(_tl, "group_manual", None) or {}).get(str(path))
    style = getattr(_tl, "framing_style", "full")
    if not m and style in ("knee_above", "knee_below") and preschool_framing is None:
        r = _three_quarter(path, detector, config, out_dir, lut, enhance_when, style)
        if r is not None:
            return r
    if not m:
        return _orig_process_image(path, detector, config, out_dir, lut=lut, pose_detector=pose_detector,
                                   balance=balance, segmenter=segmenter, enhance_when=enhance_when,
                                   bottom_margin=bottom_margin, preschool_framing=preschool_framing)
    from photocropper import imageio
    source = imageio.load(path)
    post_lut = pipeline._resolve_enhance(source, lut, enhance_when)
    written = {}
    for name, box in group_boxes(m, config, source.size).items():
        written[name] = pipeline._write_crop(source, box.as_pil(), out_dir, path.stem, name, path.suffix, config, post_lut)
    return pipeline.ImageResult(path, pipeline.OK, None, written)


pipeline.process_image = _process_image  # run_job looks it up at call time


# ---- 3/4 length ----------------------------------------------------------------
# The full-length sizes are cut across the knees instead of below the feet: the
# head keeps its headroom, the bottom edge sits a little above or below the
# knees (never on the joint itself). The knees come from the same pose model the
# balance-feet mode uses. The square keeps its own face framing.
NO_KNEES = "no_knees"
pipeline.STATUS_LABELS.setdefault(NO_KNEES, "knees not found")
THREE_QUARTER_HEADROOM = 0.12   # of the frame height, above the crown
KNEE_OFFSET = 0.22              # of the thigh (above) or shin (below) length
_KNEES, _HIPS, _ANKLES = (25, 26), (23, 24), (27, 28)


def _leg_points(rgb):
    """(hip_y, knee_y, ankle_y | None) of the one person, or None."""
    import mediapipe as mp
    import numpy as np
    pose = _Resources.pose
    if pose is None:
        return None
    h = rgb.shape[0]
    res = pose._landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    if not res.pose_landmarks:
        return None
    lm = res.pose_landmarks[0]

    def ys(ids, need=0.5):
        return [lm[i].y * h for i in ids if getattr(lm[i], "visibility", 1.0) >= need]
    knees, hips, ankles = ys(_KNEES), ys(_HIPS, 0.3), ys(_ANKLES)
    if not knees or not hips:
        return None
    hip = sum(hips) / len(hips)
    # a raised leg puts one knee higher: "above" clears the higher knee, "below" the lower one
    hi, lo = min(knees), max(knees)
    ankle = max(ankles) if ankles else None
    if hi <= hip:
        return None
    return hip, hi, lo, ankle if ankle and ankle > lo else None


def three_quarter_placement(face, legs, style, cfg, size):
    from photocropper.geometry import estimate_crown
    hip, hi, lo, ankle = legs
    thigh = hi - hip
    off = tune_value("framing", "knee_offset_fraction", KNEE_OFFSET)
    room = tune_value("framing", "three_quarter_headroom_fraction", THREE_QUARTER_HEADROOM)
    cut = hi - off * thigh if style == "knee_above" else lo + off * (ankle - lo if ankle else lo - hip)
    crown = estimate_crown(face, cfg.eye_to_chin_multiplier)[1]
    height = (cut - crown) / (1 - room)
    top = crown - room * height
    adjusted = top < 0 or cut > size[1]
    if adjusted:  # not enough photo above the head or below the cut: shorten, keep the cut line
        top = max(0.0, top)
        cut = min(float(size[1]), cut)
        height = cut - top
    return {"center_x": face.eye_mid[0], "top": top, "height": height}, adjusted


def _three_quarter(path, detector, config, out_dir, lut, enhance_when, style):
    from photocropper import imageio
    from photocropper.geometry import estimate_crown
    source = imageio.load(path)
    if config.landscape_enabled and config.landscape_ratios and source.size[0] > source.size[1]:
        return None  # group shot: framed as a group
    rgb = source.as_rgb_array()
    faces = detector.detect(rgb)
    if len(faces) != 1:
        return None  # the engine explains no face / several faces
    with _engine_lock:
        _Resources.ensure(config, True, False)
        legs = _leg_points(rgb)
    if legs is None:
        return pipeline.ImageResult(
            Path(path), NO_KNEES,
            "SKIPPED: 3/4 length framing is on, but the knees couldn't be found.\n\n"
            "Place the framing by hand, or switch Framing style back to Full length.")
    head = faces[0].chin[1] - estimate_crown(faces[0], config.eye_to_chin_multiplier)[1]
    if legs[1] - legs[0] < 0.6 * head:
        return pipeline.ImageResult(
            Path(path), NO_KNEES,
            "SKIPPED: 3/4 length framing is on, but this looks like a seated pose.\n\n"
            "Place the framing by hand, or use Preschool (seated) framing for this batch.")
    placement, adjusted = three_quarter_placement(faces[0], legs, style, config, source.size)
    res = pipeline.apply_manual_crop(Path(path), config, out_dir, placement, detector=detector, lut=lut,
                                     enhance_when=enhance_when, persist=False)
    res.adjusted = adjusted
    return res


# ---- hand-placed tight sizes (the square) ------------------------------------
# PhotoCropper's hand placement moves only the full-length sizes; the square
# keeps its own face-anchored framing and is silently skipped when that fails.
# A manual dict may carry "square": {center_x, top, height}, placed in Crop with
# S; every size with its own framing is then cut from it instead.
_orig_apply_manual = pipeline.apply_manual_crop


def _apply_manual(path, config, out_dir, manual, *, detector=None, lut=None, enhance_override=None,
                  enhance_when=None, persist=True):
    if lut is None and enhance_override is None:
        # run_job passes lut=None when the colour preset is switched off; without
        # this the engine falls back to config.yaml's default and grades anyway.
        enhance_override = False
    sq = manual.get("square") if isinstance(manual, dict) else None
    base = {k: manual[k] for k in ("center_x", "top", "height")}
    if not sq:
        res = _orig_apply_manual(path, config, out_dir, base, detector=detector, lut=lut,
                                 enhance_override=enhance_override, enhance_when=enhance_when, persist=False)
    else:
        from photocropper import imageio
        from photocropper.geometry import manual_crop_box
        own = [r for r in config.ratios if not pipeline._uses_global_framing(r)]
        cfg2 = dataclasses.replace(config, ratios=[r for r in config.ratios if pipeline._uses_global_framing(r)])
        res = _orig_apply_manual(path, cfg2, out_dir, base, detector=detector, lut=lut,
                                 enhance_override=enhance_override, enhance_when=enhance_when, persist=False)
        source = imageio.load(path)
        use_lut = lut
        if use_lut is None and enhance_override:
            use_lut = enhance.load_lut(Path(config.enhance_lut_path)) if config.enhance_lut_path else None
        post_lut = pipeline._resolve_enhance(source, use_lut, enhance_when or config.enhance_when)
        for r in own:
            box, _ = manual_crop_box(sq["center_x"], sq["top"], sq["height"], r.pair, source.size)
            res.written[r.name] = pipeline._write_crop(source, box.as_pil(), out_dir, path.stem, r.name, path.suffix, config, post_lut)
    if persist:
        pipeline.save_manual_crop(out_dir, path.stem, manual)
    return res


pipeline.apply_manual_crop = _apply_manual


# ---- remembered framing checks ---------------------------------------------
# A check is saved in the catalog under a key made from everything that can
# change its answer: the photo (path, size, date), config.yaml, the framing
# settings and any hand placement. Same inputs -> instant answer, even after a
# restart; change any of them and that photo is checked afresh.
plan_store = None  # set by the server: a Catalog
PLAN_VERSION = 2  # bump when the engine would answer differently, so saved checks are redone
_PLAN_SETTINGS = ("preschool", "balance_feet", "bottom_margin", "enhance", "enhance_when",
                  "landscape", "fit_to_frame", "disabled_sizes", "framing_style")
_focus_lock = threading.Lock()
_latest_focus = 0


def _plan_key(path: str, settings: dict, manual: dict | None) -> str | None:
    import hashlib
    try:
        st = os.stat(path)
        cfg_m = os.stat(paths.config_path()).st_mtime
    except OSError:
        return None
    sig = json.dumps([PLAN_VERSION, path, st.st_size, int(st.st_mtime), cfg_m, {k: settings.get(k) for k in _PLAN_SETTINGS}, manual, rotations.get(path, 0)],
                     sort_keys=True, default=str)
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()


def plan_cached(path: str, settings: dict, manual: dict | None = None, seq: int = 0, focus: bool = False) -> dict:
    """plan(), remembered; and stale requests skipped while the user steps fast.

    The window numbers its requests. A newer request for the photo on screen
    makes any older request still waiting for the engine pointless, so it is
    answered {"stale": true} instead of tying the engine up for seconds.
    """
    global _latest_focus
    key = _plan_key(path, settings, manual)
    if key and plan_store is not None:
        hit = plan_store.get("plans", key)
        if hit:
            return hit
    if seq:
        with _focus_lock:
            if focus and seq > _latest_focus:
                _latest_focus = seq
    with _engine_lock:
        if seq and seq < _latest_focus and not (focus and seq == _latest_focus):
            return {"path": path, "stale": True}
        result = plan(path, settings, manual)
    if key and plan_store is not None:
        try:
            plan_store.put("plans", key, result)
        except Exception:
            pass
    return result


def plan(path: str, settings: dict, manual: dict | None = None) -> dict:
    """Where every size would be cut, without writing anything."""
    if Path(path).suffix.lower() not in {".jpg", ".jpeg"}:
        return {"path": path, "status": "review", "label": "not a JPEG",
                "reason": "Print crops are made from JPEG files only (the engine keeps each JPEG's own quality settings).",
                "boxes": [], "size": list(_oriented_size(path))}
    cfg = run_config(settings)
    if manual and manual.get("kind") == "group":
        size = _oriented_size(path)
        if cfg.landscape_enabled and size[0] > size[1]:
            gb = group_boxes(manual, cfg, size)
            return {"path": path, "status": "manual", "label": "Placed by hand", "reason": None, "adjusted": False,
                    "boxes": [{"name": n, "box": [b.left, b.top, b.width, b.height], "fits": True, "kind": "landscape"} for n, b in gb.items()],
                    "size": list(size), "reference": dict(manual), "landscape": True, "ref_aspect": group_aspect(cfg)}
        manual = None  # group placement on a photo that is no longer treated as a group shot
    preschool = bool(settings.get("preschool"))
    balance = bool(settings.get("balance_feet")) and not preschool
    boxes: dict = {}
    size_holder = {}

    def hook(source, box, out_dir, stem, ratio_name, suffix):
        size_holder["size"] = source.size
        l, t, r, b = box
        boxes[ratio_name] = [l, t, r - l, b - t]
        return Path(ratio_name)

    with _engine_lock:
        _Resources.ensure(cfg, balance, cfg.landscape_enabled)
        lut = _lut_for(cfg, settings)
        pipeline._writer_hook.fn = hook
        _tl.framing_style = settings.get("framing_style") or "full"
        try:
            if manual:
                result = pipeline.apply_manual_crop(
                    Path(path), cfg, Path("."), manual, detector=_Resources.detector, lut=lut,
                    enhance_when=settings.get("enhance_when"), persist=False,
                )
            else:
                result = pipeline.process_image(
                    Path(path), _Resources.detector, cfg, Path("."), lut=lut,
                    pose_detector=_Resources.pose, balance=balance, segmenter=_Resources.segmenter,
                    enhance_when=settings.get("enhance_when") or "before",
                    bottom_margin=settings.get("bottom_margin"),
                    preschool_framing=((cfg.preschool_eye_line_fraction, cfg.preschool_headroom_fraction)
                                       if preschool else None),
                )
        finally:
            pipeline._writer_hook.fn = None
            _tl.framing_style = "full"

    size = size_holder.get("size") or _oriented_size(path)
    status, label = _status(result, manual)
    out_boxes = []
    land_names = {r.name for r in cfg.landscape_ratios}
    for r in list(cfg.ratios) + list(cfg.landscape_ratios):
        if r.name in boxes:
            out_boxes.append({"name": r.name, "box": boxes[r.name], "fits": True,
                              "kind": "landscape" if r.name in land_names else "portrait"})
    if result.solution is not None and not boxes:
        b = result.solution.box
        out_boxes.append({"name": "needed", "box": [b.left, b.top, b.width, b.height], "fits": False, "kind": "portrait"})

    # The box the Adjust tool starts from: the widest full-length crop (4:5).
    ref = None
    if manual:
        ref = dict(manual)
    else:
        globals_ = [r for r in cfg.ratios if r.eye_line_fraction is None and r.headroom_fraction is None]
        pick = next((r for r in globals_ if abs(r.width / r.height - REFERENCE_ASPECT) < 1e-6 and r.name in boxes), None) \
            or next((r for r in globals_ if r.name in boxes), None)
        if pick:
            l, t, w, h = boxes[pick.name]
            ref = {"center_x": l + w / 2, "top": t, "height": h}
        elif result.solution is not None:
            b = result.solution.box
            ref = {"center_x": b.left + b.width / 2, "top": max(0, b.top), "height": min(b.height, size[1])}
    is_group = bool(cfg.landscape_enabled and size[0] > size[1])
    if is_group and not manual:
        a = group_aspect(cfg)
        widest = max((r for r in cfg.landscape_ratios if r.name in boxes), key=lambda r: r.width / r.height, default=None)
        if widest:
            l, t, w, h = boxes[widest.name]
            ref = {"center_x": l + w / 2, "top": t, "height": h}
        else:
            h = min(size[1], size[0] / a) * 0.96
            ref = {"center_x": size[0] / 2, "top": (size[1] - h) / 2, "height": h}
    if ref is None:
        # No face to anchor on (none found, or more than one): start the Adjust
        # box as the largest 4:5 frame that fits, centred, for the user to place.
        w, h = size
        height = min(h, w / REFERENCE_ASPECT) * 0.94
        ref = {"center_x": w / 2, "top": (h - height) / 2, "height": height}
    else:
        aspect = group_aspect(cfg) if is_group else REFERENCE_ASPECT
        ref["height"] = min(ref["height"], size[1], size[0] / aspect)
        ref["top"] = max(0, min(ref["top"], size[1] - ref["height"]))
    missing = [r.name for r in cfg.ratios if result.status == pipeline.OK and not is_group and r.name not in boxes]
    return {
        "missing": missing,
        "path": path, "status": status, "label": label, "reason": result.reason,
        "adjusted": bool(getattr(result, "adjusted", False)), "boxes": out_boxes,
        "size": list(size), "reference": ref, "landscape": is_group,
        "ref_aspect": group_aspect(cfg) if is_group else REFERENCE_ASPECT,
    }


# ------------------------------------------------------------------ jobs ----

def default_output(paths_: list[str]) -> str:
    first = Path(paths_[0]).parent
    return str(first.parent / f"{first.name}_out")


def start_analyze(photo_paths: list[str], settings: dict, manual: dict, styles: dict | None = None) -> jobs.Job:
    styles = styles or {}
    def work(job):
        for i, p in enumerate(photo_paths, 1):
            if job.cancelled:
                break
            job.update(current=Path(p).name)
            try:
                r = plan_cached(p, with_style(settings, styles.get(p)), manual.get(p))
                job.add_item({"path": p, "status": r["status"], "label": r["label"], "reason": r["reason"], "plan": r})
            except Exception as exc:
                job.add_item({"path": p, "status": "review", "label": "error", "reason": f"{type(exc).__name__}: {exc}"})
            job.update(done=i)
        return {"cancelled": job.cancelled}
    return jobs.start("analyze", work, total=len(photo_paths))


def start_export_prints(photo_paths: list[str], out_dir: str, settings: dict, manual: dict,
                        styles: dict | None = None) -> jobs.Job:
    images = [Path(p) for p in photo_paths if Path(p).suffix.lower() in {".jpg", ".jpeg"}]
    skipped = [p for p in photo_paths if Path(p).suffix.lower() not in {".jpg", ".jpeg"}]
    out = Path(out_dir)
    styles = styles or {}

    def work(job):
        import time
        from photocropper import contact_sheet
        started = time.monotonic()
        out.mkdir(parents=True, exist_ok=True)
        # Hand placements made in the app become the engine's own sidecars, so
        # the run (and any later PhotoCropper run on this folder) uses them.
        group = {}
        for img in images:
            side = pipeline.manual_sidecar_path(out, img.stem)
            m = manual.get(str(img))
            if m and m.get("kind") == "group":
                group[str(img)] = m
                m = None
            if m:
                pipeline.save_manual_crop(out, img.stem, m)
            elif side.is_file():
                side.unlink()
        # Photos with their own framing style run as their own batch.
        runs: dict[str | None, list[Path]] = {}
        for img in images:
            st = styles.get(str(img))
            runs.setdefault(st if st in PHOTO_STYLES else None, []).append(img)
        job.update(message="Loading face detector…", busy=True)
        totals = {"ok": 0, "review": 0, "shortened": 0, "cancelled": False}
        sheets_by_ratio: dict[str, list] = {}
        meds = []
        offset = 0
        for st, batch in runs.items():
            if job.cancelled:
                totals["cancelled"] = True
                break
            s = with_style(settings, st)
            cfg = run_config(s)
            _tl.group_manual = group
            _tl.framing_style = s.get("framing_style") or "full"

            def progress(done, total, result, offset=offset):
                st_, label = _status(result, str(result.path) in manual)
                job.add_item({"path": str(result.path), "status": st_, "label": label, "reason": result.reason,
                              "written": {k: str(v) for k, v in result.written.items()}})
                for k, v in result.written.items():
                    sheets_by_ratio.setdefault(k, []).append((Path(v), result.path.name))
                job.update(done=offset + done, current=result.path.name, message="", busy=False)

            try:
                summary = pipeline.run_job(
                    batch, out, cfg,
                    on_progress=progress, should_cancel=lambda: job.cancelled,
                    build_sheets=False,
                    enhance_override=bool(s.get("enhance")),
                    enhance_when_override=s.get("enhance_when"),
                    balance_override=bool(s.get("balance_feet")),
                    bottom_margin_override=s.get("bottom_margin"),
                    preschool_override=bool(s.get("preschool")),
                )
            finally:
                _tl.group_manual = None
                _tl.framing_style = "full"
            offset += len(batch)
            totals["ok"] += summary.count(pipeline.OK)
            totals["review"] += len(summary.review)
            totals["shortened"] += len(summary.adjusted)
            totals["cancelled"] = totals["cancelled"] or summary.cancelled
            m = summary.framing_medians()
            if m:
                meds.append(m)
        sheets = []
        if settings.get("contact_sheets") and not totals["cancelled"]:
            ccfg = config().contact_sheet
            for name, entries in sheets_by_ratio.items():
                sh = contact_sheet.build(sorted(entries, key=lambda e: e[1].lower()), out / f"contact_sheet_{name}.png",
                                         columns=int(ccfg.get("columns", 6)), thumb_width=int(ccfg.get("thumb_width", 320)))
                if sh:
                    sheets.append(sh)
        return {
            "out_dir": str(out), "cancelled": totals["cancelled"],
            "cropped": totals["ok"], "review": totals["review"],
            "shortened": totals["shortened"], "sheets": [str(x) for x in sheets],
            "skipped_non_jpeg": skipped, "seconds": round(time.monotonic() - started, 1),
            "styles_used": len(runs),
            "medians": {"frame_heads": meds[0][0], "bottom_heads": meds[0][1]} if meds else None,
        }
    return jobs.start("prints", work, total=len(images))


def start_library_export(items: list[dict], dest: str, opts: dict) -> jobs.Job:
    """Copy originals, or resized JPEGs, into a folder; optionally a CSV."""
    out = Path(dest)

    def work(job):
        out.mkdir(parents=True, exist_ok=True)
        done = failed = 0
        for i, it in enumerate(items, 1):
            if job.cancelled:
                break
            src, name = Path(it["path"]), it["name"]
            job.update(current=src.name)
            try:
                target = out / name
                if opts.get("resize"):
                    edge, q = int(opts.get("edge", 2048)), int(opts.get("quality", 85))
                    with Image.open(src) as im:
                        icc = im.info.get("icc_profile")
                        im = ImageOps.exif_transpose(im).convert("RGB")
                        im.thumbnail((edge, edge), Image.LANCZOS)
                        im.save(target, "JPEG", quality=q, icc_profile=icc, optimize=True)
                else:
                    shutil.copy2(src, target)
                done += 1
            except Exception as exc:
                failed += 1
                job.add_item({"path": str(src), "error": f"{type(exc).__name__}: {exc}"})
            job.update(done=i)
        if opts.get("csv") and not job.cancelled:
            (out / opts.get("csv_name", "list.csv")).write_text(opts["csv"], encoding="utf-8-sig")
        return {"out_dir": str(out), "copied": done, "failed": failed, "cancelled": job.cancelled}
    return jobs.start("export", work, total=len(items))


def composite_order(students: list[str], teachers: list[str], max_per_row: int = 8, row_counts: str = "") -> dict:
    from photocropper import composite as comp
    s = sorted((Path(p) for p in students), key=comp._last_name_key)
    t = sorted((Path(p) for p in teachers), key=comp._teacher_key)
    raw = [x for x in re.split(r"[\s,]+", str(row_counts or "").strip()) if x]
    try:
        rows = [int(x) for x in raw] if raw else (comp._distribute(len(s), max(1, int(max_per_row))) if s else [])
    except ValueError:
        rows = []
    return {
        "rows": rows,
        "students": [{"path": str(p), "label": comp._label_and_order(p.stem)[1]} for p in s],
        "teachers": [{"path": str(p), "label": comp._label_and_order(p.stem)[1]} for p in t],
    }


def start_composite(opts: dict) -> jobs.Job:
    from photocropper import composite as comp

    def work(job):
        job.update(message="Finding faces and laying out the class…", busy=True)
        cfg = config()
        row_counts = opts.get("row_counts") or None
        out = comp.build_composite(
            Path(opts["background"]), Path(opts["out_path"]),
            title_lines=[opts.get("school", ""), opts.get("year", "")],
            teacher_files=[Path(p) for p in opts.get("teachers", [])],
            student_files=[Path(p) for p in opts.get("students", [])],
            title_font_path=opts["title_font"], italic_font_path=opts["teacher_font"],
            name_font_path=opts["name_font"], config=cfg,
            max_cols=int(opts.get("max_per_row", 8)), name_uppercase=bool(opts.get("uppercase")),
            row_counts=row_counts,
        )
        return {"out_path": str(out)}
    return jobs.start("composite", work, total=0)


def _model_files():
    from photoextractor import core
    home = paths.rembg_model_home()
    flat = home / f"{core.MODEL_NAME}.onnx"                       # PhotoExtractor's layout
    nested = home / "models" / core.MODEL_NAME / f"{core.MODEL_NAME}.onnx"  # newer rembg's layout
    return flat, nested


def cutout_model_ready() -> bool:
    return any(p.is_file() for p in _model_files())


def _adopt_flat_model() -> None:
    """A model copied over from PhotoExtractor sits where older rembg looked for
    it; newer rembg looks one folder deeper. Link (or copy) it there so it is
    used instead of downloading 220 MB again."""
    flat, nested = _model_files()
    if flat.is_file() and not nested.is_file():
        nested.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(flat, nested)
        except OSError:
            shutil.copy2(flat, nested)


def start_cutout(photo_paths: list[str], out_dir: str) -> jobs.Job:
    def work(job):
        from photoextractor import core
        home = paths.rembg_model_home()
        home.mkdir(parents=True, exist_ok=True)
        _adopt_flat_model()
        first = not cutout_model_ready()
        job.update(message=("Downloading the cut-out model (about 220 MB, first time only)…" if first
                            else "Loading the cut-out model…"), busy=True)
        session = core.make_session(str(home))
        job.update(message="", busy=False)
        out = Path(out_dir)
        ok = 0
        for i, p in enumerate(photo_paths, 1):
            if job.cancelled:
                break
            job.update(current=Path(p).name)
            try:
                dest = core.extract(session, Path(p), out)
                ok += 1
                job.add_item({"path": p, "output": str(dest)})
            except Exception as exc:
                job.add_item({"path": p, "error": f"{type(exc).__name__}: {exc}"})
            job.update(done=i)
        return {"out_dir": str(out), "ok": ok, "cancelled": job.cancelled}
    return jobs.start("cutout", work, total=len(photo_paths))
