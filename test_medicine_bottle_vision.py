"""
Run medicine bottle vision analysis on sample (or custom) images.

Usage (from project folder):
    python test_medicine_bottle_vision.py
    python test_medicine_bottle_vision.py Med_2.jpeg
    python test_medicine_bottle_vision.py --all-sample

Requires OPENAI_API_KEY in the environment (or your shell session).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from medicine_bottle_vision import analyze_medicine_bottle_image

ROOT = Path(__file__).resolve().parent


def _resolve_image(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path)


def run_one(image_path: Path) -> None:
    print(f"\n{'=' * 60}\nImage: {image_path}\n{'=' * 60}")
    if not image_path.is_file():
        print(f"ERROR: file not found: {image_path}", file=sys.stderr)
        return

    result = analyze_medicine_bottle_image(image_path)
    display = {k: v for k, v in result.items() if k != "raw_text"}
    print(json.dumps(display, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test medicine_bottle_vision on local images.",
    )
    parser.add_argument(
        "images",
        nargs="*",
        help=f"Image file path(s). Relative paths are under {ROOT}",
    )
    parser.add_argument(
        "--all-sample",
        action="store_true",
        help="Run every Med_*.jpeg in the project folder (sorted by name).",
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print(
            "ERROR: OPENAI_API_KEY is not set. Set it in your environment and retry.",
            file=sys.stderr,
        )
        return 1

    if args.all_sample:
        paths = sorted(ROOT.glob("Med_*.jpeg"))
        if not paths:
            print("No Med_*.jpeg files found in project folder.", file=sys.stderr)
            return 1
    elif args.images:
        paths = [_resolve_image(Path(p)) for p in args.images]
    else:
        default = ROOT / "Med_1.jpeg"
        if not default.is_file():
            print(
                f"Default sample {default} not found. Pass image path(s) or use --all-sample.",
                file=sys.stderr,
            )
            return 1
        paths = [default]

    for p in paths:
        try:
            run_one(p)
        except Exception as e:
            print(f"ERROR for {p}: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
