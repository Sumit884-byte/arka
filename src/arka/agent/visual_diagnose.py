"""Two-stage local vision QA: describe pixels first, then diagnose issues."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def diagnose(image: str) -> dict[str, object]:
    path = Path(image).expanduser()
    if not path.is_file():
        raise ValueError(f"image not found: {path}; provide a rendered PNG/JPG")
    from arka.vision.describe import describe_source

    description = describe_source(
        str(path),
        "Describe this rendered UI/game frame objectively: layout, objects, colors, typography, spacing, lighting, hierarchy, and visible text. Do not suggest fixes yet.",
    )
    analysis = describe_source(
        str(path),
        "Inspect this rendered frame for concrete visual defects. Return JSON with keys issues (array), severity (low|medium|high), fixes (array), and verdict (good|needs_fix). Do not invent content that is not visible.",
    )
    return {"image": str(path), "backend": "vllm/auto", "description": description, "diagnosis": analysis}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka visual-diagnose")
    p.add_argument("image")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = diagnose(args.image)
    except (OSError, ValueError, RuntimeError, SystemExit) as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"Description:\n{result['description']}\n\nDiagnosis:\n{result['diagnosis']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
