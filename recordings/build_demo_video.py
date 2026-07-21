#!/usr/bin/env python3
"""Build Arka hackathon demo video — wrapper around arka terminal_video skill."""

from __future__ import annotations

from pathlib import Path

from arka.media.terminal_video import configure, run_build


def main() -> None:
    configure(project_dir=Path(__file__).resolve().parent.parent)
    run_build()


if __name__ == "__main__":
    main()
