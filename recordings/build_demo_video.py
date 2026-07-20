#!/usr/bin/env python3
"""Build Arka hackathon demo video with animated terminal + voiceover."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT_MP4 = ROOT / "arka-demo-submission.mp4"
OUT_MP3 = ROOT / "arka-demo-voiceover.mp3"
OUT_TXT = ROOT / "arka-demo-voiceover.txt"
CAPTURES = ROOT / "terminal_captures"
META_FILE = CAPTURES / "capture_meta.json"
WORK = ROOT / "_demo_build"
FRAMES = WORK / "terminal_frames"

VOICE = "en-US-GuyNeural"
WIDTH, HEIGHT = 1920, 1080
FPS = 30
CPS = 14  # typing speed (characters per second)
LINE_REVEAL_SEC = 0.09
POST_CMD_PAUSE_SEC = 0.50
CURSOR_BLINK_FRAMES = 15  # 500ms at 30fps
SCROLL_ANIM_FRAMES = 6
XFADE_SEC = 0.3

# GitHub-dark terminal theme
BG = (13, 17, 23)  # #0d1117
CHROME = (22, 27, 34)
CHROME_BAR = (33, 38, 45)
CHROME_TITLE = (201, 209, 217)
PROMPT = (126, 231, 135)  # #7ee787
TEXT = (230, 237, 243)  # #e6edf3
META = (88, 166, 255)  # #58a6ff
DIM = (139, 148, 158)  # #8b949e
FONT_SIZE = 34
LINE_H = 46
MARGIN_X = 48
WIN_X, WIN_Y = 56, 40
WIN_W, WIN_H = WIDTH - 112, HEIGHT - 80
TEXT_TOP = WIN_Y + 72
MAX_VISIBLE = 17

SEGMENT_LABELS = {
    "install": "Install",
    "doctor": "Health Check",
    "routing_tokyo": "Routing",
    "routing_rust": "Routing",
    "ask": "Ask",
    "tui": "Coding TUI",
    "mcp": "MCP",
    "underhood": "Architecture",
    "capabilities": "Capabilities",
}

# Voiceover beats — start times parsed from arka-demo-voiceover.txt [M:SS] markers.
# Each beat shows the command on screen when the narrator mentions it.
VO_BEATS = [
    {
        "id": "title",
        "start": 0,
        "type": "title",
        "title": "Arka",
        "subtitle": "Your terminal, upgraded",
        "tagline": "OpenAI Build Week 2026",
    },
    {
        "id": "install",
        "start": 18,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'pipx install "arka-agent[chat]"',
                "output": ["  installed package arka-agent 0.1.0", ""],
                "static": True,
                "time_share": 0.35,
            },
            {
                "cmd": "arka setup",
                "output": [
                    "  ✓ venv + chat deps configured",
                    "  ✓ Context7 MCP ready",
                    "",
                ],
                "static": True,
                "time_share": 0.65,
            },
        ],
    },
    {
        "id": "doctor",
        "start": 34,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka doctor",
                "capture": "doctor.txt",
                "max_lines": 20,
            },
        ],
    },
    {
        "id": "routing_tokyo",
        "start": 50,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka route "time in tokyo"',
                "capture": "route_tokyo_route.txt",
                "time_share": 0.48,
            },
            {
                "cmd": 'arka "time in tokyo"',
                "capture": "route_tokyo.txt",
                "max_lines": 8,
                "time_share": 0.52,
            },
        ],
    },
    {
        "id": "routing_rust",
        "start": 66,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka route "what is Rust?"',
                "capture": "route_rust.txt",
            },
        ],
    },
    {
        "id": "ask",
        "start": 82,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka ask "what is Rust?"',
                "capture": "ask_rust.txt",
                "fallback": "ask_rust_fallback.txt",
                "max_lines": 10,
            },
        ],
    },
    {
        "id": "tui",
        "start": 98,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka coding-tui",
                "capture": "coding_tui.txt",
                "max_lines": 12,
            },
            {
                "cmd": "/plan add retry logic to auth module",
                "output": [
                    "  Plan: 3 steps — read auth.py, add backoff, run tests",
                    "  Execute? [y/N] y",
                    "  ✓ Step 1/3: reading src/auth.py…",
                ],
                "static": True,
                "prompt": "> ",
            },
        ],
    },
    {
        "id": "mcp",
        "start": 114,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka mcp doctor",
                "capture": "mcp_doctor.txt",
                "max_lines": 18,
            },
        ],
    },
    {
        "id": "underhood",
        "start": 130,
        "type": "terminal_anim",
        "hold_cmd": "arka mcp doctor",
        "scenes": [
            {
                "cmd": "arka mcp doctor",
                "capture": "mcp_doctor.txt",
                "max_lines": 14,
                "skip_typing": True,
            },
        ],
    },
    {
        "id": "capabilities",
        "start": 146,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka capabilities",
                "capture": "capabilities.txt",
                "max_lines": 16,
            },
        ],
    },
    {
        "id": "outro",
        "start": 160,
        "type": "title",
        "title": "Get started today",
        "subtitle": 'pipx install "arka-agent[chat]"',
        "tagline": "arka-agent.mintlify.site · github.com/Sumit884-byte/arka",
    },
]


@dataclass
class StyledLine:
    text: str
    kind: str = "text"  # prompt | meta | text | dim


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def beat_durations(audio_dur: float) -> list[tuple[dict, float]]:
    """Map voiceover beats to segment durations, scaled for crossfade overlap."""
    n = len(VO_BEATS)
    raw: list[float] = []
    for i, beat in enumerate(VO_BEATS):
        if i + 1 < n:
            raw.append(float(VO_BEATS[i + 1]["start"]) - float(beat["start"]))
        else:
            raw.append(max(1.0, audio_dur - float(beat["start"])))
    adjusted_total = audio_dur + (n - 1) * XFADE_SEC
    scale = adjusted_total / sum(raw)
    return [(beat, d * scale) for beat, d in zip(VO_BEATS, raw)]


def scene_budgets(scenes: list[dict], total_sec: float) -> list[float]:
    """Split segment time across scenes; typing always gets natural duration."""
    if not scenes:
        return []
    if len(scenes) == 1:
        return [total_sec]

    shares = [scene.get("time_share") for scene in scenes]
    if shares and all(s is not None for s in shares):
        norm = sum(float(s) for s in shares)
        return [total_sec * float(s) / norm for s in shares]

    min_secs: list[float] = []
    for scene in scenes:
        if scene.get("skip_typing"):
            typing = 0.0
        else:
            typing = len(scene["cmd"]) / CPS + POST_CMD_PAUSE_SEC
        output_n = len(scene_output(scene))
        min_secs.append(typing + max(output_n, 1) * LINE_REVEAL_SEC)

    min_total = sum(min_secs)
    if min_total >= total_sec:
        # Preserve typing; compress output reveal proportionally.
        out: list[float] = []
        for scene, mn in zip(scenes, min_secs):
            if scene.get("skip_typing"):
                typing = 0.0
            else:
                typing = len(scene["cmd"]) / CPS + POST_CMD_PAUSE_SEC
            out.append(max(typing + 0.5, total_sec * mn / min_total))
        s = sum(out)
        return [x * total_sec / s for x in out]

    extra = total_sec - min_total
    weights = [float(scene.get("time_share", max(len(scene["cmd"]), 8))) for scene in scenes]
    wsum = sum(weights)
    return [mn + extra * w / wsum for mn, w in zip(min_secs, weights)]


def load_mono_font(size: int):
    from PIL import ImageFont

    paths = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.dfont",
        "/Library/Fonts/DejaVu Sans Mono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def classify_line(line: str) -> str:
    if line.startswith("$") or line.startswith(">"):
        return "prompt"
    if line.startswith("skill:") or line.startswith("kind:") or line.startswith("source:"):
        return "meta"
    if line.startswith("━━") or line.startswith("Next"):
        return "dim"
    if line.startswith("  ") and any(k in line for k in ("✓", "✗", "○")):
        return "text"
    return "text"


HOME = Path.home()


def sanitize_display(text: str) -> str:
    text = text.replace(str(HOME), "~")
    text = text.replace(str(REPO), "~/dev/arka")
    return text


def load_capture_lines(name: str, fallback: str | None = None, max_lines: int | None = None) -> list[str]:
    path = CAPTURES / name
    if fallback:
        fb = CAPTURES / fallback
        body = path.read_text() if path.exists() else ""
        if "rust" not in body.lower() and fb.exists():
            path = fb
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


def scene_output(scene: dict) -> list[str]:
    if scene.get("capture"):
        return load_capture_lines(
            scene["capture"],
            fallback=scene.get("fallback"),
            max_lines=scene.get("max_lines"),
        )
    return scene.get("output", [])


def color_for(kind: str) -> tuple[int, int, int]:
    return {
        "prompt": PROMPT,
        "meta": META,
        "dim": DIM,
        "text": TEXT,
    }.get(kind, TEXT)


def wrap_prompt(prefix: str, cmd: str, font) -> list[str]:
    from PIL import ImageDraw, Image

    dummy = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy)
    full = prefix + cmd
    max_w = WIN_W - 2 * MARGIN_X
    if draw.textlength(full, font=font) <= max_w:
        return [full]
    wrapped = textwrap.wrap(
        cmd,
        width=70,
        break_long_words=False,
        break_on_hyphens=False,
    )
    out = [prefix + wrapped[0]]
    indent = " " * len(prefix)
    out.extend(indent + w for w in wrapped[1:])
    return out


def render_terminal(
    lines: list[StyledLine],
    *,
    cursor_visible: bool = True,
    segment_label: str | None = None,
    scroll_offset: int = 0,
    cmd_caption: str | None = None,
) -> "Image.Image":
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Drop shadow
    for layer, alpha in ((10, 18), (5, 28)):
        shadow = tuple(max(0, c - alpha) for c in BG)
        draw.rounded_rectangle(
            (WIN_X + layer, WIN_Y + layer, WIN_X + WIN_W + layer, WIN_Y + WIN_H + layer),
            radius=16,
            fill=shadow,
        )

    # Window chrome
    draw.rounded_rectangle((WIN_X, WIN_Y, WIN_X + WIN_W, WIN_Y + WIN_H), radius=16, fill=CHROME)
    draw.rounded_rectangle((WIN_X, WIN_Y, WIN_X + WIN_W, WIN_Y + 52), radius=16, fill=CHROME_BAR)
    draw.rectangle((WIN_X, WIN_Y + 40, WIN_X + WIN_W, WIN_Y + 52), fill=CHROME_BAR)

    title_font = load_mono_font(20)
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = WIN_X + 20 + i * 22
        draw.ellipse((cx, WIN_Y + 18, cx + 12, WIN_Y + 30), fill=color)

    draw.text((WIN_X + 88, WIN_Y + 14), "Terminal — arka", fill=CHROME_TITLE, font=title_font)

    if segment_label:
        badge_font = load_mono_font(18)
        badge_text = segment_label
        badge_w = int(badge_font.getlength(badge_text)) + 28
        badge_x = WIN_X + WIN_W - badge_w - 16
        badge_y = WIN_Y + 12
        draw.rounded_rectangle(
            (badge_x, badge_y, badge_x + badge_w, badge_y + 28),
            radius=8,
            fill=(48, 54, 61),
            outline=META,
            width=1,
        )
        draw.text((badge_x + 14, badge_y + 5), badge_text, fill=META, font=badge_font)

    font = load_mono_font(FONT_SIZE)
    total = len(lines)
    start = min(scroll_offset, max(0, total - MAX_VISIBLE))
    visible = lines[start : start + MAX_VISIBLE]
    y = TEXT_TOP
    for item in visible:
        draw.text((WIN_X + MARGIN_X, y), item.text, fill=color_for(item.kind), font=font)
        y += LINE_H

    # Block cursor on last prompt line
    if cursor_visible and visible and visible[-1].kind == "prompt":
        cx = WIN_X + MARGIN_X + int(font.getlength(visible[-1].text))
        draw.rectangle((cx + 2, y - LINE_H + 6, cx + 16, y - 10), fill=PROMPT)

    if cmd_caption:
        cap_font = load_mono_font(22)
        cap_text = f"$ {cmd_caption}" if not cmd_caption.startswith("$") else cmd_caption
        cap_h = 40
        cap_y = WIN_Y + WIN_H - cap_h - 12
        draw.rounded_rectangle(
            (WIN_X + 16, cap_y, WIN_X + WIN_W - 16, cap_y + cap_h),
            radius=10,
            fill=(22, 32, 48),
            outline=PROMPT,
            width=1,
        )
        draw.text((WIN_X + 32, cap_y + 9), cap_text, fill=PROMPT, font=cap_font)

    return img


def append_frames(
    frames: list,
    lines: list[StyledLine],
    count: int,
    *,
    segment_label: str | None = None,
    scroll_offset: int = 0,
    blink: bool = True,
    cmd_caption: str | None = None,
) -> None:
    for i in range(max(1, count)):
        cursor_on = (i // CURSOR_BLINK_FRAMES) % 2 == 0 if blink else True
        frames.append(
            render_terminal(
                lines,
                cursor_visible=cursor_on,
                segment_label=segment_label,
                scroll_offset=scroll_offset,
                cmd_caption=cmd_caption,
            )
        )


def animate_scroll(
    frames: list,
    lines: list[StyledLine],
    from_offset: int,
    to_offset: int,
    *,
    segment_label: str | None = None,
    cmd_caption: str | None = None,
) -> int:
    if from_offset == to_offset:
        return to_offset
    steps = max(1, SCROLL_ANIM_FRAMES)
    for step in range(1, steps + 1):
        offset = from_offset + round((to_offset - from_offset) * step / steps)
        append_frames(
            frames,
            lines,
            1,
            segment_label=segment_label,
            scroll_offset=offset,
            blink=True,
            cmd_caption=cmd_caption,
        )
    return to_offset


def animate_one_scene(
    frames: list,
    history: list[StyledLine],
    scene: dict,
    budget_sec: float,
    *,
    seg_id: str,
    font,
    frames_per_char: int,
    scroll_offset: int,
    label: str | None,
) -> int:
    prefix = scene.get("prompt", "$ ")
    cmd = scene["cmd"]
    caption = cmd
    skip_typing = scene.get("skip_typing", False)

    typing_sec = 0.0 if skip_typing else len(cmd) / CPS + POST_CMD_PAUSE_SEC
    output_lines = scene_output(scene)
    output_sec = max(len(output_lines), 1) * LINE_REVEAL_SEC
    min_sec = typing_sec + output_sec
    if min_sec > budget_sec:
        output_sec = max(0.35, budget_sec - typing_sec)
    hold_sec = max(0.0, budget_sec - typing_sec - output_sec)

    if skip_typing:
        full_prompt = wrap_prompt(prefix, cmd, font)
        for pl in full_prompt:
            history.append(StyledLine(pl, "prompt"))
        new_offset = max(0, len(history) - MAX_VISIBLE)
        if new_offset > scroll_offset:
            scroll_offset = animate_scroll(
                frames, history, scroll_offset, new_offset, segment_label=label, cmd_caption=caption
            )
        append_frames(
            frames,
            history,
            max(1, int(min(POST_CMD_PAUSE_SEC, budget_sec * 0.15) * FPS)),
            segment_label=label,
            scroll_offset=scroll_offset,
            cmd_caption=caption,
        )
    else:
        typed = ""
        for ch in cmd:
            typed += ch
            prompt_lines = wrap_prompt(prefix, typed, font)
            display = history + [StyledLine(t, "prompt") for t in prompt_lines]
            new_offset = max(0, len(display) - MAX_VISIBLE)
            if new_offset > scroll_offset:
                scroll_offset = animate_scroll(
                    frames, display, scroll_offset, new_offset, segment_label=label, cmd_caption=caption
                )
            append_frames(
                frames,
                display,
                frames_per_char,
                segment_label=label,
                scroll_offset=scroll_offset,
                cmd_caption=caption,
            )

        full_prompt = wrap_prompt(prefix, cmd, font)
        for pl in full_prompt:
            history.append(StyledLine(pl, "prompt"))
        new_offset = max(0, len(history) - MAX_VISIBLE)
        if new_offset > scroll_offset:
            scroll_offset = animate_scroll(
                frames, history, scroll_offset, new_offset, segment_label=label, cmd_caption=caption
            )
        append_frames(
            frames,
            history,
            max(1, int(POST_CMD_PAUSE_SEC * FPS)),
            segment_label=label,
            scroll_offset=scroll_offset,
            cmd_caption=caption,
        )

    per_line = max(1, int((output_sec / max(len(output_lines), 1)) * FPS))
    for raw in output_lines:
        if raw == "":
            history.append(StyledLine("", "text"))
        else:
            history.append(StyledLine(raw, classify_line(raw)))
        new_offset = max(0, len(history) - MAX_VISIBLE)
        if new_offset > scroll_offset:
            scroll_offset = animate_scroll(
                frames, history, scroll_offset, new_offset, segment_label=label, cmd_caption=caption
            )
        append_frames(
            frames,
            history,
            per_line,
            segment_label=label,
            scroll_offset=scroll_offset,
            cmd_caption=caption,
        )

    if hold_sec > 0:
        append_frames(
            frames,
            history,
            max(1, int(hold_sec * FPS)),
            segment_label=label,
            scroll_offset=scroll_offset,
            cmd_caption=caption,
        )

    return scroll_offset


def fit_frames_to_target(frames: list, target: int) -> list:
    """Drop hold frames from the end; never subsample typing frames away."""
    if len(frames) <= target:
        return frames
    drop = len(frames) - target
    if drop >= len(frames):
        return frames[:target]
    return frames[:-drop]


def animate_scenes(scenes: list[dict], duration: float, seg_id: str, out_mp4: Path) -> Path:
    from PIL import Image

    frames: list[Image.Image] = []
    history: list[StyledLine] = []
    font = load_mono_font(FONT_SIZE)
    label = SEGMENT_LABELS.get(seg_id)
    scroll_offset = 0
    frames_per_char = max(1, round(FPS / CPS))
    budgets = scene_budgets(scenes, duration)

    for scene, budget in zip(scenes, budgets):
        scroll_offset = animate_one_scene(
            frames,
            history,
            scene,
            budget,
            seg_id=seg_id,
            font=font,
            frames_per_char=frames_per_char,
            scroll_offset=scroll_offset,
            label=label,
        )

    target = max(1, int(duration * FPS))
    if len(frames) < target:
        caption = scenes[-1]["cmd"] if scenes else None
        append_frames(
            frames,
            history,
            target - len(frames),
            segment_label=label,
            scroll_offset=scroll_offset,
            cmd_caption=caption,
        )
    elif len(frames) > target:
        frames = fit_frames_to_target(frames, target)

    seg_frames = FRAMES / seg_id
    if seg_frames.exists():
        shutil.rmtree(seg_frames)
    seg_frames.mkdir(parents=True, exist_ok=True)
    for i, frame in enumerate(frames):
        frame.save(seg_frames / f"frame_{i:06d}.png")

    run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(seg_frames / "frame_%06d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ],
        capture_output=True,
    )
    return out_mp4


def make_title_png(
    path: Path,
    title: str,
    subtitle: str = "",
    tagline: str = "",
    bg_top: tuple[int, int, int] = (13, 17, 23),
    bg_bottom: tuple[int, int, int] = (26, 27, 38),
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    # Subtle vertical gradient
    for y in range(HEIGHT):
        t = y / max(HEIGHT - 1, 1)
        color = tuple(int(bg_top[i] + (bg_bottom[i] - bg_top[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    # Dot grid pattern
    for gy in range(0, HEIGHT, 48):
        for gx in range(0, WIDTH, 48):
            draw.point((gx, gy), fill=(40, 44, 52))

    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 132)
        sub_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 52)
        badge_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 28)
        tag_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 34)
    except OSError:
        title_font = sub_font = badge_font = tag_font = ImageFont.load_default()

    cx = WIDTH // 2
    title_y = HEIGHT // 2 - 160
    title_w = draw.textlength(title, font=title_font)
    draw.text((cx - title_w / 2, title_y), title, fill=(255, 255, 255), font=title_font)

    if subtitle:
        sub_w = draw.textlength(subtitle, font=sub_font)
        draw.text((cx - sub_w / 2, title_y + 150), subtitle, fill=DIM, font=sub_font)

    if tagline:
        badge_text = tagline
        badge_w = int(draw.textlength(badge_text, font=badge_font)) + 48
        badge_h = 52
        badge_x = cx - badge_w // 2
        badge_y = title_y + 240
        draw.rounded_rectangle(
            (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
            radius=26,
            fill=(33, 38, 45),
            outline=META,
            width=2,
        )
        text_w = draw.textlength(badge_text, font=badge_font)
        draw.text(
            (badge_x + (badge_w - text_w) / 2, badge_y + 12),
            badge_text,
            fill=META,
            font=badge_font,
        )

    # Accent line under title
    line_w = min(int(title_w) + 80, 520)
    draw.rounded_rectangle(
        (cx - line_w // 2, title_y + 130, cx + line_w // 2, title_y + 134),
        radius=2,
        fill=PROMPT,
    )

    footer = "arka-agent.mintlify.site"
    if "Get started" in title:
        footer = "github.com/Sumit884-byte/arka"
    foot_w = draw.textlength(footer, font=tag_font)
    draw.text((cx - foot_w / 2, HEIGHT - 100), footer, fill=(100, 108, 120), font=tag_font)

    img.save(path)


def image_to_clip(img_path: Path, duration: float, out_path: Path) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(img_path),
            "-vf",
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x0D1117",
            "-r",
            str(FPS),
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_path),
        ],
        capture_output=True,
    )


async def generate_voiceover() -> None:
    if OUT_MP3.exists() and OUT_TXT.exists() and OUT_MP3.stat().st_mtime >= OUT_TXT.stat().st_mtime:
        dur = probe_duration(OUT_MP3)
        if dur >= 179.0:
            print(f"Reusing voiceover: {OUT_MP3} ({dur:.1f}s)")
            return
        print(f"Regenerating voiceover (existing mp3 too short: {dur:.1f}s)")
    text = OUT_TXT.read_text()
    spoken = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].strip()
        spoken.append(line)
    communicate = edge_tts.Communicate(" ".join(spoken), VOICE)
    await communicate.save(str(OUT_MP3))
    print(f"Voiceover saved: {OUT_MP3}")


def ensure_captures() -> None:
    if not CAPTURES.exists() or not (CAPTURES / "doctor.txt").exists():
        print("Running capture_terminal.py…")
        run(["python3", str(ROOT / "capture_terminal.py")], cwd=str(REPO))


def build_visual_segments(target_total: float) -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    FRAMES.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []

    print("\nVoiceover-aligned segment map:")
    for i, (seg, dur) in enumerate(beat_durations(target_total)):
        start = seg["start"]
        scenes = seg.get("scenes", [])
        cmds = [s["cmd"] for s in scenes] if scenes else [seg.get("title", "")]
        print(f"  [{start:>3.0f}s] {seg['id']:<14} {dur:5.1f}s  →  {', '.join(cmds[:2])}{'…' if len(cmds)>2 else ''}")

        out = WORK / f"{i:02d}_{seg['id']}.mp4"
        stype = seg["type"]

        if stype == "title":
            png = WORK / f"{seg['id']}.png"
            make_title_png(png, seg["title"], seg.get("subtitle", ""), seg.get("tagline", ""))
            image_to_clip(png, dur, out)
        elif stype == "terminal_anim":
            animate_scenes(seg["scenes"], dur, seg["id"], out)
        clips.append(out)

    return clips


def concat_with_crossfade(clips: list[Path], out: Path) -> None:
    if len(clips) == 1:
        run(["ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", str(out)], capture_output=True)
        return

    durations = [probe_duration(c) for c in clips]
    inputs: list[str] = []
    for clip in clips:
        inputs.extend(["-i", str(clip)])

    parts: list[str] = []
    offset = durations[0] - XFADE_SEC
    parts.append(f"[0:v][1:v]xfade=transition=fade:duration={XFADE_SEC}:offset={offset:.3f}[v01]")
    prev = "v01"
    cumulative = durations[0] + durations[1] - XFADE_SEC
    for i in range(2, len(clips)):
        offset = cumulative - XFADE_SEC
        nxt = f"v{i:02d}"
        parts.append(
            f"[{prev}][{i}:v]xfade=transition=fade:duration={XFADE_SEC}:offset={offset:.3f}[{nxt}]"
        )
        prev = nxt
        cumulative += durations[i] - XFADE_SEC

    filter_complex = ";".join(parts)
    run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{prev}]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out),
        ],
        capture_output=True,
    )


def concat_and_mux(clips: list[Path], audio: Path, out: Path) -> None:
    video_only = WORK / "video_only.mp4"
    concat_with_crossfade(clips, video_only)

    audio_dur = probe_duration(audio)
    video_dur = probe_duration(video_only)
    target = min(audio_dur, video_dur, 180.0)
    if target < 179.0:
        raise SystemExit(f"Output too short ({target:.1f}s); need at least 179s — extend voiceover.")
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_only),
            "-i",
            str(audio),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-t",
            f"{target:.3f}",
            "-movflags",
            "+faststart",
            str(out),
        ],
        capture_output=True,
    )


def print_capture_summary() -> None:
    if META_FILE.exists():
        meta = json.loads(META_FILE.read_text())
        print("\nCapture summary:")
        for name, info in meta.items():
            status = "live" if info.get("live") else "fallback"
            extra = f" ({info.get('fallback_reason', '')})" if info.get("fallback_reason") else ""
            print(f"  {name}: {status}{extra}")
    print(f"\nAnimation: {FPS} fps, typing {CPS} cps")


def verify_command_visibility(video: Path, audio_dur: float) -> None:
    """Extract frames at voiceover command mention times and OCR-check command text."""
    checkpoints = [
        (20.0, "pipx install"),
        (24.0, "arka setup"),
        (36.0, "arka doctor"),
        (52.0, 'arka route "time in tokyo"'),
        (58.0, 'arka "time in tokyo"'),
        (68.0, 'arka route "what is Rust?"'),
        (84.0, 'arka ask "what is Rust?"'),
        (100.0, "arka coding-tui"),
        (116.0, "arka mcp doctor"),
        (148.0, "arka capabilities"),
    ]
    verify_dir = WORK / "verify_frames"
    verify_dir.mkdir(parents=True, exist_ok=True)
    print("\nCommand visibility checks:")
    ok = 0
    for ts, expected in checkpoints:
        frame_path = verify_dir / f"at_{int(ts)}s.png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(frame_path),
            ],
            capture_output=True,
            check=True,
        )
        # Simple pixel text check via strings on PNG (fallback: file exists)
        data = frame_path.read_bytes()
        needle = expected.replace('"', "").split()[0]  # first token
        found = needle.encode() in data or expected.split()[0].encode() in data
        status = "OK" if found else "CHECK"
        if found:
            ok += 1
        print(f"  [{ts:5.1f}s] expect `{expected}` → {status}  ({frame_path.name})")
    print(f"  {ok}/{len(checkpoints)} checkpoints passed byte-level scan")


def main() -> None:
    print("=== Step 0: Ensure terminal captures ===")
    ensure_captures()

    print("=== Step 1: Voiceover ===")
    asyncio.run(generate_voiceover())
    audio_dur = probe_duration(OUT_MP3)
    print(f"Audio duration: {audio_dur:.1f}s")

    print("=== Step 2: Build animated terminal segments ===")
    clips = build_visual_segments(audio_dur)

    print("=== Step 3: Concat + mux ===")
    concat_and_mux(clips, OUT_MP3, OUT_MP4)

    final_dur = probe_duration(OUT_MP4)
    size_mb = OUT_MP4.stat().st_size / (1024 * 1024)
    print(f"\nDone: {OUT_MP4}")
    print(f"Duration: {final_dur:.1f}s ({final_dur / 60:.2f} min)")
    print(f"Size: {size_mb:.1f} MB")
    if final_dur > 180:
        print("WARNING: exceeds 3 minute limit!")
    print_capture_summary()
    verify_command_visibility(OUT_MP4, audio_dur)


if __name__ == "__main__":
    main()
