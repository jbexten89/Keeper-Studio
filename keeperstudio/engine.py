"""Keeper Studio's bridge to the PhotoCropper engine.

Every crop the app previews or writes goes through photocropper.pipeline, the
same code PhotoCropper runs, so framing is identical between the two apps.
Previews use the engine's own planning path with file writing switched off.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import threading
from pathlib import Path

from PIL import Image, ImageOps

from photocropper import detectors, enhance, pipeline
from photocropper.config import load as load_config

from . import jobs, paths

_engine_lock = threading.RLock()

SETTINGS_FIELDS = (
    "preschool", "balance_feet", "bottom_margin", "enhance", "enhance_when",
    "landscape", "contact_sheets", "orders", "fit_to_frame", "disabled_sizes",
)


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
TUNABLES = [
    ("framing", "eye_line_fraction", "Eye line (full-length)", 0.02, 0.6),
    ("framing", "headroom_fraction", "Headroom (full-length)", 0.0, 0.5),
    ("framing", "eye_to_chin_multiplier", "Crown estimate (eye-to-chin ×)", 0.5, 2.5),
    ("framing", "min_headroom_fraction", "Minimum headroom", 0.0, 0.3),
    ("framing", "preschool_eye_line_fraction", "Eye line (preschool)", 0.02, 0.6),
    ("framing", "preschool_headroom_fraction", "Headroom (preschool)", 0.0, 0.5),
    ("framing", "foot_margin_fraction", "Top margin (balance feet)", 0.0, 0.4),
    ("detector", "confidence_threshold", "Face detection confidence", 0.05, 0.99),
    ("landscape", "margin_fraction", "Group shot margin", 0.0, 0.5),
]


def _section_line(lines: list[str], section: str, key: str) -> int | None:
    in_sec = False
    for i, line in enumerate(lines):
        if re.match(r"^[A-Za-z_]", line):
            in_sec = line.split(":")[0].strip() == section
            continue
        if in_sec and re.match(rf"^  {re.escape(key)}\s*:", line):
            return i
    return None


def read_tunables() -> list[dict]:
    lines = paths.config_path().read_text(encoding="utf-8").splitlines()
    out = []
    for section, key, label, lo, hi in TUNABLES:
        i = _section_line(lines, section, key)
        val = None
        if i is not None:
            m = re.match(rf"^\s*{re.escape(key)}\s*:\s*([^#\s]+)", lines[i])
            if m:
                try:
                    val = float(m.group(1))
                except ValueError:
                    pass
        out.append({"section": section, "key": key, "label": label, "min": lo, "max": hi, "value": val})
    return out


def write_tunables(values: dict) -> None:
    p = paths.config_path()
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    for section, key, _label, lo, hi in TUNABLES:
        k = f"{section}.{key}"
        if k not in values or values[k] is None:
            continue
        v = min(hi, max(lo, float(values[k])))
        i = _section_line(lines, section, key)
        if i is None:
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


def _oriented_size(path: str) -> tuple[int, int]:
    with Image.open(path) as im:
        w, h = im.size
        if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):
            w, h = h, w
    return w, h


def _status(result, manual) -> tuple[str, str]:
    if result.status == pipeline.OK:
        if manual:
            return "manual", "Placed by hand"
        return ("shortened", "Cropped (frame shortened to fit)") if result.adjusted else ("ok", "Cropped")
    return "review", pipeline.STATUS_LABELS.get(result.status, result.status)


REFERENCE_ASPECT = 4 / 5


def plan(path: str, settings: dict, manual: dict | None = None) -> dict:
    """Where every size would be cut, without writing anything."""
    if Path(path).suffix.lower() not in {".jpg", ".jpeg"}:
        return {"path": path, "status": "review", "label": "not a JPEG",
                "reason": "Print crops are made from JPEG files only (the engine keeps each JPEG's own quality settings).",
                "boxes": [], "size": list(_oriented_size(path))}
    cfg = run_config(settings)
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
    return {
        "path": path, "status": status, "label": label, "reason": result.reason,
        "adjusted": bool(getattr(result, "adjusted", False)), "boxes": out_boxes,
        "size": list(size), "reference": ref, "landscape": bool(boxes) and all(n in land_names for n in boxes),
    }


# ------------------------------------------------------------------ jobs ----

def default_output(paths_: list[str]) -> str:
    first = Path(paths_[0]).parent
    return str(first.parent / f"{first.name}_out")


def start_analyze(photo_paths: list[str], settings: dict, manual: dict) -> jobs.Job:
    def work(job):
        for i, p in enumerate(photo_paths, 1):
            if job.cancelled:
                break
            job.update(current=Path(p).name)
            try:
                r = plan(p, settings, manual.get(p))
                job.add_item({"path": p, "status": r["status"], "label": r["label"], "reason": r["reason"]})
            except Exception as exc:
                job.add_item({"path": p, "status": "review", "label": "error", "reason": f"{type(exc).__name__}: {exc}"})
            job.update(done=i)
        return {"cancelled": job.cancelled}
    return jobs.start("analyze", work, total=len(photo_paths))


def start_export_prints(photo_paths: list[str], out_dir: str, settings: dict, manual: dict) -> jobs.Job:
    images = [Path(p) for p in photo_paths if Path(p).suffix.lower() in {".jpg", ".jpeg"}]
    skipped = [p for p in photo_paths if Path(p).suffix.lower() not in {".jpg", ".jpeg"}]
    out = Path(out_dir)

    def work(job):
        cfg = run_config(settings)
        out.mkdir(parents=True, exist_ok=True)
        # Hand placements made in the app become the engine's own sidecars, so
        # the run (and any later PhotoCropper run on this folder) uses them.
        for img in images:
            side = pipeline.manual_sidecar_path(out, img.stem)
            m = manual.get(str(img))
            if m:
                pipeline.save_manual_crop(out, img.stem, m)
            elif side.is_file():
                side.unlink()
        job.update(message="Loading face detector…", busy=True)
        statuses = {}

        def progress(done, total, result):
            st, label = _status(result, str(result.path) in manual)
            statuses[str(result.path)] = st
            job.add_item({"path": str(result.path), "status": st, "label": label, "reason": result.reason,
                          "written": {k: str(v) for k, v in result.written.items()}})
            job.update(done=done, current=result.path.name, message="", busy=False)

        summary = pipeline.run_job(
            images, out, cfg,
            on_progress=progress, should_cancel=lambda: job.cancelled,
            build_sheets=bool(settings.get("contact_sheets")),
            enhance_override=bool(settings.get("enhance")),
            enhance_when_override=settings.get("enhance_when"),
            balance_override=bool(settings.get("balance_feet")),
            bottom_margin_override=settings.get("bottom_margin"),
            preschool_override=bool(settings.get("preschool")),
        )
        med = summary.framing_medians()
        return {
            "out_dir": str(out), "cancelled": summary.cancelled,
            "cropped": summary.count(pipeline.OK), "review": len(summary.review),
            "shortened": len(summary.adjusted), "sheets": [str(s) for s in summary.sheets],
            "skipped_non_jpeg": skipped,
            "medians": {"frame_heads": med[0], "bottom_heads": med[1]} if med else None,
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
