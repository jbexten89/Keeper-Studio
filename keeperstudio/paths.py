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


def config_path() -> Path:
    return app_dir() / "config.yaml"


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
