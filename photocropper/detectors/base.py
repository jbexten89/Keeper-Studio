"""Detector interface and the neutral observation type the cropper consumes.

Everything downstream of a detector works with `FaceObservation` only. A new
detector is a drop-in as long as it can fill this struct; nothing in the crop
geometry knows what produced the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class FaceObservation:
    """One detected face, in source-image pixel coordinates.

    Coordinates are floats: sub-pixel landmark precision matters here because
    the crop height is derived from the (small) crown-to-eye distance and any
    error in it is amplified by the framing geometry.
    """

    eye_left: Point
    """Centre of the subject's left eye (image-right in a front-on portrait)."""

    eye_right: Point
    """Centre of the subject's right eye."""

    chin: Point
    """Lowest point of the chin."""

    forehead_top: Point
    """Highest landmark the model provides. For a face mesh this is the upper
    forehead / hairline, NOT the crown of the skull. Crown is estimated from
    this plus the eye-chin span; see `photocropper.geometry.estimate_crown`."""

    confidence: float

    @property
    def eye_mid(self) -> Point:
        """Midpoint between the eyes. This is the horizontal anchor -- not the
        centre of the face bounding box, which drifts on a turned head."""
        return (
            (self.eye_left[0] + self.eye_right[0]) / 2.0,
            (self.eye_left[1] + self.eye_right[1]) / 2.0,
        )

    @property
    def interocular(self) -> float:
        """Distance between eye centres. Used as a scale sanity check."""
        return float(
            np.hypot(
                self.eye_left[0] - self.eye_right[0],
                self.eye_left[1] - self.eye_right[1],
            )
        )


class Detector(Protocol):
    """Implement this and register it to swap detection backends."""

    name: str

    def detect(self, image_rgb: np.ndarray) -> Sequence[FaceObservation]:
        """Return every face found in an HxWx3 uint8 RGB array.

        Must return all faces above the configured confidence threshold -- the
        caller is responsible for the multi-face policy, not the detector.
        """
        ...

    def close(self) -> None: ...
