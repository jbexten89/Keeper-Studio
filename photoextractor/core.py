"""Background removal: subject -> transparent PNG, using rembg (BiRefNet).

The model and its home directory are resolved so this works both from source and
from a frozen one-dir build (where the model is bundled beside the exe).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}

# BiRefNet general (lite): RemoveBG-class edges on hair/pom-poms, ~224 MB.
MODEL_NAME = "birefnet-general-lite"


def default_model_home() -> str:
    """Directory holding <MODEL_NAME>.onnx, for both source and frozen runs."""
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).resolve().parent / "models" / "rembg"
        if beside.is_dir():
            return str(beside)
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return str(Path(bundled) / "models" / "rembg")
    return str(Path(__file__).resolve().parent.parent / "models" / "rembg")


def find_images(folder: Path) -> list[Path]:
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix in IMAGE_SUFFIXES),
        key=lambda p: p.name,
    )


def make_session(model_home: str | None = None, model_name: str = MODEL_NAME):
    """Create the rembg session. Offline as long as the model is present in
    model_home (rembg verifies the file and skips downloading)."""
    os.environ["U2NET_HOME"] = model_home or default_model_home()
    from rembg import new_session

    return new_session(model_name)


def extract(session, in_path: Path, out_dir: Path) -> Path:
    """Cut out the subject and write a transparent PNG (source stem, .png)."""
    from rembg import remove

    image = Image.open(in_path).convert("RGB")
    cut = remove(image, session=session, post_process_mask=True)  # RGBA
    destination = out_dir / f"{in_path.stem}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    cut.save(destination)
    return destination


@dataclass
class ExtractResult:
    path: Path
    output: Path | None
    ok: bool
    error: str | None = None


def run(
    images: Iterable[Path],
    out_dir: Path,
    *,
    model_home: str | None = None,
    on_progress: Callable[[int, int, ExtractResult], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[ExtractResult]:
    images = list(images)
    total = len(images)
    session = make_session(model_home)
    results: list[ExtractResult] = []
    for index, path in enumerate(images, start=1):
        if should_cancel is not None and should_cancel():
            break
        try:
            dest = extract(session, path, out_dir)
            result = ExtractResult(path, dest, True)
        except Exception as exc:  # one bad frame must not kill the batch
            result = ExtractResult(path, None, False, f"{type(exc).__name__}: {exc}")
        results.append(result)
        if on_progress is not None:
            on_progress(index, total, result)
    return results
