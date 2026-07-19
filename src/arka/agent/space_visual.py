"""Arka presets for deterministic space/engineering explainers."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def create(output: str) -> str:
    source = Path(__file__).resolve().parents[3] / "visuals" / "space-tech-vs-engineering.svg"
    target = Path(output).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return str(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka visual space-tech")
    parser.add_argument("--output", default="space-tech-vs-engineering.svg")
    args = parser.parse_args(argv)
    print(f"Created Arka visual: {create(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
