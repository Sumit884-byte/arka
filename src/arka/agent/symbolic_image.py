"""Compose repeatable visual explainers from pre-made image assets locally."""

from __future__ import annotations

import argparse
from pathlib import Path


def comparison(
    left: str, right: str, *, left_title: str, right_title: str, output: str
) -> dict[str, object]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError(
            "symbolic image composition requires Pillow: pip install Pillow"
        ) from exc
    assets = [Path(left).expanduser(), Path(right).expanduser()]
    if not all(path.is_file() for path in assets):
        missing = next(path for path in assets if not path.is_file())
        raise ValueError(f"image asset not found: {missing}")
    images = [Image.open(path).convert("RGB") for path in assets]
    width = max(image.width for image in images)
    height = max(image.height for image in images)
    canvas = Image.new("RGB", (width * 2, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (image, title) in enumerate(zip(images, (left_title, right_title))):
        image.thumbnail((width, height))
        x = index * width + (width - image.width) // 2
        canvas.paste(image, (x, 0))
        draw.rectangle((index * width, 0, (index + 1) * width, 48), fill=(10, 22, 40))
        draw.text((index * width + 18, 16), title, fill="white", font=font)
    draw.line((width, 0, width, height), fill=(20, 30, 45), width=3)
    target = Path(output).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)
    return {
        "output": str(target),
        "template": "comparison",
        "token_cost": "local-only",
        "assets": [str(path) for path in assets],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka symbolic-image")
    sub = p.add_subparsers(dest="command", required=True)
    comp = sub.add_parser("comparison")
    comp.add_argument("--left", required=True)
    comp.add_argument("--right", required=True)
    comp.add_argument("--left-title", default="BEFORE")
    comp.add_argument("--right-title", default="AFTER")
    comp.add_argument("--output", default="comparison.png")
    comp.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = comparison(
            args.left,
            args.right,
            left_title=args.left_title,
            right_title=args.right_title,
            output=args.output,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        p.error(str(exc))
    import json

    print(
        json.dumps(result, indent=2)
        if args.json
        else f"Created local comparison: {result['output']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
