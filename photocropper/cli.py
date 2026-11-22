"""Command line entry point. All work happens in `pipeline.run_job`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import imageio, pipeline
from .config import ConfigError, load as load_config

def _default_config_path() -> Path:
    """Locate config.yaml, including inside a packaged app.

    A frozen build prefers a config.yaml sitting next to the executable, so
    framing stays editable after packaging, and falls back to the copy bundled
    inside the app when there is none.
    """
    if getattr(sys, "frozen", False):
        beside_app = Path(sys.executable).resolve().parent / "config.yaml"
        if beside_app.is_file():
            return beside_app
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(bundled) / "config.yaml"
    return Path(__file__).resolve().parent.parent / "config.yaml"


DEFAULT_CONFIG = _default_config_path()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="photocropper",
        description="Batch face-anchored cropping of portrait photos for print.",
    )
    parser.add_argument("input", type=Path, help="folder of source JPEGs")
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("out"), help="output folder (default: out)"
    )
    parser.add_argument(
        "-c", "--config", type=Path, default=DEFAULT_CONFIG,
        help="path to config.yaml (default: project root)",
    )
    parser.add_argument("--limit", type=int, default=None, help="process only the first N images")
    parser.add_argument(
        "--enhance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="apply the colour/tone preset before cropping (use --no-enhance to skip). "
        "Default: whatever enhance.enabled is in config.yaml.",
    )
    parser.add_argument(
        "--enhance-when",
        choices=["before", "after"],
        default=None,
        help="apply the colour preset before or after cropping. "
        "Default: enhance.when in config.yaml.",
    )
    parser.add_argument(
        "--balance-feet",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="frame full-body sizes with equal top/bottom margins using pose detection "
        "(use --no-balance-feet to skip). Default: framing.balance_feet in config.yaml.",
    )
    parser.add_argument(
        "--bottom-margin",
        type=float,
        default=None,
        help="bottom (feet) margin as a fraction of frame height for balanced framing, "
        "e.g. 0.22 to leave room below a soccer ball. Default: framing.bottom_margin_fraction.",
    )
    parser.add_argument(
        "--preschool",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="use the seated preschool framing (tighter 3/4 crop, bottom at the lap) "
        "on every size instead of the full-length framing; feet-balancing is ignored. "
        "Default: framing.preschool in config.yaml.",
    )
    parser.add_argument(
        "--contact-sheets",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="build the per-size contact sheets (use --no-contact-sheets to skip). "
        "Default: contact_sheet.enabled in config.yaml.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    for warning in config.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if not args.input.is_dir():
        print(f"input folder not found: {args.input}", file=sys.stderr)
        return 2

    images = imageio.find_images(args.input)
    if args.limit is not None:
        images = images[: args.limit]
    if not images:
        print(f"no JPEGs found in {args.input}", file=sys.stderr)
        return 1

    use_enhance = config.enhance_enabled if args.enhance is None else args.enhance
    use_preschool = config.preschool if args.preschool is None else args.preschool
    use_balance = config.balance_feet if args.balance_feet is None else args.balance_feet
    if use_preschool:
        use_balance = False  # seated: feet-balancing does not apply
    print(
        f"cropping {len(images)} image(s) from {args.input}"
        f"  (enhancement {'ON' if use_enhance else 'off'}, "
        f"{'PRESCHOOL (seated)' if use_preschool else 'full-length'}, "
        f"feet-balanced {'ON' if use_balance else 'off'})"
    )

    def report(done: int, total: int, result: pipeline.ImageResult) -> None:
        print(f"  [{done}/{total}] {result.path.name}: {result.status}")

    try:
        summary = pipeline.run_job(
            images, args.out, config, on_progress=report,
            enhance_override=args.enhance, enhance_when_override=args.enhance_when,
            balance_override=args.balance_feet, bottom_margin_override=args.bottom_margin,
            preschool_override=args.preschool,
            build_sheets=args.contact_sheets,
        )
    except (KeyError, FileNotFoundError) as exc:
        print(f"detector error: {exc}", file=sys.stderr)
        return 2

    print("\nsummary")
    print(f"  cropped        {summary.count(pipeline.OK)}")
    if summary.adjusted:
        # Visible on purpose: these are good crops, but framed tighter than
        # configured, so they should be eyeballed on the contact sheet.
        print(f"    of which shortened to fit: {len(summary.adjusted)}")
    print(f"  no face        {summary.count(pipeline.NO_FACE)}")
    print(f"  multiple faces {summary.count(pipeline.MULTI_FACE)}")
    print(f"  out of bounds  {summary.count(pipeline.OUT_OF_BOUNDS)}")
    if summary.count(pipeline.ERROR):
        print(f"  errors         {summary.count(pipeline.ERROR)}")

    medians = summary.framing_medians()
    if medians:
        # The bottom edge is a result of the eye line and headroom, not an
        # input, so report where it actually landed.
        frame, bottom = medians
        print("\nframing check (head-heights, crown to chin = 1.0)")
        print(f"  frame height   median {frame:.2f}")
        print(
            f"  bottom edge    median {bottom:.2f} below crown "
            "(~3.5 hip, ~4.3 mid-thigh, ~5.0 knee on a child)"
        )

    if summary.adjusted:
        tightest = min(r.solution.bottom_below_crown_in_heads for r in summary.adjusted if r.solution)
        print(
            f"\n{len(summary.adjusted)} image(s) had too little space above the head for the\n"
            "configured framing. The frame was shortened, holding the eye line, so the\n"
            f"bottom edge sits higher -- as high as {tightest:.2f} head-heights below the crown."
        )
        for r in summary.adjusted:
            print(f"  {r.path.name}")

    for sheet in summary.sheets:
        print(f"\ncontact sheet: {sheet}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
