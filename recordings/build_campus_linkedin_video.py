#!/usr/bin/env python3
"""Build ≤60s campus demo — personal intro + LinkedIn profile + Arka terminal demo."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from arka.media import terminal_video as tv  # noqa: E402

LINKEDIN_SHOT = Path(
    "/Users/sumitmishra/.cursor/projects/Users-sumitmishra-dev-arka/assets/"
    "image-16a8830d-3e13-4476-a812-5f92bc4c37ca.png"
)
CAPTURES = REPO / "recordings" / "terminal_captures"
OUT_MP4 = REPO / "recordings" / "reels" / "arka-campus-intro-linkedin-60s.mp4"
OUT_MP3 = REPO / "recordings" / "campus-linkedin-voiceover.mp3"
OUT_TXT = REPO / "recordings" / "campus-linkedin-voiceover.txt"
OUT_DESC = REPO / "recordings" / "reels" / "arka-campus-intro-linkedin-description.txt"
WORK = REPO / "recordings" / "_campus_linkedin_build"
MAX_DURATION = 60.0

VO_BEATS = [
    {
        "id": "linkedin",
        "start": 0,
        "type": "linkedin_card",
    },
    {
        "id": "intro",
        "start": 11,
        "type": "campus_intro_title",
        "title": "Something I helped make happen on campus",
        "subtitle": "Arka — open-source AI agent in your terminal",
        "tagline": "IIT Madras · by Sumit Mishra",
    },
    {
        "id": "routing",
        "start": 19,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka route "time in tokyo"',
                "capture": "route_tokyo_route.txt",
                "time_share": 0.5,
            },
            {
                "cmd": 'arka "time in tokyo"',
                "capture": "route_tokyo.txt",
                "max_lines": 6,
                "time_share": 0.5,
            },
        ],
    },
    {
        "id": "ask",
        "start": 26,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka ask "what is Rust?"',
                "capture": "ask_rust.txt",
                "fallback": "ask_rust_fallback.txt",
                "max_lines": 8,
            },
        ],
    },
    {
        "id": "mcp",
        "start": 32,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka mcp doctor",
                "capture": "mcp_doctor.txt",
                "max_lines": 12,
            },
        ],
    },
    {
        "id": "outro",
        "start": 46,
        "type": "title",
        "title": "Connect & explore",
        "subtitle": "Open source · growing on campus",
        "tagline": "linkedin.com/in/sumit0rn · github.com/Sumit884-byte/arka",
    },
]

SEGMENT_LABELS = {
    "routing": "Routing",
    "ask": "Ask",
    "mcp": "MCP",
}

DESCRIPTION = """\
What's something you helped make happen on campus?

Something I helped make happen on campus at IIT Madras is Arka — an open-source AI agent I built from scratch.

I noticed students and developers around me were copying prompts into chat apps instead of having tools that work locally in the terminal. So I built Arka to route plain English to 70+ skills, run offline when possible, and connect to IDEs via MCP.

This 60-second video shows a quick look at what it does: natural-language routing, arka ask, and MCP integration — all from one CLI, local-first by design.

Repo: github.com/Sumit884-byte/arka
LinkedIn: linkedin.com/in/sumit0rn
"""

AUDIO_LEAD_IN_SEC = 0.45
INTRO_TEXT_MAX_WIDTH = 1680


def _load_fonts() -> tuple:
    from PIL import ImageFont

    try:
        head_bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 44)
        head_wrap = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 38)
        sub_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 30)
        badge_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 24)
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 78)
        title_sub_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 52)
        title_tag_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 28)
    except OSError:
        head_bold = head_wrap = sub_font = badge_font = title_font = title_sub_font = title_tag_font = (
            ImageFont.load_default()
        )
    return head_bold, head_wrap, sub_font, badge_font, title_font, title_sub_font, title_tag_font


def _wrap_text(draw, text: str, font, max_width: float) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped_centered(
    draw,
    text: str,
    *,
    font,
    y: int,
    fill: tuple[int, int, int],
    max_width: float,
    line_gap: int = 10,
) -> int:
    lines = _wrap_text(draw, text, font, max_width)
    if not lines:
        return y
    bbox = draw.textbbox((0, 0), "Ay", font=font)
    line_h = bbox[3] - bbox[1]
    for line in lines:
        line_w = draw.textlength(line, font=font)
        draw.text(((tv.WIDTH - line_w) / 2, y), line, fill=fill, font=font)
        y += line_h + line_gap
    return y


def make_campus_intro_title_png(
    path: Path,
    title: str,
    subtitle: str = "",
    tagline: str = "",
) -> None:
    """Title card with wrapped headline so long intro text stays inside frame."""
    from PIL import Image, ImageDraw

    _, _, _, _, title_font, sub_font, badge_font = _load_fonts()
    img = Image.new("RGB", (tv.WIDTH, tv.HEIGHT))
    draw = ImageDraw.Draw(img)

    bg_top = (13, 17, 23)
    bg_bottom = (26, 27, 38)
    for y in range(tv.HEIGHT):
        t = y / max(tv.HEIGHT - 1, 1)
        color = tuple(int(bg_top[i] + (bg_bottom[i] - bg_top[i]) * t) for i in range(3))
        draw.line([(0, y), (tv.WIDTH, y)], fill=color)

    for gy in range(0, tv.HEIGHT, 48):
        for gx in range(0, tv.WIDTH, 48):
            draw.point((gx, gy), fill=(40, 44, 52))

    lines = _wrap_text(draw, title, title_font, INTRO_TEXT_MAX_WIDTH)
    bbox = draw.textbbox((0, 0), "Ay", font=title_font)
    line_h = bbox[3] - bbox[1]
    block_h = len(lines) * line_h + max(len(lines) - 1, 0) * 12
    title_y = tv.HEIGHT // 2 - 170 - block_h // 2
    after_title = _draw_wrapped_centered(
        draw,
        title,
        font=title_font,
        y=title_y,
        fill=(255, 255, 255),
        max_width=INTRO_TEXT_MAX_WIDTH,
    )

    accent_y = after_title + 8
    accent_w = min(520, INTRO_TEXT_MAX_WIDTH)
    draw.rounded_rectangle(
        (tv.WIDTH // 2 - accent_w // 2, accent_y, tv.WIDTH // 2 + accent_w // 2, accent_y + 4),
        radius=2,
        fill=tv.PROMPT,
    )

    if subtitle:
        sub_w = draw.textlength(subtitle, font=sub_font)
        draw.text((tv.WIDTH // 2 - sub_w / 2, accent_y + 36), subtitle, fill=tv.DIM, font=sub_font)

    if tagline:
        badge_w = int(draw.textlength(tagline, font=badge_font)) + 48
        badge_h = 52
        badge_x = tv.WIDTH // 2 - badge_w // 2
        badge_y = accent_y + 120
        draw.rounded_rectangle(
            (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
            radius=26,
            fill=(33, 38, 45),
            outline=tv.META,
            width=2,
        )
        text_w = draw.textlength(tagline, font=badge_font)
        draw.text(
            (badge_x + (badge_w - text_w) / 2, badge_y + 12),
            tagline,
            fill=tv.META,
            font=badge_font,
        )

    foot = "arka-agent.mintlify.site"
    foot_w = draw.textlength(foot, font=sub_font)
    draw.text((tv.WIDTH // 2 - foot_w / 2, tv.HEIGHT - 100), foot, fill=(100, 108, 120), font=sub_font)
    img.save(path)


def make_linkedin_intro_png(path: Path, screenshot: Path) -> None:
    """Composite LinkedIn screenshot into a styled 1920x1080 intro frame."""
    from PIL import Image, ImageDraw

    head_bold, head_wrap, sub_font, badge_font, *_ = _load_fonts()
    img = Image.new("RGB", (tv.WIDTH, tv.HEIGHT))
    draw = ImageDraw.Draw(img)

    bg_top = (13, 17, 23)
    bg_bottom = (22, 27, 38)
    for y in range(tv.HEIGHT):
        t = y / max(tv.HEIGHT - 1, 1)
        color = tuple(int(bg_top[i] + (bg_bottom[i] - bg_top[i]) * t) for i in range(3))
        draw.line([(0, y), (tv.WIDTH, y)], fill=color)

    header = "Something I helped make happen on campus"
    header_lines = _wrap_text(draw, header, head_wrap, INTRO_TEXT_MAX_WIDTH)
    header_font = head_wrap if len(header_lines) > 1 else head_bold
    if len(header_lines) == 1:
        header_lines = _wrap_text(draw, header, header_font, INTRO_TEXT_MAX_WIDTH)
    bbox = draw.textbbox((0, 0), "Ay", font=header_font)
    line_h = bbox[3] - bbox[1]
    header_y = 28
    for line in header_lines:
        line_w = draw.textlength(line, font=header_font)
        draw.text(((tv.WIDTH - line_w) / 2, header_y), line, fill=(255, 255, 255), font=header_font)
        header_y += line_h + 8

    sub = "Sumit Mishra  ·  IIT Madras  ·  Built Arka"
    sub_w = draw.textlength(sub, font=sub_font)
    draw.text(((tv.WIDTH - sub_w) / 2, header_y + 6), sub, fill=tv.DIM, font=sub_font)

    shot = Image.open(screenshot).convert("RGB")
    max_w, max_h = 1680, 760
    ratio = min(max_w / shot.width, max_h / shot.height)
    new_size = (max(1, int(shot.width * ratio)), max(1, int(shot.height * ratio)))
    shot = shot.resize(new_size, Image.Resampling.LANCZOS)

    x = (tv.WIDTH - new_size[0]) // 2
    y = header_y + 44
    frame_pad = 6
    draw.rounded_rectangle(
        (
            x - frame_pad,
            y - frame_pad,
            x + new_size[0] + frame_pad,
            y + new_size[1] + frame_pad,
        ),
        radius=16,
        outline=tv.META,
        width=3,
    )
    img.paste(shot, (x, y))

    badge = "linkedin.com/in/sumit0rn"
    badge_w = int(draw.textlength(badge, font=badge_font)) + 40
    badge_h = 44
    badge_x = tv.WIDTH // 2 - badge_w // 2
    badge_y = y + new_size[1] + 28
    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=22,
        fill=(33, 38, 45),
        outline=tv.META,
        width=2,
    )
    text_w = draw.textlength(badge, font=badge_font)
    draw.text(
        (badge_x + (badge_w - text_w) / 2, badge_y + 10),
        badge,
        fill=tv.META,
        font=badge_font,
    )

    img.save(path)


def _patch_tv(vo_beats: list[dict]) -> None:
    tv.REPO = REPO
    tv.CAPTURES = CAPTURES
    tv.META_FILE = CAPTURES / "capture_meta.json"
    tv.WORK = WORK
    tv.FRAMES = WORK / "terminal_frames"
    tv.OUT_MP4 = OUT_MP4
    tv.OUT_MP3 = OUT_MP3
    tv.OUT_TXT = OUT_TXT
    tv.VO_BEATS = vo_beats
    tv.SEGMENT_LABELS = {**tv.SEGMENT_LABELS, **SEGMENT_LABELS}
    tv.MAX_DURATION = MAX_DURATION
    tv.MIN_DURATION = 45.0


def fit_voiceover(audio: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    padded = WORK / "voiceover_padded.mp3"
    pad_audio_lead_in(audio, padded, lead_in=AUDIO_LEAD_IN_SEC)
    dur = tv.probe_duration(padded)
    limit = MAX_DURATION - AUDIO_LEAD_IN_SEC - 0.2
    if dur <= limit:
        if padded.resolve() != out.resolve():
            shutil.copy(padded, out)
        return out
    tv.fit_audio_to_limit(padded, out, limit=limit)
    return out


def pad_audio_lead_in(audio: Path, out: Path, *, lead_in: float) -> Path:
    """Prepend silence so the opening line isn't clipped at t=0."""
    out.parent.mkdir(parents=True, exist_ok=True)
    delay_ms = max(1, int(lead_in * 1000))
    tv.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(audio),
            "-af",
            f"adelay={delay_ms}|{delay_ms}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(out),
        ],
        capture_output=True,
    )
    return out


async def generate_voiceover_fresh() -> None:
    import edge_tts

    OUT_MP3.unlink(missing_ok=True)
    text = OUT_TXT.read_text()
    spoken = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].strip()
        spoken.append(line)
    communicate = edge_tts.Communicate(" ".join(spoken), tv.VOICE)
    await communicate.save(str(OUT_MP3))
    print(f"Voiceover saved: {OUT_MP3}")


def build_visual_segments(target_total: float, vo_beats: list[dict]) -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    tv.FRAMES.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []

    print("\nVoiceover-aligned segment map:")
    for i, (seg, dur) in enumerate(tv.beat_durations(target_total)):
        start = seg["start"]
        stype = seg["type"]
        out = WORK / f"{i:02d}_{seg['id']}.mp4"
        scenes = seg.get("scenes", [])
        cmds = [s["cmd"] for s in scenes] if scenes else [seg.get("title", "")]
        print(f"  [{start:>3.0f}s] {seg['id']:<14} {dur:5.1f}s  →  {', '.join(cmds[:2])}")

        if stype == "linkedin_card":
            png = WORK / "linkedin_intro.png"
            make_linkedin_intro_png(png, LINKEDIN_SHOT)
            tv.image_to_clip(png, dur, out)
        elif stype == "campus_intro_title":
            png = WORK / f"{seg['id']}.png"
            make_campus_intro_title_png(
                png,
                seg["title"],
                seg.get("subtitle", ""),
                seg.get("tagline", ""),
            )
            tv.image_to_clip(png, dur, out)
        elif stype == "title":
            png = WORK / f"{seg['id']}.png"
            tv.make_title_png(png, seg["title"], seg.get("subtitle", ""), seg.get("tagline", ""))
            tv.image_to_clip(png, dur, out)
        elif stype == "terminal_anim":
            tv.animate_scenes(seg["scenes"], dur, seg["id"], out)
        else:
            raise SystemExit(f"Unknown segment type: {stype}")
        clips.append(out)

    return clips


def run_build() -> Path:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg/ffprobe required")
    if not LINKEDIN_SHOT.is_file():
        raise SystemExit(f"LinkedIn screenshot missing: {LINKEDIN_SHOT}")
    if not OUT_TXT.is_file():
        raise SystemExit(f"Voiceover script missing: {OUT_TXT}")

    vo_beats = list(VO_BEATS)
    _patch_tv(vo_beats)
    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)
    OUT_DESC.write_text(DESCRIPTION, encoding="utf-8")

    print("=== Step 1: Voiceover ===")
    asyncio.run(generate_voiceover_fresh())
    raw_dur = tv.probe_duration(OUT_MP3)
    print(f"Audio duration: {raw_dur:.1f}s")
    fitted = fit_voiceover(OUT_MP3, WORK / "voiceover_fitted.mp3")
    audio_dur = tv.probe_duration(fitted)
    if audio_dur > MAX_DURATION + 0.1:
        raise SystemExit(f"Voiceover {audio_dur:.1f}s exceeds {MAX_DURATION:.0f}s limit")

    print("=== Step 2: Build segments ===")
    clips = build_visual_segments(audio_dur, vo_beats)

    print("=== Step 3: Concat + mux ===")
    tv.concat_and_mux(clips, fitted, OUT_MP4)

    final_dur = tv.probe_duration(OUT_MP4)
    size_mb = OUT_MP4.stat().st_size / (1024 * 1024)
    print(f"\nDone: {OUT_MP4}")
    print(f"Duration: {final_dur:.1f}s")
    print(f"Size: {size_mb:.1f} MB")
    if final_dur > MAX_DURATION:
        raise SystemExit(f"Output {final_dur:.1f}s exceeds {MAX_DURATION:.0f}s campus limit")
    return OUT_MP4


def main() -> None:
    run_build()


if __name__ == "__main__":
    main()
