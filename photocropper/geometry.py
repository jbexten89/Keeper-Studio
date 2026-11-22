"""Crop-box solving. Pure arithmetic -- no image or model dependencies.

THE GEOMETRY, AND WHY THE BOTTOM EDGE IS NOT AN INPUT
-----------------------------------------------------
Two vertical constraints are configured:

    eye_y   - top = eye_line_fraction * H
    crown_y - top = headroom_fraction  * H

Subtracting one from the other eliminates `top` and solves H outright:

    H = (eye_y - crown_y) / (eye_line_fraction - headroom_fraction)

So the eye line and the headroom together *fully determine the crop height*.
The output ratio then sets width only (W = aspect * H), and the bottom edge is
whatever falls out at `top + H`.

That has two consequences worth knowing:

1. Where the bottom lands (waist / mid-thigh / knee) is a RESULT, not a dial.
   It cannot be specified independently -- the geometry is already fully
   constrained. To move the bottom edge, change `headroom_fraction`: a smaller
   headroom yields a shorter frame and a higher bottom cut. Every run reports
   the bottom position in head-heights so this can be calibrated empirically.

2. Crop height is identical across every output ratio, because H does not
   depend on aspect. Only the width changes. This is the desirable behaviour --
   the 4x5 and the 5x7 of the same child are framed identically top to bottom.

SENSITIVITY
-----------
The denominator (eye_line_fraction - headroom_fraction) is usually small, and
H is that denominator divided into the crown-to-eye distance. At eye 0.25 /
headroom 0.15 the denominator is 0.10, so H is 10x the crown-to-eye distance
and any error in the crown estimate is amplified 10x. `amplification()` exposes
this so the config loader can warn on unstable settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd

from .detectors.base import FaceObservation, Point


@dataclass(frozen=True)
class CropBox:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def as_pil(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True)
class Overflow:
    """How far the ideal box falls outside the source, per edge, in pixels."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def any(self) -> bool:
        return max(self.left, self.top, self.right, self.bottom) > 0

    def describe(self) -> str:
        parts = [
            f"{name} by {value}px"
            for name, value in (
                ("left", self.left),
                ("top", self.top),
                ("right", self.right),
                ("bottom", self.bottom),
            )
            if value > 0
        ]
        return ", ".join(parts)


@dataclass(frozen=True)
class CropSolution:
    box: CropBox
    overflow: Overflow
    crown: Point
    # Diagnostics, all in head-heights (crown-to-chin), for calibrating framing.
    head_height_px: float
    frame_height_in_heads: float
    bottom_below_crown_in_heads: float
    eye_line_actual: float
    headroom_actual: float

    @property
    def fits(self) -> bool:
        return not self.overflow.any


def amplification(eye_line_fraction: float, headroom_fraction: float) -> float:
    """Factor by which crown-estimate error propagates into crop height."""
    denominator = eye_line_fraction - headroom_fraction
    if denominator <= 0:
        raise ValueError(
            f"eye_line_fraction ({eye_line_fraction}) must be greater than "
            f"headroom_fraction ({headroom_fraction}); otherwise the eye line "
            "would sit above the top of the head and no crop height exists."
        )
    return 1.0 / denominator


def estimate_crown(face: FaceObservation, eye_to_chin_multiplier: float) -> Point:
    """Estimate the top of the skull.

    A face mesh stops at the hairline -- landmark 10 is upper forehead, not
    crown -- so the crown is extrapolated upward from the eye-to-chin span.
    The multiplier is the crown-to-eye distance expressed as a fraction of the
    eye-to-chin distance. It is ~1.0 for adults (eyes near head mid-height) and
    higher for young children, whose craniums are proportionally larger, which
    is why it is configurable rather than a constant.

    The result is clamped to never fall below the forehead landmark: the crown
    cannot be lower than a point known to be on the head.
    """
    eye_x, eye_y = face.eye_mid
    eye_to_chin = face.chin[1] - eye_y
    crown_y = eye_y - eye_to_chin * eye_to_chin_multiplier
    return (eye_x, min(crown_y, face.forehead_top[1]))


def _snap_to_exact_ratio(
    height: float, ratio_w: int, ratio_h: int, *, round_down: bool = False
) -> tuple[int, int]:
    """Round to integer dimensions that hit the print ratio exactly.

    Print ratios should be exact, so height is snapped to a multiple of the
    reduced denominator. The shift is at most a couple of pixels.

    `round_down` matters when the height is a hard ceiling: rounding up by a
    pixel there would push the box back outside the image it was just fitted
    to.
    """
    divisor = gcd(ratio_w, ratio_h)
    rw, rh = ratio_w // divisor, ratio_h // divisor
    raw = height / rh
    units = int(raw) if round_down else round(raw)
    units = max(1, units)
    return rh * units, rw * units


def max_fitting_height(
    face: FaceObservation,
    ratio: tuple[int, int],
    image_size: tuple[int, int],
    *,
    eye_line_fraction: float,
) -> float:
    """Tallest crop that stays inside the image with the eye line held fixed.

    Used when the ideal frame does not fit. The eye line and the horizontal
    eye-midpoint anchor are both preserved, so faces still land in the same
    place across the batch; the frame simply gets shorter, which raises the
    bottom edge. Each image edge imposes its own ceiling and the tightest wins.
    """
    image_w, image_h = image_size
    aspect = ratio[0] / ratio[1]
    eye_x, eye_y = face.eye_mid

    ceilings = (
        eye_y / eye_line_fraction,                     # top edge of the image
        (image_h - eye_y) / (1.0 - eye_line_fraction),  # bottom edge
        2.0 * eye_x / aspect,                           # left edge
        2.0 * (image_w - eye_x) / aspect,               # right edge
    )
    return max(0.0, min(ceilings))


def group_crop_box(
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
    ratio_a: int,
    ratio_b: int,
    margin_fraction: float,
) -> CropBox | None:
    """Frame a landscape group crop around the group's bounding box.

    The crop contains the whole group -- so no side, top or bottom of the group
    is cut -- with `margin_fraction` of proper spacing around it where the image
    allows, centred on the group. Returns None when the group cannot fit the
    print ratio inside the image without trimming into it (a group wider than the
    aspect can hold), so the caller can route that image to review.
    """
    image_w, image_h = image_size
    x0, y0, x1, y1 = bbox
    group_w, group_h = x1 - x0, y1 - y0
    long_side, short_side = max(ratio_a, ratio_b), min(ratio_a, ratio_b)
    divisor = gcd(long_side, short_side)
    rw, rh = long_side // divisor, short_side // divisor  # rw >= rh; aspect = rw/rh
    aspect = rw / rh

    # Smallest crop of this aspect that still contains the whole group.
    min_h = max(group_h, group_w / aspect)
    if min_h > image_h or aspect * min_h > image_w:
        return None  # group too wide/tall for this ratio -> cannot avoid a cut

    # Add proper margin where the image allows, then snap to the exact ratio.
    target_h = min(min_h * (1.0 + 2.0 * margin_fraction), float(image_h), image_w / aspect)
    units = int(target_h) // rh
    crop_h, crop_w = rh * units, rw * units
    # Snap can round the box a hair below the group; nudge up one unit if so and
    # it still fits.
    if (crop_w < group_w or crop_h < group_h) and rw * (units + 1) <= image_w and rh * (units + 1) <= image_h:
        units += 1
        crop_h, crop_w = rh * units, rw * units

    gcx, gcy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    left = int(round(min(max(gcx - crop_w / 2.0, 0.0), image_w - crop_w)))
    top = int(round(min(max(gcy - crop_h / 2.0, 0.0), image_h - crop_h)))
    return CropBox(left=left, top=top, width=crop_w, height=crop_h)


def manual_crop_box(
    center_x: float,
    top: float,
    height: float,
    ratio: tuple[int, int],
    image_size: tuple[int, int],
    *,
    clamp: bool = True,
) -> tuple[CropBox, Overflow]:
    """Build a crop box from a hand-placed full-length framing.

    Unlike solve_crop this uses no face landmarks: the caller supplies the
    vertical extent (top, height) and horizontal centre directly, as set in the
    Adjust window. Height is snapped to the exact print ratio (rounding down so
    a pixel of rounding cannot push the box past an edge it was fitted to), the
    width follows from the aspect, and the box is optionally clamped inside the
    image. All sizes that share the global framing are built from one such
    placement, so the set stays consistent.
    """
    image_w, image_h = image_size
    ratio_w, ratio_h = ratio
    h, w = _snap_to_exact_ratio(height, ratio_w, ratio_h, round_down=True)
    # Shrink to the largest box of this ratio that fits the image, so an
    # oversized request can never produce a crop that runs off the edge (which
    # would fill with black). Aspect is preserved; only the size drops.
    if w > image_w or h > image_h:
        scale = min(image_w / w, image_h / h)
        h, w = _snap_to_exact_ratio(h * scale, ratio_w, ratio_h, round_down=True)
    left = round(center_x - w / 2.0)
    top_i = round(top)
    if clamp:
        left = max(0, min(left, image_w - w))
        top_i = max(0, min(top_i, image_h - h))
    box = CropBox(left=left, top=top_i, width=w, height=h)
    overflow = Overflow(
        left=max(0, -box.left),
        top=max(0, -box.top),
        right=max(0, box.right - image_w),
        bottom=max(0, box.bottom - image_h),
    )
    return box, overflow


def max_fitting_height_balanced(
    face: FaceObservation,
    ratio: tuple[int, int],
    image_size: tuple[int, int],
    *,
    margin_top: float,
    eye_to_chin_multiplier: float,
) -> float:
    """Tallest balanced crop that fits, holding the crown at the top margin.

    The crown stays margin_top from the top; the frame simply gets shorter,
    which pulls the bottom up. Each image edge sets a ceiling and the tightest
    wins.
    """
    image_w, image_h = image_size
    aspect = ratio[0] / ratio[1]
    crown_x, crown_y = estimate_crown(face, eye_to_chin_multiplier)
    eye_x, eye_y = face.eye_mid
    ceilings = (
        crown_y / margin_top,                       # top edge stays in frame
        (image_h - crown_y) / (1.0 - margin_top),   # bottom edge stays in frame
        2.0 * eye_x / aspect,                        # left edge
        2.0 * (image_w - eye_x) / aspect,            # right edge
    )
    return max(0.0, min(ceilings))


def solve_crop_balanced(
    face: FaceObservation,
    feet_y: float,
    ratio: tuple[int, int],
    image_size: tuple[int, int],
    *,
    margin_top: float,
    margin_bottom: float,
    eye_to_chin_multiplier: float,
    height_override: float | None = None,
) -> CropSolution:
    """Solve a full-body crop with configurable top and bottom margins.

    The crown sits margin_top from the top and the feet sit margin_bottom from
    the bottom, so the crop height follows the person's own crown-to-feet span,
    not their head size. When the margins are equal the subject is centred; a
    larger margin_bottom leaves extra room below the feet -- room for a prop the
    feet rest on, such as a soccer ball that hangs below the detected feet.
    """
    image_w, image_h = image_size
    ratio_w, ratio_h = ratio
    if not (0.0 < margin_top < 1.0 and 0.0 < margin_bottom < 1.0 and margin_top + margin_bottom < 1.0):
        raise ValueError("margin_top and margin_bottom must be positive and sum below 1")

    crown_x, crown_y = estimate_crown(face, eye_to_chin_multiplier)
    eye_x, eye_y = face.eye_mid
    span = feet_y - crown_y  # crown to feet
    if span <= 0:
        raise ValueError("degenerate: feet detected at or above the crown")

    if height_override is None:
        height_f = span / (1.0 - margin_top - margin_bottom)
        height, width = _snap_to_exact_ratio(height_f, ratio_w, ratio_h)
        # Ideal frame: crown at margin_top, feet at margin_bottom. Any overflow
        # is left visible so the caller can shorten the frame to fit.
        top = crown_y - margin_top * height
    else:
        height, width = _snap_to_exact_ratio(height_override, ratio_w, ratio_h, round_down=True)
        # Shortened frame (had to shrink for width or an edge): split the leftover
        # space by the top:bottom margin ratio so the intended asymmetry is kept,
        # then clamp inside the image so the subject never runs off-frame.
        frac_top = margin_top / (margin_top + margin_bottom)
        top = crown_y - (height - span) * frac_top
        top = max(0.0, min(top, float(image_h - height)))
    top = round(top)
    left = round(eye_x - width / 2.0)
    box = CropBox(left=left, top=top, width=width, height=height)

    overflow = Overflow(
        left=max(0, -box.left),
        top=max(0, -box.top),
        right=max(0, box.right - image_w),
        bottom=max(0, box.bottom - image_h),
    )

    head_height_px = face.chin[1] - crown_y
    return CropSolution(
        box=box,
        overflow=overflow,
        crown=(crown_x, crown_y),
        head_height_px=head_height_px,
        frame_height_in_heads=height / head_height_px if head_height_px > 0 else float("nan"),
        bottom_below_crown_in_heads=(
            (box.bottom - crown_y) / head_height_px if head_height_px > 0 else float("nan")
        ),
        eye_line_actual=(eye_y - box.top) / height,
        headroom_actual=(crown_y - box.top) / height,
    )


def solve_crop(
    face: FaceObservation,
    ratio: tuple[int, int],
    image_size: tuple[int, int],
    *,
    eye_line_fraction: float,
    headroom_fraction: float,
    eye_to_chin_multiplier: float,
    height_override: float | None = None,
) -> CropSolution:
    """Solve the crop box for one face at one output ratio.

    By default the returned box is the *ideal* box, never shifted or shrunk to
    fit the source; callers inspect `.fits` and route failures to review.

    `height_override` forces a specific frame height, which is how the
    fit-to-frame fallback shortens a frame that would otherwise overflow. The
    eye line and horizontal anchor still hold, so only the bottom edge moves.
    """
    image_w, image_h = image_size
    ratio_w, ratio_h = ratio

    denominator = eye_line_fraction - headroom_fraction
    if denominator <= 0:
        raise ValueError("eye_line_fraction must exceed headroom_fraction")

    crown_x, crown_y = estimate_crown(face, eye_to_chin_multiplier)
    eye_x, eye_y = face.eye_mid

    crown_to_eye = eye_y - crown_y
    if crown_to_eye <= 0:
        raise ValueError("degenerate landmarks: crown estimated at or below the eye line")

    if height_override is None:
        height_f = crown_to_eye / denominator
        height, width = _snap_to_exact_ratio(height_f, ratio_w, ratio_h)
    else:
        # A ceiling, so round down: a pixel of rounding up would put the box
        # back outside the image it was just fitted to.
        height, width = _snap_to_exact_ratio(height_override, ratio_w, ratio_h, round_down=True)

    # Anchor vertically on the eye line, horizontally on the eye midpoint.
    top = round(eye_y - eye_line_fraction * height)
    left = round(eye_x - width / 2.0)
    box = CropBox(left=left, top=top, width=width, height=height)

    overflow = Overflow(
        left=max(0, -box.left),
        top=max(0, -box.top),
        right=max(0, box.right - image_w),
        bottom=max(0, box.bottom - image_h),
    )

    head_height_px = face.chin[1] - crown_y
    return CropSolution(
        box=box,
        overflow=overflow,
        crown=(crown_x, crown_y),
        head_height_px=head_height_px,
        frame_height_in_heads=height / head_height_px if head_height_px > 0 else float("nan"),
        bottom_below_crown_in_heads=(
            (box.bottom - crown_y) / head_height_px if head_height_px > 0 else float("nan")
        ),
        eye_line_actual=(eye_y - box.top) / height,
        headroom_actual=(crown_y - box.top) / height,
    )
