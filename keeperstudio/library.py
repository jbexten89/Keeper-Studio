"""Reading a shoot from disk: folder scans, photo details, thumbnails, previews."""

from __future__ import annotations

import hashlib
import io
import os
import threading
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from . import paths

try:  # HEIC / HEIF / Canon .HIF
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF = True
except Exception:  # pragma: no cover - optional
    HEIF = False

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".hif", ".tif", ".tiff"}
JPEG_EXT = {".jpg", ".jpeg"}

# Decoding a 30 MP frame takes real memory; cap how many happen at once so a
# fast scroll through a big shoot cannot exhaust it.
_decode_slots = threading.BoundedSemaphore(max(2, min(4, (os.cpu_count() or 4) // 2)))


def scan(folder: Path) -> dict:
    """Every photo under `folder` (recursively), plus what was skipped."""
    folder = folder.resolve()
    photos, skipped = [], {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not d.endswith("_out") and d != "_retouched")
        for name in sorted(files):
            if name.startswith("."):
                continue
            p = Path(root) / name
            ext = p.suffix.lower()
            if ext not in PHOTO_EXT or (ext in {".heic", ".heif", ".hif"} and not HEIF):
                skipped[ext or "(none)"] = skipped.get(ext or "(none)", 0) + 1
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            rel = p.relative_to(folder.parent).as_posix()
            photos.append({
                "path": str(p), "rel": rel, "name": name,
                "folder": rel.rsplit("/", 1)[0],
                "size": st.st_size, "mtime": int(st.st_mtime * 1000),
            })
    return {"root": str(folder), "name": folder.name, "photos": photos, "skipped": skipped}


def _ratio(v):
    try:
        if isinstance(v, tuple):
            return v[0] / v[1] if v[1] else None
        return float(v)
    except Exception:
        return None


def info(path: str) -> dict:
    """Pixel size (as displayed) and the camera details shown in the app."""
    out: dict = {"path": path}
    try:
        with Image.open(path) as im:
            w, h = im.size
            exif = im.getexif()
            orient = exif.get(0x0112, 1)
            if orient in (5, 6, 7, 8):
                w, h = h, w
            out["w"], out["h"] = w, h
            ifd = exif.get_ifd(0x8769) if exif else {}
            dt = ifd.get(0x9003) or ifd.get(0x9004) or exif.get(0x0132)
            if dt:
                try:
                    out["capture"] = int(datetime.strptime(str(dt).strip()[:19], "%Y:%m:%d %H:%M:%S").timestamp() * 1000)
                except ValueError:
                    pass
            e = {}
            if exif.get(0x010F): e["Make"] = str(exif.get(0x010F)).strip("\x00 ")
            if exif.get(0x0110): e["Model"] = str(exif.get(0x0110)).strip("\x00 ")
            if ifd.get(0xA434): e["LensModel"] = str(ifd.get(0xA434)).strip("\x00 ")
            for tag, key in ((0x920A, "FocalLength"), (0x829A, "ExposureTime"), (0x829D, "FNumber")):
                v = _ratio(ifd.get(tag)) if ifd.get(tag) is not None else None
                if v:
                    e[key] = v
            iso = ifd.get(0x8827)
            if isinstance(iso, (tuple, list)):
                iso = iso[0] if iso else None
            if iso:
                e["ISO"] = int(iso)
            out["exif"] = e
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _cache_name(path: str, size: int, kind: str) -> Path:
    try:
        st = os.stat(path)
        sig = f"{path}|{st.st_size}|{int(st.st_mtime)}|{size}|{kind}"
    except OSError:
        sig = f"{path}|{size}|{kind}"
    return paths.thumbs_dir() / (hashlib.sha1(sig.encode("utf-8")).hexdigest() + ".jpg")


def _render(path: str, size: int, deg: float = 0.0) -> bytes:
    with _decode_slots:
        with Image.open(path) as im:
            if im.format == "JPEG":
                im.draft("RGB", (size * 2, size * 2))  # decode at reduced scale: much faster
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            if deg:
                from .engine import straighten
                # rotate a reduced copy (fast); same geometry as the full-size crop
                im.thumbnail((size * 2, size * 2), Image.LANCZOS)
                im = straighten(im, deg)
            im.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=86 if size <= 600 else 90)
            return buf.getvalue()


def thumbnail(path: str, size: int = 400, deg: float = 0.0) -> bytes:
    """A cached, orientation-corrected JPEG of at most size x size."""
    cached = _cache_name(path, size, f"t{deg:g}" if deg else "t")
    if cached.is_file():
        return cached.read_bytes()
    data = _render(path, size, deg)
    try:
        tmp = cached.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cached)
    except OSError:
        pass
    return data


def full_image(path: str) -> tuple[bytes, str]:
    """The photo at full resolution in a form the window can show.

    JPEG, PNG and WebP are sent untouched (the window honours EXIF orientation
    itself); HEIC and TIFF are converted once and cached.
    """
    ext = Path(path).suffix.lower()
    if ext in JPEG_EXT:
        return Path(path).read_bytes(), "image/jpeg"
    if ext == ".png":
        return Path(path).read_bytes(), "image/png"
    if ext == ".webp":
        return Path(path).read_bytes(), "image/webp"
    cached = _cache_name(path, 0, "full")
    if cached.is_file():
        return cached.read_bytes(), "image/jpeg"
    with _decode_slots:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=94)
    data = buf.getvalue()
    try:
        cached.write_bytes(data)
    except OSError:
        pass
    return data, "image/jpeg"
