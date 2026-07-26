#!/usr/bin/env python3
"""Capture Arka web dashboard walkthrough PNGs and optional MP4."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from arka.agent.video_capture import (  # noqa: E402
    DEFAULT_WALKTHROUGH_URL,
    capture,
    dashboard_walkthrough_actions,
    walkthrough_output_dir,
)


def main() -> int:
    url = os.environ.get("ARKA_WALKTHROUGH_URL", DEFAULT_WALKTHROUGH_URL)
    output = walkthrough_output_dir()
    record_video = os.environ.get("ARKA_WALKTHROUGH_NO_VIDEO", "").lower() not in ("1", "true", "yes")

    result = capture(
        url,
        output=str(output),
        actions=dashboard_walkthrough_actions(url),
        record_video=record_video,
        screenshot_steps=True,
    )
    print(f"output: {result['output']}")
    if result["video"]:
        print(f"video: {result['video']}")
    for path in result["screenshots"]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
