"""Detector registry -- maps the `detector.name` config value to a backend."""

from __future__ import annotations

from typing import Callable, Dict

from .base import Detector

_REGISTRY: Dict[str, Callable[[dict], Detector]] = {}


def register(name: str) -> Callable[[Callable[[dict], Detector]], Callable[[dict], Detector]]:
    def _wrap(factory: Callable[[dict], Detector]) -> Callable[[dict], Detector]:
        _REGISTRY[name] = factory
        return factory

    return _wrap


def available() -> list[str]:
    return sorted(_REGISTRY)


def build(name: str, cfg: dict) -> Detector:
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown detector {name!r}; available: {', '.join(available()) or '(none)'}"
        )
    return _REGISTRY[name](cfg)
