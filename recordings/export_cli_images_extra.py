#!/usr/bin/env python3
"""Export extra Arka CLI showcase JPGs — features beyond the YouTube tutorial."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CAPTURES = ROOT / "terminal_captures_extra"
OUT_DIR = ROOT / "cli-images-extra"
QUALITY = 88

from arka.media.terminal_video import (  # noqa: E402
    BG,
    DIM,
    META,
    PROMPT,
    TEXT,
    WIDTH,
    HEIGHT,
    StyledLine,
    classify_line,
    configure,
    load_mono_font,
    make_title_png,
    render_terminal,
    sanitize_display,
    wrap_prompt,
)


@dataclass
class ImageSpec:
    filename: str
    description: str
    kind: str  # "terminal" | "title" | "grid"
    cmd: str | None = None
    capture: str | None = None
    label: str | None = None
    max_lines: int | None = None
    scroll_offset: int = 0


SPECS: list[ImageSpec] = [
    ImageSpec(
        "01-title-70-skills-beyond-chat.jpg",
        "Title card — 70+ skills beyond chat",
        "grid",
    ),
    ImageSpec(
        "02-skills-list.jpg",
        "arka skills list — plugin ecosystem",
        "terminal",
        cmd="arka skills list",
        capture="skills_list.txt",
        label="Skills",
        max_lines=17,
        scroll_offset=2,
    ),
    ImageSpec(
        "03-repo-health.jpg",
        "arka repo_health — dev tooling scan",
        "terminal",
        cmd="arka repo_health",
        capture="repo_health.txt",
        label="Dev Tools",
        max_lines=17,
    ),
    ImageSpec(
        "04-dev-route-audit.jpg",
        "arka dev route-audit — routing parity audit",
        "terminal",
        cmd="arka dev route-audit",
        capture="dev_route_audit.txt",
        label="Routing",
        max_lines=17,
    ),
    ImageSpec(
        "05-route-chart-btc.jpg",
        'arka route "chart BTC" — offline chart routing',
        "terminal",
        cmd='arka route "chart BTC"',
        capture="route_chart_btc.txt",
        label="Routing",
        max_lines=8,
    ),
    ImageSpec(
        "06-chart-bar.jpg",
        'arka chart bar — charts skill',
        "terminal",
        cmd='arka chart bar --data "Apple:230,Samsung:210,Google:180"',
        capture="chart_bar.txt",
        label="Charts",
        max_lines=10,
    ),
    ImageSpec(
        "07-compose-slides.jpg",
        'arka compose slides "AI agents"',
        "terminal",
        cmd='arka compose slides "AI agents"',
        capture="compose_slides.txt",
        label="Compose",
        max_lines=12,
    ),
    ImageSpec(
        "08-compose-3d-help.jpg",
        "arka compose 3d — 3D model generation",
        "terminal",
        cmd="arka compose 3d --help",
        capture="compose_3d_help.txt",
        label="3D",
        max_lines=14,
    ),
    ImageSpec(
        "09-password-vault.jpg",
        "arka password list — encrypted vault (no secrets shown)",
        "terminal",
        cmd="arka password list",
        capture="password_list.txt",
        label="Vault",
        max_lines=12,
    ),
    ImageSpec(
        "10-bookmarks.jpg",
        "arka bookmark list — saved links",
        "terminal",
        cmd="arka bookmark list",
        capture="bookmark_list.txt",
        label="Bookmarks",
        max_lines=8,
    ),
    ImageSpec(
        "11-docker-ps.jpg",
        "arka docker ps — container integration",
        "terminal",
        cmd="arka docker ps",
        capture="docker_ps.txt",
        label="Docker",
        max_lines=8,
    ),
    ImageSpec(
        "12-github.jpg",
        "arka github — repository activity skill",
        "terminal",
        cmd="arka github --help",
        capture="github_help.txt",
        label="GitHub",
        max_lines=14,
    ),
    ImageSpec(
        "13-agent-hub.jpg",
        "arka agent_hub list — multi-agent launcher",
        "terminal",
        cmd="arka agent_hub list",
        capture="agent_hub_list.txt",
        label="Agent Hub",
        max_lines=14,
    ),
    ImageSpec(
        "14-self-improve.jpg",
        "arka self-improve status — self-improvement loop",
        "terminal",
        cmd="arka self-improve status",
        capture="self_improve_status.txt",
        label="Self Improve",
        max_lines=10,
    ),
    ImageSpec(
        "15-ascii-arka.jpg",
        'arka ascii "ARKA" — visual terminal skill',
        "terminal",
        cmd='arka ascii "ARKA"',
        capture="ascii_arka.txt",
        label="ASCII",
        max_lines=10,
    ),
]


def save_jpg(img, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(path, "JPEG", quality=QUALITY, optimize=True)


def load_capture_lines(name: str, *, max_lines: int | None = None) -> list[str]:
    path = CAPTURES / name
    if not path.exists():
        return [f"(missing capture: {name})"]
    raw = sanitize_display(path.read_text()).splitlines()
    lines: list[str] = []
    for line in raw:
        line = line.replace("\t", "  ")
        if len(line) > 78:
            lines.extend(textwrap.wrap(line, width=78, break_long_words=False, break_on_hyphens=False))
        else:
            lines.append(line)
    if max_lines and len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["  …"]
    return lines


def render_command(
    cmd: str,
    output: list[str],
    *,
    label: str | None = None,
    scroll_offset: int = 0,
) -> "Image.Image":
    font = load_mono_font(34)
    lines: list[StyledLine] = []
    for pl in wrap_prompt("$ ", cmd, font):
        lines.append(StyledLine(pl, "prompt"))
    for raw in output:
        lines.append(StyledLine(raw, classify_line(raw) if raw else "text"))
    return render_terminal(
        lines,
        cursor_visible=False,
        segment_label=label,
        scroll_offset=scroll_offset,
        cmd_caption=cmd,
    )


def make_skills_grid_card(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    for y in range(HEIGHT):
        t = y / max(HEIGHT - 1, 1)
        color = tuple(int(BG[i] + (38 - BG[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 68)
        head_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 30)
        body_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 26)
        mono = load_mono_font(24)
    except OSError:
        title_font = head_font = body_font = ImageFont.load_default()
        mono = body_font

    cx = WIDTH // 2
    draw.text((cx - 420, 48), "70+ Skills Beyond Chat", fill=(255, 255, 255), font=title_font)
    draw.rounded_rectangle((cx - 280, 128, cx + 280, 132), radius=2, fill=PROMPT)

    features = [
        ("Productivity", ["remind", "bookmark", "calendar", "clipboard"]),
        ("Dev & CI", ["repo_health", "route-audit", "github", "docker"]),
        ("Creative", ["compose slides", "compose 3d", "ascii", "chart"]),
        ("Security", ["password vault", "security gates", "config share"]),
        ("Agents", ["agent_hub", "self-improve", "coding-tui", "MCP tools"]),
        ("Plugins", ["skill.json", "astronomy", "charts", "video evidence"]),
    ]

    col_w = (WIDTH - 120) // 3
    x0 = 60
    y0 = 170
    for i, (heading, items) in enumerate(features):
        col = i % 3
        row = i // 3
        x = x0 + col * (col_w + 20)
        y = y0 + row * 260
        draw.rounded_rectangle((x, y, x + col_w - 10, y + 220), radius=12, fill=(22, 27, 34), outline=DIM, width=1)
        draw.text((x + 16, y + 14), heading, fill=META, font=head_font)
        yy = y + 56
        for item in items:
            draw.text((x + 24, yy), f"• {item}", fill=TEXT, font=body_font)
            yy += 36

    foot = "arka skills list  ·  pip install skill folders with skill.json"
    fw = draw.textlength(foot, font=mono)
    draw.text((cx - fw / 2, HEIGHT - 64), foot, fill=DIM, font=mono)

    save_jpg(img, path)


def ensure_captures() -> None:
    capture_py = ROOT / "capture_terminal_extra.py"
    if not CAPTURES.exists() or not any(CAPTURES.glob("*.txt")):
        subprocess.run([sys.executable, str(capture_py)], cwd=str(REPO), check=True)
        return
    meta_path = CAPTURES / "capture_meta.json"
    if meta_path.exists():
        return
    subprocess.run([sys.executable, str(capture_py)], cwd=str(REPO), check=True)


def build_images() -> list[tuple[Path, str, int]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[tuple[Path, str, int]] = []

    for spec in SPECS:
        path = OUT_DIR / spec.filename
        if spec.kind == "grid":
            make_skills_grid_card(path)
        elif spec.kind == "terminal":
            assert spec.cmd and spec.capture
            out = load_capture_lines(spec.capture, max_lines=spec.max_lines)
            img = render_command(
                spec.cmd,
                out,
                label=spec.label,
                scroll_offset=spec.scroll_offset,
            )
            save_jpg(img, path)
        else:
            raise ValueError(f"unknown kind: {spec.kind}")
        results.append((path, spec.description, path.stat().st_size))

    return results


def main() -> None:
    configure(project_dir=REPO, captures=CAPTURES)
    print("=== Capturing extra terminal output ===")
    ensure_captures()

    print("=== Exporting extra CLI JPGs ===")
    results = build_images()

    total = sum(size for _, _, size in results)
    print(f"\nExported {len(results)} images to {OUT_DIR}\n")
    for path, desc, size in results:
        kb = size / 1024
        print(f"  {path.name:42}  {kb:6.1f} KB  {desc}")
    print(f"\nTotal size: {total / (1024 * 1024):.2f} MB")
    print(f"\nRegenerate: python3 recordings/export_cli_images_extra.py")


if __name__ == "__main__":
    main()
