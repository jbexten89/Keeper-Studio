"""Swappable face-detection backends.

Add a backend by writing a module here that fills `base.FaceObservation` and
decorating its factory with `@register("your_name")`, then import it below so
the registration runs. Select it with `detector.name` in config.yaml.
"""

from . import mediapipe_mesh  # noqa: F401  (import registers the backend)
from .base import Detector, FaceObservation
from .registry import available, build

__all__ = ["Detector", "FaceObservation", "available", "build"]
