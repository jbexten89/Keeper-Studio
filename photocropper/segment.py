"""Group localisation via MediaPipe DeepLab person segmentation.

Landscape group shots are framed around the group's outline, so the cropper
needs the group's bounding box (top of heads, bottom, and both sides). DeepLab's
person class gives a person mask for the whole scene; its bounding box is all
that is needed here -- edge precision does not matter, only the extent.

Groups too small/distant to segment confidently return None, so the caller can
route them to review rather than cropping from a garbage box.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

PERSON_CLASS = 15  # Pascal VOC person class in DeepLab


class PersonSegmenter:
    def __init__(self, model_path: str, *, min_area_fraction: float = 0.01):
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision

        path = Path(model_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(
                f"segmentation model not found at {path}. Download deeplab_v3.tflite "
                "from the MediaPipe model garden."
            )
        self._min_area_fraction = float(min_area_fraction)
        options = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            output_category_mask=True,
        )
        self._segmenter = vision.ImageSegmenter.create_from_options(options)

    def group_bbox(self, image_rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        """Bounding box (x0, y0, x1, y1) of all person pixels, or None.

        None means too few person pixels were found to trust -- a group too
        small or distant to locate, which the caller sends to review.
        """
        import mediapipe as mp

        height, width = image_rgb.shape[:2]
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(image_rgb)
        )
        result = self._segmenter.segment(mp_image)
        mask = np.squeeze(np.asarray(result.category_mask.numpy_view()))
        person = mask == PERSON_CLASS
        if person.sum() < self._min_area_fraction * height * width:
            return None
        rows = np.any(person, axis=1)
        cols = np.any(person, axis=0)
        y0, y1 = np.where(rows)[0][[0, -1]]
        x0, x1 = np.where(cols)[0][[0, -1]]
        mh, mw = mask.shape[:2]
        sx, sy = width / mw, height / mh  # map mask coords to image if sizes differ
        return int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)

    def close(self) -> None:
        self._segmenter.close()
