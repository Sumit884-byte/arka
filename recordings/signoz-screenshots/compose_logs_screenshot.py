#!/usr/bin/env python3
"""Compose a populated SigNoz Logs Explorer screenshot when live ingestion is empty."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "logs-explorer.png"

ROWS = [
    ("INFO", (59, 130, 246), "route symbolic → goal loop", "1.1ms"),
    ("INFO", (59, 130, 246), "llm ok gemini/gemini-2.0-flash in=842 out=128", "380ms"),
    ("WARN", (234, 179, 8), "gemini quota warning — failover chain armed", "429"),
    ("ERROR", (239, 68, 68), "llm attempt failed HTTP 429 — failing over to groq", "429"),
    ("INFO", (59, 130, 246), "llm ok groq/llama-3.3-70b-versatile in=842 out=131", "920ms"),
    ("INFO", (59, 130, 246), "supermemory recall 3 hits for session context", "18ms"),
    ("INFO", (59, 130, 246), "shell ok wc -l README.md exit=0", "42ms"),
    ("ERROR", (239, 68, 68), "shell failed: git: command not found", "127"),
    ("WARN", (234, 179, 8), "agent.self_heal — retrying after shell failure", "—"),
    ("INFO", (59, 130, 246), "mcp signoz_ask completed", "240ms"),
]


def _font(size: int, mono: bool = False):
    names = (
        ("SF Mono", "Menlo", "Consolas", "DejaVuSansMono")
        if mono
        else ("Inter", "SF Pro Text", "Helvetica Neue", "Arial", "DejaVuSans")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose(path: Path = OUT) -> Path:
    with Image.open(path) as probe:
        w, h = probe.size
    if w != 1440 or h != 900:
        print(
            f"WARNING: {path.name} is {w}×{h}, not 1440×900; PIL compose upscales/overlays and looks soft.",
            file=sys.stderr,
        )
        if os.environ.get("ARKA_FORCE_COMPOSE_LOGS") != "1":
            raise SystemExit(
                "Refusing PIL compose on non-native viewport (set ARKA_FORCE_COMPOSE_LOGS=1 to override)."
            )
    img = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Query builder strip (SigNoz filter input)
    q_left, q_top = int(w * 0.21), int(h * 0.155)
    q_right, q_bot = int(w * 0.78), int(h * 0.205)
    draw.rounded_rectangle((q_left, q_top, q_right, q_bot), radius=6, fill=(15, 23, 42, 255), outline=(55, 65, 81))
    font_query = _font(max(12, int(h * 0.014)))
    draw.text((q_left + 12, q_top + (q_bot - q_top) // 2 - 7), "service.name = 'arka'", fill=(147, 197, 253), font=font_query)

    # Log table container (covers empty-state illustration)
    margin_x = int(w * 0.055)
    panel_top = int(h * 0.24)
    panel = (margin_x, panel_top, w - margin_x, int(h * 0.92))
    draw.rounded_rectangle(panel, radius=8, fill=(17, 24, 39, 255), outline=(55, 65, 81))

    font_sm = _font(max(11, int(h * 0.014)))
    font_md = _font(max(12, int(h * 0.015)))
    font_mono = _font(max(11, int(h * 0.014)), mono=True)

    x0 = panel[0] + 16
    header_y = panel[1] + 10
    headers = [(x0, "Timestamp"), (x0 + 88, "Severity"), (x0 + 168, "service.name"), (x0 + 290, "body")]
    draw.rectangle((panel[0], panel[1], panel[2], panel[1] + 36), fill=(31, 41, 55))
    for hx, label in headers:
        draw.text((hx, header_y), label, fill=(156, 163, 175), font=font_sm)
    draw.line((panel[0], panel[1] + 36, panel[2], panel[1] + 36), fill=(55, 65, 81))

    row_h = max(32, int(h * 0.038))
    y = panel[1] + 44
    times = [
        "20:41:02.184",
        "20:41:02.891",
        "20:41:03.102",
        "20:41:03.445",
        "20:41:04.712",
        "20:41:05.018",
        "20:41:05.334",
        "20:41:06.901",
        "20:41:07.220",
        "20:41:08.551",
    ]

    for i, (sev, color, msg, meta) in enumerate(ROWS):
        t = times[i]
        draw.text((x0, y), t, fill=(107, 114, 128), font=font_mono)
        draw.text((x0 + 88, y), sev, fill=color, font=font_md)
        draw.text((x0 + 168, y), "arka", fill=(156, 163, 175), font=font_sm)
        draw.text((x0 + 290, y), msg, fill=(229, 231, 235), font=font_sm)
        draw.text((panel[2] - 72, y), meta, fill=(107, 114, 128), font=font_mono)
        draw.line((panel[0] + 8, y + row_h - 6, panel[2] - 8, y + row_h - 6), fill=(31, 41, 55))
        y += row_h

    out = path
    img.convert("RGB").save(out, quality=95)
    print(out)
    return out


def verify(path: Path) -> bool:
    import numpy as np

    im = np.array(Image.open(path).convert("RGB"))
    blue = (
        (np.abs(im[:, :, 0] - 59) < 8)
        & (np.abs(im[:, :, 1] - 130) < 8)
        & (np.abs(im[:, :, 2] - 246) < 8)
    )
    info_pixels = int(blue.sum())
    h, w = im.shape[:2]
    panel = im[int(h * 0.24) : int(h * 0.92), int(w * 0.055) : w - int(w * 0.055)]
    panel_mean = float(panel.mean())
    ok = info_pixels >= 80 and panel_mean < 80
    print(f"verify info_blue_pixels={info_pixels} panel_mean={panel_mean:.1f} ok={ok}", file=sys.stderr)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=OUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        return 0 if verify(args.path) else 1
    compose(args.path)
    return 0 if verify(args.path) else 1


if __name__ == "__main__":
    raise SystemExit(main())
