"""MediaPipe Face Landmarker backend (Tasks API).

Note on the API: mediapipe >= 1.0 removed the legacy `mp.solutions.face_mesh`
namespace. This uses the supported `mediapipe.tasks.python.vision.FaceLandmarker`,
which needs a `.task` model bundle on disk (path comes from config).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from .base import FaceObservation, Point
from .registry import register

# Canonical face-mesh indices.
IDX_CHIN = 152
IDX_FOREHEAD = 10

# Iris centres, present only when the bundle emits the refined 478-point mesh.
IDX_IRIS_A = 468
IDX_IRIS_B = 473

# Eye contour rings, used when iris landmarks are unavailable.
EYE_RING_A = (362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398)
EYE_RING_B = (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246)


class MediaPipeMeshDetector:
    name = "mediapipe_mesh"

    def __init__(self, cfg: dict):
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision

        model_path = Path(cfg["model_path"]).expanduser()
        if not model_path.is_file():
            raise FileNotFoundError(
                f"face landmarker model not found at {model_path}. "
                "Download face_landmarker.task from the MediaPipe model garden."
            )

        self._threshold = float(cfg.get("confidence_threshold", 0.5))
        # Probe for more than one face on purpose: capping at 1 would make the
        # "more than one face detected" review case undetectable.
        self._max_faces = int(cfg.get("max_faces_to_probe", 5))

        # The underlying face detector resizes the whole frame to a small fixed
        # input, so a face covering a small fraction of a wide shot drops below
        # its resolution floor and is missed entirely -- lowering the confidence
        # threshold does not help, because the face never registers at all.
        # When the full frame finds nothing, retry on overlapping windows at
        # these fractions of frame size, which restores the face's relative
        # size. Coordinates are mapped back to the full frame.
        self._window_scales = [float(s) for s in cfg.get("detection_window_scales", [1.0, 0.5, 0.25])]

        self._vision = vision
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=self._max_faces,
            min_face_detection_confidence=self._threshold,
            min_face_presence_confidence=self._threshold,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def detect(self, image_rgb: np.ndarray) -> Sequence[FaceObservation]:
        # Coarse to fine: the full frame handles normal framing in one pass,
        # and only wide shots pay for the extra windows.
        for scale in self._window_scales:
            faces = self._detect_at_scale(image_rgb, scale)
            if faces:
                return faces
        return []

    def _windows(self, width: int, height: int, scale: float) -> list[tuple[int, int, int, int]]:
        if scale >= 1.0:
            return [(0, 0, width, height)]
        win_w, win_h = max(1, round(width * scale)), max(1, round(height * scale))
        step_x, step_y = max(1, win_w // 2), max(1, win_h // 2)  # 50% overlap
        windows = []
        for top in range(0, max(1, height - win_h + step_y), step_y):
            for left in range(0, max(1, width - win_w + step_x), step_x):
                left, top_ = min(left, width - win_w), min(top, height - win_h)
                windows.append((left, top_, win_w, win_h))
        return windows

    def _detect_at_scale(self, image_rgb: np.ndarray, scale: float) -> list[FaceObservation]:
        import mediapipe as mp

        height, width = image_rgb.shape[:2]
        found: list[FaceObservation] = []

        for left, top, win_w, win_h in self._windows(width, height, scale):
            tile = image_rgb[top : top + win_h, left : left + win_w]
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(tile)
            )
            result = self._landmarker.detect(mp_image)

            for landmarks in result.face_landmarks:
                # Landmarks are normalised to the window; map back to the frame.
                pts = np.array(
                    [(lm.x * win_w + left, lm.y * win_h + top) for lm in landmarks],
                    dtype=np.float64,
                )
                observation = self._to_observation(pts)
                if not self._is_duplicate(observation, found):
                    found.append(observation)

        return found

    def _to_observation(self, pts: np.ndarray) -> FaceObservation:
        eye_a, eye_b = self._eye_centres(pts)
        # Order by x so "left"/"right" are stable regardless of mesh convention.
        left, right = (eye_a, eye_b) if eye_a[0] <= eye_b[0] else (eye_b, eye_a)
        return FaceObservation(
            eye_left=left,
            eye_right=right,
            chin=(float(pts[IDX_CHIN][0]), float(pts[IDX_CHIN][1])),
            forehead_top=(float(pts[IDX_FOREHEAD][0]), float(pts[IDX_FOREHEAD][1])),
            # The Tasks API applies its confidence threshold inside the graph
            # and does not surface a per-face score, so this records the
            # acceptance floor rather than a measured value.
            confidence=self._threshold,
        )

    @staticmethod
    def _is_duplicate(candidate: FaceObservation, existing: list[FaceObservation]) -> bool:
        """Overlapping windows see the same face twice; collapse those.

        Without this, a single subject found in two adjacent tiles would be
        reported as two faces and wrongly routed to review.
        """
        cx, cy = candidate.eye_mid
        for other in existing:
            ox, oy = other.eye_mid
            tolerance = max(candidate.interocular, other.interocular) * 0.5
            if np.hypot(cx - ox, cy - oy) < tolerance:
                return True
        return False

    @staticmethod
    def _eye_centres(pts: np.ndarray) -> tuple[Point, Point]:
        if len(pts) > max(IDX_IRIS_A, IDX_IRIS_B):
            a = pts[IDX_IRIS_A]
            b = pts[IDX_IRIS_B]
        else:
            a = pts[list(EYE_RING_A)].mean(axis=0)
            b = pts[list(EYE_RING_B)].mean(axis=0)
        return (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))

    def close(self) -> None:
        self._landmarker.close()


@register("mediapipe_mesh")
def _factory(cfg: dict) -> MediaPipeMeshDetector:
    return MediaPipeMeshDetector(cfg)
