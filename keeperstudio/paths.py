"""Where Keeper Studio keeps its files.

The app folder (beside the exe when packaged, the repo root from source) holds
config.yaml, models/ and luts/, exactly like PhotoCropper, so framing stays
editable without a rebuild. Per-user data (the catalog of flags/ratings/
collections and the thumbnail cache) lives in the user's app-data folder, so it
survives reinstalling or updating the app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """Read-only files shipped inside the app (the UI)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "KeeperStudio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def shipped_config_path() -> Path:
    """The config.yaml that comes with the app (replaced by every new build)."""
    return app_dir() / "config.yaml"


_user_cfg = {"seen": None}


def config_path() -> Path:
    """Your framing settings: a copy of the app's config.yaml kept in your user
    folder, so a new build never resets them. Fine-tune framing values are also
    saved on their own (framing-settings.json) and put back on every new build's
    copy; file paths in it (models, looks) point back into the app folder."""
    user = data_dir() / "config.yaml"
    ship = shipped_config_path()
    try:
        st = ship.stat()
        seen = (st.st_mtime, st.st_size)
    except OSError:
        return user if user.exists() else ship
    if _user_cfg["seen"] == seen and user.exists():
        return user
    import hashlib
    h = hashlib.sha1(ship.read_bytes()).hexdigest()
    mark = data_dir() / "config.shipped"
    if not user.exists() or (mark.read_text().strip() if mark.exists() else "") != h:
        _make_user_config(ship, user)
        mark.write_text(h)
    _user_cfg["seen"] = seen
    return user


def _make_user_config(ship: Path, user: Path) -> None:
    import json
    import re
    base = ship.parent
    lines = []
    for line in ship.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\s*\w*(?:model_path|lut_path)\s*:\s*)([^#\s]+)(.*)$", line)
        if m and m.group(2) not in ("null", "~", "''", '""') and not Path(m.group(2)).is_absolute():
            line = f"{m.group(1)}{(base / m.group(2)).resolve().as_posix()}{m.group(3)}"
        lines.append(line)
    text = "# Your copy of Keeper Studio's settings (made from the app's config.yaml).\n" \
           "# Fine-tune framing values are kept across new builds; other hand edits last until the next build.\n" + "\n".join(lines) + "\n"
    tmp = user.with_suffix(".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(user)
    try:
        saved = json.loads((data_dir() / "framing-settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if saved:
        from . import engine  # put your Fine-tune values back into the fresh copy
        engine.write_tunables(saved, remember=False, path=user)


def thumbs_dir() -> Path:
    d = data_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def catalog_path() -> Path:
    return data_dir() / "catalog.sqlite3"


def rembg_model_home() -> Path:
    """Where the extraction models live: in the data folder, so a new build
    (a new app folder) reuses them instead of downloading 220 MB again."""
    return data_dir() / "models" / "rembg"


def legacy_rembg_model_home() -> Path:
    """Where older builds downloaded the model: beside the exe."""
    return app_dir() / "models" / "rembg"
