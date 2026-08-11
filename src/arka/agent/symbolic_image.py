"""Compose repeatable visual explainers from pre-made image assets locally."""

from __future__ import annotations

import argparse
import json

from arka.agent.meme_templates import comparison as _comparison


def comparison(
    left: str, right: str, *, left_title: str, right_title: str, output: str
) -> dict[str, object]:
    return _comparison(
        left=left,
        right=right,
        left_title=left_title,
        right_title=right_title,
        output=output,
    )


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
    print(
        json.dumps(result, indent=2)
        if args.json
        else f"Created local comparison: {result['output']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
