"""Optional colour/tone enhancement applied before cropping.

The enhancement is a fixed editing preset captured as three per-channel 1D
lookup tables (a separable RGB curve). It was measured from a before/after pair
and reproduces that edit to within JPEG noise, so applying it here is the same
grade the photographer would apply by hand -- just batched and identical across
every image.

Kept deliberately simple: a separable per-channel LUT covers the measured
transform (per-channel curve fit R^2 = 0.996). Anything localised (skin
retouching and the like) is out of scope and is not what this does.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


class EnhanceError(Exception):
    pass


def load_lut(path: Path) -> np.ndarray:
    """Load a (3, 256) uint8 per-channel LUT saved with numpy."""
    if not path.is_file():
        raise EnhanceError(f"enhancement LUT not found: {path}")
    lut = np.load(path)
    if lut.shape != (3, 256) or lut.dtype != np.uint8:
        raise EnhanceError(
            f"enhancement LUT at {path} must be a (3, 256) uint8 array, "
            f"got shape {lut.shape} dtype {lut.dtype}"
        )
    return lut


def apply_lut(image: Image.Image, lut: np.ndarray) -> Image.Image:
    """Return a new RGB image with the per-channel LUT applied."""
    arr = np.asarray(image.convert("RGB"), np.uint8)
    graded = np.dstack([lut[i][arr[..., i]] for i in range(3)])
    return Image.fromarray(graded, mode="RGB")
