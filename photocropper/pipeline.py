"""Job execution, shared by the CLI and the GUI.

Neither front end contains cropping logic: both call `run_job`, which reports
progress through a callback and can be cancelled between images. Keeping this
in one place is what stops the two from drifting apart.
"""

from __future__ import annotations

import json
import shutil
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import contact_sheet, detectors, enhance, imageio
from .config import Config
from .geometry import (
    CropSolution,
    estimate_crown,
    group_crop_box,
    manual_crop_box,
    max_fitting_height,
    max_fitting_height_balanced,
    solve_crop,
    solve_crop_balanced,
)

# Status values. OK means every enabled ratio was written.
OK = "ok"
NO_FACE = "no_face"
MULTI_FACE = "multi_face"
OUT_OF_BOUNDS = "out_of_bounds"
ERROR = "error"

STATUS_LABELS = {
    OK: "cropped",
    NO_FACE: "no face found",
    MULTI_FACE: "multiple faces",
    OUT_OF_BOUNDS: "crop box off-frame",
    ERROR: "error",
}


@dataclass
class ImageResult:
    path: Path
    status: str
    reason: str | None = None
    """Full sidecar text for anything routed to review; None when cropped."""
    written: dict[str, Path] = field(default_factory=dict)
    solution: CropSolution | None = None
    adjusted: bool = False
    """True when the frame was shortened to fit. The crop is good, but the
    bottom edge sits higher than the configured framing, so these are worth a
    look on the contact sheet."""

    @property
    def ok(self) -> bool:
        return self.status == OK


@dataclass
class JobSummary:
    results: list[ImageResult] = field(default_factory=list)
    sheets: list[Path] = field(default_factory=list)
    cancelled: bool = False

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def review(self) -> list[ImageResult]:
        return [r for r in self.results if not r.ok]

    @property
    def adjusted(self) -> list[ImageResult]:
        """Cropped, but with the frame shortened to fit the available space."""
        return [r for r in self.results if r.ok and r.adjusted]

    def framing_medians(self) -> tuple[float, float] | None:
        """Median frame height and bottom edge, in head-heights."""
        heads = [r.solution.frame_height_in_heads for r in self.results if r.ok and r.solution]
        bottoms = [r.solution.bottom_below_crown_in_heads for r in self.results if r.ok and r.solution]
        if not heads:
            return None
        return statistics.median(heads), statistics.median(bottoms)


def _too_tight_reason(
    solutions: dict[str, CropSolution],
    image_size: tuple[int, int],
    tightest: float,
    minimum: float,
) -> str:
    return "\n".join(
        [
            "SKIPPED: not enough room above the head, even after shortening the frame.",
            "",
            f"Source size: {image_size[0]}x{image_size[1]} px",
            "",
            "The frame was shortened as far as it could go while keeping the eye",
            f"line in place, but headroom still came to {tightest:.3f} of frame height,",
            f"below the {minimum:.3f} floor set by framing.min_headroom_fraction.",
            "Going further would start cropping into the top of the head.",
            "",
            "Reshoot with more space above the head, or lower",
            "framing.min_headroom_fraction if this much is acceptable.",
        ]
    )


def _overflow_reason(failures: list[tuple[str, CropSolution]], image_size: tuple[int, int]) -> str:
    lines = [
        "SKIPPED: computed crop box extends beyond the source image.",
        "",
        f"Source size: {image_size[0]}x{image_size[1]} px",
        "",
        "The crop was not shifted or shrunk to fit, so framing stays consistent",
        "with every other image in the run. Either reshoot wider, or reduce",
        "framing.headroom_fraction in config.yaml to pull the frame in.",
        "",
    ]
    for ratio_name, solution in failures:
        box = solution.box
        lines.append(
            f"  {ratio_name}: needed box {box.width}x{box.height} at "
            f"({box.left},{box.top}) -- outside {solution.overflow.describe()}"
        )
    return "\n".join(lines)


def _fit_override_ratio(face, ratio, config, size):
    """Solve one override ratio (its own framing), shortening it to fit if need be.

    Returns (solution, adjusted) on success, or (solution, None) when even the
    shortest frame would crop into the head -- the caller routes that to review.
    """
    eye_line, headroom = config.framing_for(ratio)
    sol = solve_crop(
        face, ratio.pair, size,
        eye_line_fraction=eye_line, headroom_fraction=headroom,
        eye_to_chin_multiplier=config.eye_to_chin_multiplier,
    )
    if sol.fits:
        return sol, False
    if not config.fit_to_frame:
        return sol, False
    fitted = max_fitting_height(face, ratio.pair, size, eye_line_fraction=eye_line)
    cand = solve_crop(
        face, ratio.pair, size,
        eye_line_fraction=eye_line, headroom_fraction=headroom,
        eye_to_chin_multiplier=config.eye_to_chin_multiplier, height_override=fitted,
    )
    if cand.fits and cand.headroom_actual >= config.min_headroom_fraction:
        return cand, True
    return cand, None


# Keeper Studio: a per-thread hook that lets the app plan crops (preview the
# boxes) through the exact same code path as a real run, without writing files.
import threading as _threading

_writer_hook = _threading.local()


def _write_crop(source, box, out_dir: Path, stem: str, ratio_name: str, suffix: str, config: Config, post_lut=None) -> Path:
    hook = getattr(_writer_hook, "fn", None)
    if hook is not None:
        return hook(source, box, out_dir, stem, ratio_name, suffix)
    """Write one crop to its size folder, and copy it into the combined Orders
    folder too when that is enabled. The copy is byte-for-byte, so no
    re-encoding happens the second time.

    `post_lut` applies the colour preset to each crop after cropping (the
    "after" enhancement timing).
    """
    destination = out_dir / ratio_name / f"{stem}_{ratio_name}{suffix}"
    imageio.save_crop(
        source, box, destination,
        jpeg_quality=config.jpeg_quality, jpeg_subsampling=config.jpeg_subsampling,
        post_lut=post_lut,
    )
    if config.orders_folder:
        combined = out_dir / config.orders_folder / f"{stem}_{ratio_name}{suffix}"
        combined.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, combined)
    return destination


def _landscape_review_reason(kind: str, config: Config, image_size) -> str:
    if kind == "not_found":
        return "\n".join([
            "SKIPPED: landscape group shot, but the group could not be located.",
            "",
            f"Source size: {image_size[0]}x{image_size[1]} px",
            "",
            "The people are too small/distant for the segmenter to find them, so",
            "a safe crop cannot be placed automatically. Crop this one by hand.",
        ])
    return "\n".join([
        "SKIPPED: landscape group is too wide to crop to the landscape ratios",
        "without cutting people off at the sides.",
        "",
        f"Source size: {image_size[0]}x{image_size[1]} px",
        "",
        f"The group spans nearly the full frame, and {', '.join(r.name for r in config.landscape_ratios)}",
        "are narrower than the source, so fitting the whole width would trim the",
        "end people. Reshoot with more room on the sides, or crop this by hand.",
    ])


def _resolve_enhance(source, lut, when):
    """Enhance the whole source now (when == "before") or defer to each crop
    (when == "after"). Returns the post-crop LUT to apply at save time, or None.
    """
    if lut is None:
        return None
    if when == "after":
        return lut
    source.image = enhance.apply_lut(source.image, lut)
    return None


def _process_landscape(path: Path, source, config: Config, out_dir: Path, segmenter, post_lut=None) -> ImageResult:
    """Crop a landscape group shot to the landscape print ratios.

    The group is located by segmentation and each ratio is framed around it with
    proper margins, never trimming into the group on any side. A group that
    cannot be located, or is too wide to fit a ratio without a side cut, goes to
    review instead of being cropped badly.
    """
    bbox = segmenter.group_bbox(source.as_rgb_array()) if segmenter is not None else None
    if bbox is None:
        return ImageResult(
            path, OUT_OF_BOUNDS, _landscape_review_reason("not_found", config, source.size)
        )

    written: dict[str, Path] = {}
    for ratio in config.landscape_ratios:
        box = group_crop_box(
            bbox, source.size, ratio.width, ratio.height, config.landscape_margin_fraction
        )
        if box is None:
            continue  # this ratio cannot contain the group without a side cut
        written[ratio.name] = _write_crop(
            source, box.as_pil(), out_dir, path.stem, ratio.name, path.suffix, config, post_lut
        )

    if not written:
        return ImageResult(
            path, OUT_OF_BOUNDS, _landscape_review_reason("too_wide", config, source.size)
        )
    return ImageResult(path, OK, None, written)


def process_image(
    path: Path, detector, config: Config, out_dir: Path, lut=None, pose_detector=None,
    balance=False, segmenter=None, enhance_when="before", bottom_margin=None,
    preschool_framing=None,
) -> ImageResult:
    """Crop one image, or classify why it cannot be cropped.

    Writes crops but not review copies -- the caller owns that, so a dry run
    is possible without touching the review folder.

    When `lut` is provided the enhancement preset is applied to the pixels before
    detection. When `balance` is set and a `pose_detector` locates the feet, the
    full-body sizes are framed with equal top/bottom margins (see
    solve_crop_balanced); otherwise they fall back to head-anchored framing. The
    square and any other per-ratio-framed size always stay face-anchored.

    `preschool_framing`, when given as (eye_line_fraction, headroom_fraction),
    is the seated preschool mode: every globally-framed size uses that tighter
    profile instead of the full-length global framing, and feet-balancing is
    switched off (the subject is seated). The square keeps its own override.
    """
    source = imageio.load(path)
    # Enhance the whole source now (before) or defer to each crop (after).
    post_lut = _resolve_enhance(source, lut, enhance_when)
    rgb = source.as_rgb_array()

    # A landscape source is a group shot: crop it to the landscape print ratios
    # (full height kept, sides trimmed, centred on the group) rather than trying
    # to anchor on a single face and routing it to review.
    if config.landscape_enabled and config.landscape_ratios and source.size[0] > source.size[1]:
        return _process_landscape(path, source, config, out_dir, segmenter, post_lut)

    faces = detector.detect(rgb)

    if len(faces) == 0:
        return ImageResult(
            path,
            NO_FACE,
            "SKIPPED: no face detected.\n\n"
            f"Detector: {config.detector['name']} at confidence threshold "
            f"{config.detector.get('confidence_threshold')}.\n"
            "Lower detector.confidence_threshold in config.yaml, or crop by hand.",
        )

    if len(faces) > 1:
        return ImageResult(
            path,
            MULTI_FACE,
            f"SKIPPED: {len(faces)} faces detected, expected exactly 1.\n\n"
            "Anchoring is ambiguous with more than one subject. Crop by hand, or\n"
            "raise detector.confidence_threshold if the extras are false positives.",
        )

    face = faces[0]

    # Feet-balanced framing needs the feet located. If the pose model finds them
    # (and they sit below the crown), full-body sizes get equal margins; if not
    # -- feet cut off, no pose -- fall back to head-anchored framing silently.
    # Preschool (seated) framing takes precedence over feet-balancing: there are
    # no standing feet to balance on, so the full-body sizes use the tighter
    # seated profile instead.
    feet_y = None
    if balance and preschool_framing is None and pose_detector is not None:
        feet_y = pose_detector.feet_y(rgb)
    crown_y = estimate_crown(face, config.eye_to_chin_multiplier)[1]
    use_balanced = feet_y is not None and feet_y > crown_y

    global_ratios = [r for r in config.ratios if _uses_global_framing(r)]
    override_ratios = [r for r in config.ratios if not _uses_global_framing(r)]

    def solve_global(ratio, height_override=None):
        if use_balanced:
            mb = config.bottom_margin_fraction if bottom_margin is None else bottom_margin
            return solve_crop_balanced(
                face, feet_y, ratio.pair, source.size,
                margin_top=config.foot_margin_fraction,
                margin_bottom=mb,
                eye_to_chin_multiplier=config.eye_to_chin_multiplier,
                height_override=height_override,
            )
        eye_line, headroom = (
            preschool_framing if preschool_framing is not None else config.framing_for(ratio)
        )
        return solve_crop(
            face, ratio.pair, source.size,
            eye_line_fraction=eye_line, headroom_fraction=headroom,
            eye_to_chin_multiplier=config.eye_to_chin_multiplier,
            height_override=height_override,
        )

    solutions: dict[str, CropSolution] = {}
    adjusted = False

    # Full-body sizes share one height (balanced or head-anchored), so they are
    # framed alike and shortened together when the ideal frame does not fit.
    if global_ratios:
        g = {r.name: solve_global(r) for r in global_ratios}
        if any(not s.fits for s in g.values()) and config.fit_to_frame:
            ideal_h = next(iter(g.values())).box.height
            if use_balanced:
                ceilings = [
                    max_fitting_height_balanced(
                        face, r.pair, source.size,
                        margin_top=config.foot_margin_fraction,
                        eye_to_chin_multiplier=config.eye_to_chin_multiplier,
                    )
                    for r in global_ratios
                ]
            else:
                fit_eye_line = (
                    preschool_framing[0] if preschool_framing is not None
                    else config.eye_line_fraction
                )
                ceilings = [
                    max_fitting_height(
                        face, r.pair, source.size, eye_line_fraction=fit_eye_line
                    )
                    for r in global_ratios
                ]
            fitted = min(ceilings + [float(ideal_h)])
            cand = {r.name: solve_global(r, height_override=fitted) for r in global_ratios}
            tightest = min(s.headroom_actual for s in cand.values())
            if all(s.fits for s in cand.values()) and tightest >= config.min_headroom_fraction:
                g = cand
                adjusted = True
            else:
                return ImageResult(
                    path, OUT_OF_BOUNDS,
                    _too_tight_reason(cand, source.size, tightest, config.min_headroom_fraction),
                    solution=next(iter(cand.values())),
                )
        solutions.update(g)

    # Override sizes (the square) keep their own tighter, face-anchored framing,
    # each shortened on its own if needed.
    too_tight: list[tuple[str, CropSolution]] = []
    for ratio in override_ratios:
        sol, ok = _fit_override_ratio(face, ratio, config, source.size)
        solutions[ratio.name] = sol
        if ok is None:
            too_tight.append((ratio.name, sol))
        elif ok:
            adjusted = True
    if too_tight:
        name, worst = min(too_tight, key=lambda kv: kv[1].headroom_actual)
        return ImageResult(
            path, OUT_OF_BOUNDS,
            _too_tight_reason(dict(too_tight), source.size, worst.headroom_actual, config.min_headroom_fraction),
            solution=worst,
        )

    failures = [(name, s) for name, s in solutions.items() if not s.fits]
    if failures:
        # All-or-nothing: a subject must never end up with some ratios and not
        # others, since these are matched back to records downstream.
        return ImageResult(
            path,
            OUT_OF_BOUNDS,
            _overflow_reason(failures, source.size),
            solution=next(iter(solutions.values())),
        )

    written: dict[str, Path] = {}
    for ratio_name, solution in solutions.items():
        # The ratio is appended so every print size is a distinct,
        # self-describing file that survives being flattened into one folder.
        written[ratio_name] = _write_crop(
            source, solution.box.as_pil(), out_dir, path.stem, ratio_name, path.suffix, config, post_lut
        )

    return ImageResult(
        path, OK, None, written, next(iter(solutions.values())), adjusted=adjusted
    )


MANUAL_DIRNAME = "manual"


def _uses_global_framing(ratio) -> bool:
    """True for ratios that follow the global framing (no per-ratio override).

    Manual positioning governs exactly these; ratios with their own framing
    (e.g. the square) keep their auto, face-anchored crop.
    """
    return ratio.eye_line_fraction is None and ratio.headroom_fraction is None


def manual_sidecar_path(out_dir: Path, stem: str) -> Path:
    return out_dir / MANUAL_DIRNAME / f"{stem}.json"


def load_manual_crop(out_dir: Path, stem: str) -> dict | None:
    """Load a saved manual framing for one image stem, or None."""
    path = manual_sidecar_path(out_dir, stem)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if all(k in data for k in ("center_x", "top", "height")):
        return data
    return None


def save_manual_crop(out_dir: Path, stem: str, manual: dict) -> None:
    path = manual_sidecar_path(out_dir, stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manual), encoding="utf-8")


def apply_manual_crop(
    path: Path,
    config: Config,
    out_dir: Path,
    manual: dict,
    *,
    detector=None,
    lut=None,
    enhance_override: bool | None = None,
    enhance_when: str | None = None,
    persist: bool = True,
) -> ImageResult:
    """Re-crop one image from a hand-placed framing box.

    `manual` carries center_x / top / height in the coordinate space of the
    display-oriented source (i.e. imageio.load(path).image). Every ratio that
    uses the global framing is written from that one box; ratios with their own
    framing (the square) keep their auto, face-anchored crop. Existing crops for
    this image are overwritten. The placement is saved as a sidecar so a later
    full run reproduces it, unless persist is False.
    """
    source = imageio.load(path)
    if lut is None:
        use_enhance = config.enhance_enabled if enhance_override is None else enhance_override
        if use_enhance and config.enhance_lut_path is not None:
            lut = enhance.load_lut(Path(config.enhance_lut_path))
    when = enhance_when if enhance_when is not None else config.enhance_when
    post_lut = _resolve_enhance(source, lut, when)

    written: dict[str, Path] = {}
    for ratio in config.ratios:
        if not _uses_global_framing(ratio):
            continue
        box, _ = manual_crop_box(
            manual["center_x"], manual["top"], manual["height"], ratio.pair, source.size
        )
        written[ratio.name] = _write_crop(
            source, box.as_pil(), out_dir, path.stem, ratio.name, path.suffix, config, post_lut
        )

    # Override ratios (the square) keep their auto, face-anchored framing, since
    # a raised arm above the head never reaches a hip-high square crop anyway.
    override_ratios = [r for r in config.ratios if not _uses_global_framing(r)]
    if override_ratios:
        own_detector = detector is None
        if own_detector:
            detector = detectors.build(config.detector["name"], config.detector)
        try:
            faces = detector.detect(source.as_rgb_array())
            if len(faces) == 1:
                face = faces[0]
                for ratio in override_ratios:
                    eye_line, headroom = config.framing_for(ratio)
                    sol = solve_crop(
                        face, ratio.pair, source.size,
                        eye_line_fraction=eye_line, headroom_fraction=headroom,
                        eye_to_chin_multiplier=config.eye_to_chin_multiplier,
                    )
                    if not sol.fits and config.fit_to_frame:
                        fh = max_fitting_height(
                            face, ratio.pair, source.size, eye_line_fraction=eye_line
                        )
                        sol = solve_crop(
                            face, ratio.pair, source.size,
                            eye_line_fraction=eye_line, headroom_fraction=headroom,
                            eye_to_chin_multiplier=config.eye_to_chin_multiplier,
                            height_override=fh,
                        )
                    if sol.fits:
                        written[ratio.name] = _write_crop(
                            source, sol.box.as_pil(), out_dir, path.stem, ratio.name, path.suffix, config, post_lut
                        )
            # 0 or >1 faces: leave any existing square crop untouched.
        finally:
            if own_detector:
                detector.close()

    if persist:
        save_manual_crop(out_dir, path.stem, manual)
    return ImageResult(path, OK, None, written)


def run_job(
    images: Iterable[Path],
    out_dir: Path,
    config: Config,
    *,
    on_progress: Callable[[int, int, ImageResult], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    build_sheets: bool | None = None,
    enhance_override: bool | None = None,
    enhance_when_override: str | None = None,
    balance_override: bool | None = None,
    bottom_margin_override: float | None = None,
    preschool_override: bool | None = None,
    use_manual: bool = True,
) -> JobSummary:
    """Run a whole job.

    `on_progress` is called after each image with (done, total, result).
    `should_cancel` is polled between images so a long run can be stopped.
    `enhance_override` forces the enhancement preset on (True) or off (False) for
    this run; None uses the config default. `balance_override` does the same for
    feet-balanced framing. Both back the GUI checkboxes and CLI flags, so the
    toggles can be set per run without editing config.
    """
    images = list(images)
    total = len(images)
    review_dir = out_dir / "review"
    summary = JobSummary()
    all_ratios = list(config.ratios) + list(config.landscape_ratios)
    by_ratio: dict[str, list[tuple[Path, str]]] = {r.name: [] for r in all_ratios}

    use_preschool = config.preschool if preschool_override is None else preschool_override
    preschool_framing = (
        (config.preschool_eye_line_fraction, config.preschool_headroom_fraction)
        if use_preschool
        else None
    )

    use_enhance = config.enhance_enabled if enhance_override is None else enhance_override
    when_enhance = config.enhance_when if enhance_when_override is None else enhance_when_override
    lut = None
    if use_enhance:
        # Preschool mode grades with its own preset (seated indoor look); every
        # other run uses the default preset.
        if use_preschool:
            lut_path = config.enhance_preschool_lut_path
            if lut_path is None:
                raise enhance.EnhanceError(
                    "preschool enhancement was requested but no enhance.preschool_lut_path "
                    "is set in config."
                )
        else:
            lut_path = config.enhance_lut_path
            if lut_path is None:
                raise enhance.EnhanceError(
                    "enhancement was requested but no enhance.lut_path is set in config."
                )
        lut = enhance.load_lut(Path(lut_path))

    # Preschool is a seated mode, so feet-balancing does not apply and the pose
    # model is not loaded even if balancing is otherwise requested.
    use_balance = config.balance_feet if balance_override is None else balance_override
    if use_preschool:
        use_balance = False
    pose_detector = None
    if use_balance:
        if config.pose_model_path is None:
            raise FileNotFoundError(
                "feet-balanced framing was requested but no pose.model_path is set in config."
            )
        from .pose import PoseDetector

        pose_detector = PoseDetector(config.pose_model_path)

    segmenter = None
    if config.landscape_enabled and config.landscape_ratios:
        if config.segment_model_path is None:
            raise FileNotFoundError(
                "landscape handling is on but no segment.model_path is set in config."
            )
        from .segment import PersonSegmenter

        segmenter = PersonSegmenter(config.segment_model_path)

    detector = detectors.build(config.detector["name"], config.detector)
    try:
        for index, path in enumerate(images, start=1):
            if should_cancel is not None and should_cancel():
                summary.cancelled = True
                break

            try:
                manual = load_manual_crop(out_dir, path.stem) if use_manual else None
                if manual is not None:
                    # A saved hand-placement wins over auto framing so manual
                    # fixes survive a re-run of the whole job.
                    result = apply_manual_crop(
                        path, config, out_dir, manual, detector=detector, lut=lut,
                        enhance_when=when_enhance, persist=False,
                    )
                else:
                    result = process_image(
                        path, detector, config, out_dir, lut=lut,
                        pose_detector=pose_detector, balance=use_balance, segmenter=segmenter,
                        enhance_when=when_enhance, bottom_margin=bottom_margin_override,
                        preschool_framing=preschool_framing,
                    )
            except Exception as exc:  # one bad frame must not kill a 400-image run
                result = ImageResult(
                    path, ERROR, f"SKIPPED: error while processing.\n\n{type(exc).__name__}: {exc}"
                )

            if result.reason is not None:
                imageio.copy_for_review(path, review_dir, result.reason)
            for ratio_name, destination in result.written.items():
                by_ratio[ratio_name].append((destination, path.name))

            summary.results.append(result)
            if on_progress is not None:
                on_progress(index, total, result)
    finally:
        detector.close()
        if pose_detector is not None:
            pose_detector.close()
        if segmenter is not None:
            segmenter.close()

    make_sheets = (
        bool(config.contact_sheet.get("enabled", True)) if build_sheets is None else build_sheets
    )
    if make_sheets:
        for ratio in all_ratios:
            sheet = contact_sheet.build(
                by_ratio[ratio.name],
                out_dir / f"contact_sheet_{ratio.name}.png",
                columns=int(config.contact_sheet.get("columns", 6)),
                thumb_width=int(config.contact_sheet.get("thumb_width", 320)),
            )
            if sheet:
                summary.sheets.append(sheet)

    return summary
