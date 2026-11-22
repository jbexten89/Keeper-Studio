"""Feet detection via MediaPipe Pose Landmarker (Tasks API).

Face landmarks fix the top of the crop; to balance the bottom edge (feet the
same distance from the bottom as the head is from the top) the cropper needs to
know where the feet are. This wraps the Pose Landmarker and returns just the
lowest foot point, which is all the balanced framing needs. Everything else
about a pose is ignored.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# MediaPipe Pose landmark indices for the feet.
_FOOT_INDICES = (
    27,  # left ankle
    28,  # right ankle
    29,  # left heel
    30,  # right heel
    31,  # left foot index
    32,  # right foot index
)


class PoseDetector:
    def __init__(self, model_path: str, *, min_visibility: float = 0.5):
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision

        path = Path(model_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(
                f"pose landmarker model not found at {path}. Download "
                "pose_landmarker.task from the MediaPipe model garden."
            )
        self._min_visibility = float(min_visibility)
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)

    def feet_y(self, image_rgb: np.ndarray) -> float | None:
        """Lowest (largest-y) visible foot point in pixels, or None.

        None means no pose, or the feet were not confidently visible (e.g. cut
        off at the bottom of the source) -- the caller then falls back to
        head-anchored framing rather than guessing.
        """
        import mediapipe as mp

        height = image_rgb.shape[0]
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(image_rgb)
        )
        result = self._landmarker.detect(mp_image)
        if not result.pose_landmarks:
            return None
        landmarks = result.pose_landmarks[0]
        ys = [
            landmarks[i].y * height
            for i in _FOOT_INDICES
            if getattr(landmarks[i], "visibility", 1.0) >= self._min_visibility
        ]
        if not ys:
            return None
        return float(max(ys))

    def close(self) -> None:
        self._landmarker.close()
