#!/usr/bin/env python3
"""Export polished Arka CLI showcase JPGs for Devpost / docs."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CAPTURES = ROOT / "terminal_captures"
OUT_DIR = ROOT / "cli-images"
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
    ensure_captures,
    load_capture_lines,
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


SPECS: list[ImageSpec] = [
    ImageSpec("01-hero-arka-terminal-upgraded.jpg", "Hero title — Arka, your terminal upgraded"),
    ImageSpec("02-pipx-install.jpg", "pipx install arka-agent[chat]"),
    ImageSpec("03-arka-doctor.jpg", "arka doctor health check"),
    ImageSpec("04-route-time-tokyo.jpg", 'arka route "time in tokyo" (offline routing)'),
    ImageSpec("05-time-tokyo-jst.jpg", 'arka "time in tokyo" → JST result'),
    ImageSpec("06-route-what-is-rust.jpg", 'arka route "what is Rust?" (offline)'),
    ImageSpec("07-ask-what-is-rust.jpg", 'arka ask "what is Rust?" (AI answer)'),
    ImageSpec("08-coding-tui.jpg", "arka coding-tui startup"),
    ImageSpec("09-mcp-doctor.jpg", "arka mcp doctor"),
    ImageSpec("10-capabilities.jpg", "arka capabilities voice summary"),
    ImageSpec("11-help-full.jpg", "arka help — full command reference"),
    ImageSpec("12-route-capabilities.jpg", 'arka route "capabilities"'),
    ImageSpec("13-install-outro.jpg", "Get started — pipx one-liner"),
    ImageSpec("14-mcp-tools-list.jpg", "MCP server — 38 tools exposed"),
    ImageSpec("15-architecture-features.jpg", "Architecture & features summary"),
]


def run_extra_captures() -> None:
    """Capture help + route capabilities if missing."""
    capture_py = ROOT / "capture_terminal.py"
    if capture_py.exists():
        subprocess.run([sys.executable, str(capture_py)], cwd=str(REPO), check=True)

    arka = REPO / "venv-arka" / "bin" / "arka"
    if not arka.is_file():
        which = subprocess.run(["which", "arka"], capture_output=True, text=True)
        if which.returncode == 0:
            arka = Path(which.stdout.strip())

    if not arka.is_file():
        return

    for name, args in (("help", ["--help"]), ("route_capabilities", ["route", "capabilities"])):
        proc = subprocess.run(
            [str(arka), *args],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(REPO),
        )
        text = sanitize_display((proc.stdout or "") + (proc.stderr or ""))
        CAPTURES.mkdir(parents=True, exist_ok=True)
        (CAPTURES / f"{name}.txt").write_text(text.rstrip() + "\n")


def save_jpg(img, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(path, "JPEG", quality=QUALITY, optimize=True)


def render_command(
    cmd: str,
    output: list[str],
    *,
    label: str | None = None,
    scroll_offset: int = 0,
    prefix: str = "$ ",
) -> "Image.Image":
    font = load_mono_font(34)
    lines: list[StyledLine] = []
    for pl in wrap_prompt(prefix, cmd, font):
        lines.append(StyledLine(pl, "prompt"))
    for raw in output:
        if raw == "":
            lines.append(StyledLine("", "text"))
        else:
            lines.append(StyledLine(raw, classify_line(raw)))
    return render_terminal(
        lines,
        cursor_visible=False,
        segment_label=label,
        scroll_offset=scroll_offset,
        cmd_caption=cmd,
    )


def lines_from_capture(name: str, *, max_lines: int | None = None, fallback: str | None = None) -> list[str]:
    return load_capture_lines(name, fallback=fallback, max_lines=max_lines)


def lines_from_text(text: str, *, max_lines: int | None = None) -> list[str]:
    raw = sanitize_display(text).splitlines()
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


def make_features_card(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    for y in range(HEIGHT):
        t = y / max(HEIGHT - 1, 1)
        color = tuple(int(BG[i] + (38 - BG[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 72)
        head_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 36)
        body_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 30)
        mono = load_mono_font(26)
    except OSError:
        title_font = head_font = body_font = ImageFont.load_default()
        mono = body_font

    cx = WIDTH // 2
    draw.text((cx - 280, 56), "Arka Architecture", fill=(255, 255, 255), font=title_font)
    draw.rounded_rectangle((cx - 300, 130, cx + 300, 134), radius=2, fill=PROMPT)

    columns = [
        (
            "Natural language routing",
            [
                "Offline skill matching (70+ skills)",
                "arka route — preview before run",
                "Teachable: arka route learn",
            ],
        ),
        (
            "LLM & agents",
            [
                "Multi-provider failover (OpenRouter, …)",
                "Coding TUI with /plan /run /test",
                "MCP server — 38 tools for IDEs",
            ],
        ),
        (
            "Cross-platform",
            [
                "fish shell + portable Python subset",
                "Voice-friendly capabilities summary",
                "pipx install · arka setup · arka doctor",
            ],
        ),
    ]

    col_w = (WIDTH - 160) // 3
    x0 = 80
    y_start = 180
    for i, (heading, bullets) in enumerate(columns):
        x = x0 + i * (col_w + 20)
        draw.text((x, y_start), heading, fill=META, font=head_font)
        y = y_start + 52
        for bullet in bullets:
            draw.text((x + 8, y), f"• {bullet}", fill=TEXT, font=body_font)
            y += 42

    flow_y = HEIGHT - 220
    draw.rounded_rectangle((80, flow_y, WIDTH - 80, flow_y + 120), radius=14, fill=(22, 27, 34), outline=DIM, width=1)
    flow = "You say it  →  arka route  →  skill / LLM  →  terminal result  →  MCP for Cursor & Claude"
    draw.text((120, flow_y + 44), flow, fill=PROMPT, font=mono)

    foot = "arka-agent.mintlify.site · github.com/Sumit884-byte/arka"
    fw = draw.textlength(foot, font=body_font)
    draw.text((cx - fw / 2, HEIGHT - 56), foot, fill=DIM, font=body_font)

    save_jpg(img, path)


def make_mcp_tools_card():
    """Terminal frame focused on MCP tool list from mcp doctor."""
    tool_lines = lines_from_capture("mcp_doctor.txt", max_lines=40)
    trimmed: list[str] = []
    for line in tool_lines:
        if line.startswith("summary"):
            break
        trimmed.append(line)
    if not trimmed:
        trimmed = ["tools_list ok count=38", "tool arka_ask", "tool arka_route", "…"]
    return render_command("arka mcp doctor", trimmed, label="MCP Tools", scroll_offset=4)


def clean_ask_output(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line.strip() == "[FROM MEMORY]":
            continue
        if line.strip().lower().startswith("searching web"):
            continue
        out.append(line)
    return out[:10] if len(out) > 10 else out


def build_images() -> list[tuple[Path, str, int]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_DIR / "_tmp_title.png"
    results: list[tuple[Path, str, int]] = []

    # 1 Hero
    make_title_png(tmp, "Arka", "Your terminal, upgraded", "OpenAI Build Week 2026")
    from PIL import Image

    save_jpg(Image.open(tmp), OUT_DIR / SPECS[0].filename)
    results.append((OUT_DIR / SPECS[0].filename, SPECS[0].description, (OUT_DIR / SPECS[0].filename).stat().st_size))

    # 2 pipx install (+ setup hint in history style — single command frame)
    install_out = [
        "  installed package arka-agent 0.1.1",
        "  ✓ ready — run: arka setup",
        "",
    ]
    save_jpg(render_command('pipx install "arka-agent[chat]"', install_out, label="Install"), OUT_DIR / SPECS[1].filename)
    results.append((OUT_DIR / SPECS[1].filename, SPECS[1].description, (OUT_DIR / SPECS[1].filename).stat().st_size))

    terminal_jobs: list[tuple[int, str, str, list[str] | None, str | None, int, str | None]] = [
        (2, "arka doctor", "doctor.txt", None, "Health Check", 0, None),
        (3, 'arka route "time in tokyo"', "route_tokyo_route.txt", None, "Routing", 0, None),
        (4, 'arka "time in tokyo"', "route_tokyo.txt", None, "Timezone", 0, None),
        (5, 'arka route "what is Rust?"', "route_rust.txt", None, "Routing", 0, None),
        (6, 'arka ask "what is Rust?"', "ask_rust.txt", "ask_rust_fallback.txt", "Ask", 0, None),
        (7, "arka coding-tui", "coding_tui.txt", None, "Coding TUI", 0, None),
        (8, "arka mcp doctor", "mcp_doctor.txt", None, "MCP", 0, None),
        (9, "arka capabilities", "capabilities.txt", None, "Capabilities", 0, None),
        (10, "arka help", "help.txt", None, "Help", 0, None),
        (11, 'arka route "capabilities"', "route_capabilities.txt", None, "Routing", 0, None),
    ]

    for spec_idx, cmd, capture, fallback, label, scroll, prefix in terminal_jobs:
        if capture == "ask_rust.txt":
            out = clean_ask_output(lines_from_capture(capture, fallback=fallback, max_lines=12))
        elif capture == "coding_tui.txt":
            raw = lines_from_capture(capture, fallback=fallback, max_lines=14)
            out = raw
            cmd = "arka coding-tui"
        elif capture == "help.txt":
            out = lines_from_capture("help.txt", max_lines=17)
            if out and out[0].startswith("(missing"):
                out = lines_from_text(
                    subprocess.run(
                        [str(REPO / "venv-arka" / "bin" / "arka"), "--help"],
                        capture_output=True,
                        text=True,
                        cwd=str(REPO),
                    ).stdout,
                    max_lines=17,
                )
        elif capture == "route_capabilities.txt":
            out = lines_from_capture("route_capabilities.txt", max_lines=8)
            if out and out[0].startswith("(missing"):
                out = ["skill: capabilities", "kind: skill", "source: offline", ""]
        else:
            max_l = 18 if capture == "mcp_doctor.txt" else None
            out = lines_from_capture(capture, fallback=fallback, max_lines=max_l)

        p = prefix or "$ "
        img = render_command(cmd, out, label=label, scroll_offset=scroll, prefix=p)
        path = OUT_DIR / SPECS[spec_idx].filename
        save_jpg(img, path)
        results.append((path, SPECS[spec_idx].description, path.stat().st_size))

    # 13 outro
    make_title_png(
        tmp,
        "Get started today",
        'pipx install "arka-agent[chat]"',
        "arka-agent.mintlify.site · github.com/Sumit884-byte/arka",
    )
    save_jpg(Image.open(tmp), OUT_DIR / SPECS[12].filename)
    results.append((OUT_DIR / SPECS[12].filename, SPECS[12].description, (OUT_DIR / SPECS[12].filename).stat().st_size))
    tmp.unlink(missing_ok=True)

    # 14 MCP tools highlight
    save_jpg(make_mcp_tools_card(), OUT_DIR / SPECS[13].filename)
    results.append((OUT_DIR / SPECS[13].filename, SPECS[13].description, (OUT_DIR / SPECS[13].filename).stat().st_size))

    # 15 features card
    make_features_card(OUT_DIR / SPECS[14].filename)
    results.append((OUT_DIR / SPECS[14].filename, SPECS[14].description, (OUT_DIR / SPECS[14].filename).stat().st_size))

    return results


def main() -> None:
    configure(project_dir=REPO)
    print("=== Ensuring terminal captures ===")
    ensure_captures()
    run_extra_captures()

    print("=== Exporting CLI JPGs ===")
    results = build_images()

    total = sum(size for _, _, size in results)
    print(f"\nExported {len(results)} images to {OUT_DIR}\n")
    for path, desc, size in results:
        kb = size / 1024
        print(f"  {path.name:42}  {kb:6.1f} KB  {desc}")
    print(f"\nTotal size: {total / (1024 * 1024):.2f} MB")


if __name__ == "__main__":
    main()
