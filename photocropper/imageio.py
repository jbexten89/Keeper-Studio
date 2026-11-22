"""Image loading and saving with EXIF / ICC preservation.

Two things this module is careful about:

EXIF ORIENTATION. A camera may store pixels rotated and record the correction
in EXIF. Landmarks would then be detected in a different frame than the one a
person sees, and the crop would be wrong. Images are therefore transposed into
display orientation before detection, cropped there, and written with
Orientation reset to 1 -- so the file on disk needs no further correction.

RE-ENCODING. Crops are written with the source's own quantisation tables
(`quality="keep"`), so the output is not re-compressed at a different quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import piexif
from PIL import Image, ImageOps

JPEG_SUFFIXES = {".jpg", ".jpeg", ".JPG", ".JPEG"}


@dataclass
class LoadedImage:
    image: Image.Image
    """RGB, already transposed into display orientation."""
    exif_bytes: bytes | None
    icc_profile: bytes | None
    path: Path
    quantization: dict | None = None
    """The source JPEG's quantisation tables, captured before the image was
    transposed. Transposing and converting return copies that drop them, which
    would make Pillow's `quality="keep"` fail and silently re-encode."""
    subsampling: int = -1
    """The source JPEG's chroma subsampling, -1 if unknown."""

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def as_rgb_array(self) -> np.ndarray:
        return np.asarray(self.image, dtype=np.uint8)


def find_images(folder: Path) -> list[Path]:
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix in JPEG_SUFFIXES),
        key=lambda p: p.name,
    )


def load(path: Path) -> LoadedImage:
    image = Image.open(path)
    icc_profile = image.info.get("icc_profile")
    exif_bytes = image.info.get("exif")

    # Capture encoding parameters while this is still the original JPEG object.
    quantization = getattr(image, "quantization", None)
    try:
        from PIL import JpegImagePlugin

        subsampling = JpegImagePlugin.get_sampling(image)
    except Exception:
        subsampling = -1

    # Bake orientation into the pixels so detection and display agree.
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")

    return LoadedImage(
        image=image,
        exif_bytes=exif_bytes,
        icc_profile=icc_profile,
        path=path,
        quantization=quantization,
        subsampling=subsampling,
    )


def _rewrite_exif(exif_bytes: bytes | None, size: tuple[int, int]) -> bytes | None:
    """Update EXIF to describe the cropped file rather than the original.

    Orientation is reset to 1 (pixels are now upright), the recorded pixel
    dimensions are corrected, and the embedded thumbnail is dropped because it
    still shows the uncropped frame. On any parse failure the original bytes
    are passed through untouched -- preserving imperfect metadata beats losing
    it.
    """
    if not exif_bytes:
        return None

    width, height = size
    try:
        exif = piexif.load(exif_bytes)
        exif["0th"][piexif.ImageIFD.Orientation] = 1
        exif["0th"][piexif.ImageIFD.ImageWidth] = width
        exif["0th"][piexif.ImageIFD.ImageLength] = height
        exif["Exif"][piexif.ExifIFD.PixelXDimension] = width
        exif["Exif"][piexif.ExifIFD.PixelYDimension] = height
        exif["thumbnail"] = None
        exif["1st"] = {}
        return piexif.dump(exif)
    except Exception:
        return exif_bytes


def save_crop(
    source: LoadedImage,
    box: tuple[int, int, int, int],
    destination: Path,
    *,
    jpeg_quality: object = "keep",
    jpeg_subsampling: object = "keep",
    post_lut=None,
) -> None:
    """Crop and write. Pixels are copied, never resampled or scaled.

    `post_lut` applies the colour preset to the crop AFTER cropping (used when
    enhancement is configured to run after the crop rather than on the whole
    source). For a per-channel LUT this yields the same pixels either way.
    """
    cropped = source.image.crop(box)
    if post_lut is not None:
        from .enhance import apply_lut

        cropped = apply_lut(cropped, post_lut)
    destination.parent.mkdir(parents=True, exist_ok=True)

    save_kwargs: dict = {}
    exif = _rewrite_exif(source.exif_bytes, cropped.size)
    if exif:
        save_kwargs["exif"] = exif
    if source.icc_profile:
        save_kwargs["icc_profile"] = source.icc_profile

    if jpeg_quality == "keep" and source.quantization:
        # Reuse the source's own tables rather than re-quantising. Pillow's
        # quality="keep" cannot be used directly because the image has been
        # transposed and is no longer the object loaded from the JPEG.
        save_kwargs["qtables"] = source.quantization
        save_kwargs["subsampling"] = (
            source.subsampling if jpeg_subsampling == "keep" else jpeg_subsampling
        )
    else:
        save_kwargs["quality"] = 95 if jpeg_quality == "keep" else jpeg_quality
        save_kwargs["subsampling"] = (
            source.subsampling if jpeg_subsampling == "keep" else jpeg_subsampling
        )

    try:
        cropped.save(destination, format="JPEG", **save_kwargs)
    except (ValueError, OSError):
        # Malformed tables or an unusable subsampling value: re-encode high.
        for key in ("qtables", "subsampling"):
            save_kwargs.pop(key, None)
        save_kwargs["quality"] = 95
        cropped.save(destination, format="JPEG", subsampling="4:4:4", **save_kwargs)


def copy_for_review(source_path: Path, review_dir: Path, reason: str) -> None:
    """Copy an unprocessable original to review/ with a sidecar explaining why."""
    import shutil

    review_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, review_dir / source_path.name)
    sidecar = review_dir / (source_path.name + ".txt")
    sidecar.write_text(reason.rstrip() + "\n", encoding="utf-8")
