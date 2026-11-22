"""YAML config loading and validation.

Every tunable lives in config.yaml. Nothing here reads from the command line
except the paths to operate on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .geometry import amplification

# Above this, a small crown-estimate error becomes a large framing error.
AMPLIFICATION_WARN_THRESHOLD = 12.0


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Ratio:
    name: str
    width: int
    height: int
    # Optional per-ratio framing. When None, the global framing values apply.
    # This is what lets one size (e.g. a square) be composed tighter than the
    # rest of the set instead of being forced to the shared full-length height.
    eye_line_fraction: float | None = None
    headroom_fraction: float | None = None

    @property
    def pair(self) -> tuple[int, int]:
        return (self.width, self.height)


@dataclass(frozen=True)
class Config:
    detector: dict
    eye_line_fraction: float
    headroom_fraction: float
    eye_to_chin_multiplier: float
    fit_to_frame: bool
    min_headroom_fraction: float
    ratios: list[Ratio]
    jpeg_quality: object
    jpeg_subsampling: object
    contact_sheet: dict
    orders_folder: str | None
    landscape_enabled: bool
    landscape_ratios: list[Ratio]
    landscape_margin_fraction: float
    segment_model_path: str | None
    enhance_enabled: bool
    enhance_lut_path: str | None
    enhance_preschool_lut_path: str | None
    enhance_when: str
    balance_feet: bool
    foot_margin_fraction: float
    bottom_margin_fraction: float
    pose_model_path: str | None
    preschool: bool
    preschool_eye_line_fraction: float
    preschool_headroom_fraction: float
    composite: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def framing_for(self, ratio: Ratio) -> tuple[float, float]:
        """Effective (eye_line_fraction, headroom_fraction) for one ratio.

        A ratio's own values win when set; otherwise the global framing applies.
        """
        eye_line = (
            ratio.eye_line_fraction
            if ratio.eye_line_fraction is not None
            else self.eye_line_fraction
        )
        headroom = (
            ratio.headroom_fraction
            if ratio.headroom_fraction is not None
            else self.headroom_fraction
        )
        return eye_line, headroom


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ConfigError(f"missing required key {where}.{key} in config")
    return mapping[key]


def _fraction(value, where: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where} must be a number, got {value!r}") from exc
    if not 0.0 < number < 1.0:
        raise ConfigError(f"{where} must be strictly between 0 and 1, got {number}")
    return number


def load(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    warnings: list[str] = []

    detector = dict(_require(raw, "detector", "config"))
    _require(detector, "name", "detector")
    model_path = detector.get("model_path")
    if model_path is not None:
        # Resolve relative to the config file so runs work from any cwd.
        detector["model_path"] = str((path.parent / str(model_path)).resolve())

    framing = dict(_require(raw, "framing", "config"))
    eye_line = _fraction(_require(framing, "eye_line_fraction", "framing"), "framing.eye_line_fraction")
    headroom = _fraction(_require(framing, "headroom_fraction", "framing"), "framing.headroom_fraction")
    multiplier = float(framing.get("eye_to_chin_multiplier", 1.05))
    if multiplier <= 0:
        raise ConfigError("framing.eye_to_chin_multiplier must be positive")

    # Feet-balanced framing: equal top/bottom margins on full-body sizes, which
    # needs the feet located by a pose model. Off by default; the margin
    # defaults to the headroom so the balanced look matches the head-anchored one
    # for an average-height subject.
    balance_feet = bool(framing.get("balance_feet", False))
    foot_margin = _fraction(
        framing.get("foot_margin_fraction", headroom), "framing.foot_margin_fraction"
    )
    # Bottom (feet) margin for balanced framing; defaults to the top margin so
    # framing stays symmetric. Raise it to leave room below a prop at the feet
    # (e.g. a soccer ball the cleat rests on, which sits below the detected feet).
    bottom_margin = _fraction(
        framing.get("bottom_margin_fraction", foot_margin), "framing.bottom_margin_fraction"
    )
    if foot_margin + bottom_margin >= 1.0:
        raise ConfigError(
            f"framing.foot_margin_fraction ({foot_margin}) + bottom_margin_fraction "
            f"({bottom_margin}) must be below 1.0; the margins cannot fill the whole frame."
        )
    pose = dict(raw.get("pose") or {})
    pose_model = pose.get("model_path")
    pose_model_path = (
        str((path.parent / str(pose_model)).resolve()) if pose_model is not None else None
    )
    if balance_feet and pose_model_path is None:
        raise ConfigError(
            "framing.balance_feet is true but pose.model_path is not set; point it "
            "at the pose model (e.g. models/pose_landmarker.task)."
        )

    # Preschool framing: a tighter, seated 3/4 profile (eyes high, bottom at the
    # lap) measured from the reference 5x7 crops. It is a mode, toggled per run,
    # that replaces the global full-length framing with these fractions on every
    # globally-framed size; feet-balancing does not apply (the subject is seated)
    # and the square keeps its own override. Off by default.
    preschool = bool(framing.get("preschool", False))
    preschool_eye_line = _fraction(
        framing.get("preschool_eye_line_fraction", 0.264),
        "framing.preschool_eye_line_fraction",
    )
    preschool_headroom = _fraction(
        framing.get("preschool_headroom_fraction", 0.133),
        "framing.preschool_headroom_fraction",
    )
    if preschool_headroom >= preschool_eye_line:
        raise ConfigError(
            f"framing.preschool_headroom_fraction ({preschool_headroom}) must be less "
            f"than framing.preschool_eye_line_fraction ({preschool_eye_line})."
        )

    fit_to_frame = bool(framing.get("fit_to_frame", True))
    min_headroom = _fraction(
        framing.get("min_headroom_fraction", 0.08), "framing.min_headroom_fraction"
    )
    if min_headroom > preschool_headroom:
        raise ConfigError(
            f"framing.min_headroom_fraction ({min_headroom}) cannot exceed "
            f"framing.preschool_headroom_fraction ({preschool_headroom}); it is the "
            "floor the frame may shrink to, not a target."
        )
    preschool_factor = amplification(preschool_eye_line, preschool_headroom)
    if preschool_factor > AMPLIFICATION_WARN_THRESHOLD:
        warnings.append(
            f"preschool framing sensitivity is high: crop height is "
            f"{preschool_factor:.1f}x the crown-to-eye distance."
        )
    if min_headroom > headroom:
        raise ConfigError(
            f"framing.min_headroom_fraction ({min_headroom}) cannot exceed "
            f"framing.headroom_fraction ({headroom}); it is the floor the frame "
            "may shrink to, not a target."
        )

    if headroom >= eye_line:
        raise ConfigError(
            f"framing.headroom_fraction ({headroom}) must be less than "
            f"framing.eye_line_fraction ({eye_line}). With headroom at or above "
            "the eye line the top of the head would sit below the eyes and no "
            "crop height exists."
        )

    factor = amplification(eye_line, headroom)
    if factor > AMPLIFICATION_WARN_THRESHOLD:
        warnings.append(
            f"framing sensitivity is high: crop height is {factor:.1f}x the "
            f"crown-to-eye distance, so crown-estimate error is amplified "
            f"{factor:.0f}x. Widen the gap between eye_line_fraction and "
            "headroom_fraction to stabilise framing."
        )

    # Ratio names become both a folder and the filename suffix, so a name that
    # is unsafe in a path or confusing to a filename parser corrupts output
    # names rather than just looking untidy.
    unsafe_chars = set('/\\\0:*?"<>|')

    raw_ratios = _require(raw, "ratios", "config")
    if not isinstance(raw_ratios, list) or not raw_ratios:
        raise ConfigError("config.ratios must be a non-empty list")
    ratios: list[Ratio] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_ratios):
        if not isinstance(item, dict):
            raise ConfigError(f"config.ratios[{index}] must be a mapping")
        name = str(_require(item, "name", f"ratios[{index}]"))
        width = int(_require(item, "width", f"ratios[{index}]"))
        height = int(_require(item, "height", f"ratios[{index}]"))
        if width <= 0 or height <= 0:
            raise ConfigError(f"config.ratios[{index}] width and height must be positive")
        if name in seen:
            raise ConfigError(f"duplicate ratio name {name!r}; names become output folders")
        seen.add(name)

        if not name.strip() or name in {".", ".."} or name.startswith("."):
            raise ConfigError(f"ratio name {name!r} is not usable as a folder name")
        bad = sorted(unsafe_chars.intersection(name))
        if bad:
            raise ConfigError(
                f"ratio name {name!r} contains {' '.join(bad)}, which cannot appear "
                "in a folder or filename"
            )
        if "." in name:
            warnings.append(
                f"ratio name {name!r} contains a dot, so crops are named like "
                f"'STUDENT_{name}.jpg'. Standard extension parsing takes the last "
                "dot and handles this, but a system that splits on the first dot "
                "will truncate the filename. Prefer a dot-free name such as "
                "'wallet' or 'square' if these files go to a lab."
            )
        # Optional per-ratio framing overrides. Absent keys inherit the global
        # framing; present ones are validated exactly like the global values.
        el_raw = item.get("eye_line_fraction")
        hr_raw = item.get("headroom_fraction")
        el_override = (
            _fraction(el_raw, f"ratios[{index}].eye_line_fraction")
            if el_raw is not None
            else None
        )
        hr_override = (
            _fraction(hr_raw, f"ratios[{index}].headroom_fraction")
            if hr_raw is not None
            else None
        )

        eff_eye_line = el_override if el_override is not None else eye_line
        eff_headroom = hr_override if hr_override is not None else headroom
        if eff_headroom >= eff_eye_line:
            raise ConfigError(
                f"ratio {name!r}: headroom_fraction ({eff_headroom}) must be less "
                f"than eye_line_fraction ({eff_eye_line}). With headroom at or above "
                "the eye line the top of the head would sit below the eyes and no "
                "crop height exists."
            )
        if min_headroom > eff_headroom:
            raise ConfigError(
                f"ratio {name!r}: framing.min_headroom_fraction ({min_headroom}) "
                f"cannot exceed this ratio's headroom_fraction ({eff_headroom})."
            )
        # Only warn here when the ratio sets its own framing; ratios that inherit
        # the global values are already covered by the global warning above.
        if el_override is not None or hr_override is not None:
            ratio_factor = amplification(eff_eye_line, eff_headroom)
            if ratio_factor > AMPLIFICATION_WARN_THRESHOLD:
                warnings.append(
                    f"ratio {name!r}: framing sensitivity is high: crop height is "
                    f"{ratio_factor:.1f}x the crown-to-eye distance, so crown-estimate "
                    f"error is amplified {ratio_factor:.0f}x."
                )

        ratios.append(
            Ratio(
                name=name,
                width=width,
                height=height,
                eye_line_fraction=el_override,
                headroom_fraction=hr_override,
            )
        )

    # Landscape (group) handling: a landscape source is cropped to these
    # landscape print ratios instead of being routed to review.
    landscape = dict(raw.get("landscape") or {})
    landscape_enabled = bool(landscape.get("enabled", False))
    landscape_ratios: list[Ratio] = []
    seen_landscape: set[str] = set()
    for index, item in enumerate(landscape.get("ratios") or []):
        if not isinstance(item, dict):
            raise ConfigError(f"landscape.ratios[{index}] must be a mapping")
        name = str(_require(item, "name", f"landscape.ratios[{index}]"))
        width = int(_require(item, "width", f"landscape.ratios[{index}]"))
        height = int(_require(item, "height", f"landscape.ratios[{index}]"))
        if width <= 0 or height <= 0:
            raise ConfigError(f"landscape.ratios[{index}] width and height must be positive")
        if name in seen_landscape or name in seen:
            raise ConfigError(f"duplicate ratio name {name!r} (names become output folders)")
        seen_landscape.add(name)
        if not name.strip() or name.startswith(".") or unsafe_chars.intersection(name):
            raise ConfigError(f"landscape ratio name {name!r} is not usable as a folder name")
        landscape_ratios.append(Ratio(name=name, width=width, height=height))
    if landscape_enabled and not landscape_ratios:
        raise ConfigError("landscape.enabled is true but no landscape.ratios are defined")
    landscape_margin = _fraction(
        landscape.get("margin_fraction", 0.08), "landscape.margin_fraction"
    )
    segment = dict(raw.get("segment") or {})
    segment_model = segment.get("model_path")
    segment_model_path = (
        str((path.parent / str(segment_model)).resolve()) if segment_model is not None else None
    )
    if landscape_enabled and segment_model_path is None:
        raise ConfigError(
            "landscape.enabled is true but no segment.model_path is set; point it at "
            "the segmentation model (e.g. models/deeplab_v3.tflite)."
        )

    output = dict(raw.get("output") or {})
    contact_sheet = dict(raw.get("contact_sheet") or {})
    # Class-composite defaults (fonts, school name, layout). Passed straight to
    # the composite builder / GUI; validated there, not here.
    composite = dict(raw.get("composite") or {})

    # A single flat folder holding a copy of every crop (all sizes together),
    # in addition to the per-size folders. Set to null/empty to switch off.
    orders_raw = output.get("orders_folder", "Orders")
    if orders_raw in (None, "", False):
        orders_folder = None
    else:
        orders_folder = str(orders_raw)
        bad = sorted(unsafe_chars.intersection(orders_folder))
        if bad or orders_folder in {".", ".."} or orders_folder.startswith("."):
            raise ConfigError(
                f"output.orders_folder {orders_folder!r} is not usable as a folder name"
            )

    enhance = dict(raw.get("enhance") or {})
    enhance_enabled = bool(enhance.get("enabled", False))
    lut_path = enhance.get("lut_path")
    enhance_lut_path = (
        str((path.parent / str(lut_path)).resolve()) if lut_path is not None else None
    )
    if enhance_enabled and enhance_lut_path is None:
        raise ConfigError(
            "enhance.enabled is true but enhance.lut_path is not set; point it at "
            "the preset LUT (e.g. luts/preset.npy)."
        )
    # Separate grading preset for preschool mode (seated indoor shots). When
    # preschool is on and enhancement is on, this LUT is used instead of the
    # default one above. Optional; only needed to grade a preschool run.
    preschool_lut = enhance.get("preschool_lut_path")
    enhance_preschool_lut_path = (
        str((path.parent / str(preschool_lut)).resolve()) if preschool_lut is not None else None
    )
    enhance_when = str(enhance.get("when", "before")).lower()
    if enhance_when not in ("before", "after"):
        raise ConfigError("enhance.when must be 'before' or 'after' (cropping)")

    return Config(
        detector=detector,
        eye_line_fraction=eye_line,
        headroom_fraction=headroom,
        eye_to_chin_multiplier=multiplier,
        fit_to_frame=fit_to_frame,
        min_headroom_fraction=min_headroom,
        ratios=ratios,
        jpeg_quality=output.get("jpeg_quality", "keep"),
        jpeg_subsampling=output.get("jpeg_subsampling", "keep"),
        contact_sheet=contact_sheet,
        orders_folder=orders_folder,
        landscape_enabled=landscape_enabled,
        landscape_ratios=landscape_ratios,
        landscape_margin_fraction=landscape_margin,
        segment_model_path=segment_model_path,
        enhance_enabled=enhance_enabled,
        enhance_lut_path=enhance_lut_path,
        enhance_preschool_lut_path=enhance_preschool_lut_path,
        enhance_when=enhance_when,
        balance_feet=balance_feet,
        foot_margin_fraction=foot_margin,
        bottom_margin_fraction=bottom_margin,
        pose_model_path=pose_model_path,
        preschool=preschool,
        preschool_eye_line_fraction=preschool_eye_line,
        preschool_headroom_fraction=preschool_headroom,
        composite=composite,
        warnings=warnings,
    )
