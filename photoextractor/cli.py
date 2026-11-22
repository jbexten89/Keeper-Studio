"""Command line entry point for background removal.

    python -m photoextractor.cli /path/to/images -o out
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import core


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="photoextractor",
        description="Remove the background from photos, writing transparent PNGs.",
    )
    parser.add_argument("input", type=Path, help="folder of images")
    parser.add_argument("-o", "--out", type=Path, default=Path("extracted"), help="output folder")
    args = parser.parse_args(argv)

    if not args.input.is_dir():
        print(f"input folder not found: {args.input}", file=sys.stderr)
        return 2
    images = core.find_images(args.input)
    if not images:
        print(f"no images found in {args.input}", file=sys.stderr)
        return 1

    print(f"extracting {len(images)} image(s) from {args.input}")

    def report(done: int, total: int, result: core.ExtractResult) -> None:
        status = "ok" if result.ok else f"FAILED ({result.error})"
        print(f"  [{done}/{total}] {result.path.name}: {status}")

    results = core.run(images, args.out, on_progress=report)
    ok = sum(1 for r in results if r.ok)
    print(f"\nextracted {ok}/{len(results)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
