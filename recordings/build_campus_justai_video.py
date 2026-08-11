#!/usr/bin/env python3
"""Build ≤60s campus demo — Arka just-ai mode (plain LLM, no routing/skills)."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from arka.media import terminal_video as tv  # noqa: E402

CAPTURES = REPO / "recordings" / "justai_captures"
OUT_MP4 = REPO / "recordings" / "reels" / "arka-campus-justai-60s.mp4"
OUT_MP3 = REPO / "recordings" / "justai-campus-voiceover.mp3"
OUT_TXT = REPO / "recordings" / "justai-campus-voiceover.txt"
WORK = REPO / "recordings" / "_justai_campus_build"
MAX_DURATION = 60.0
TARGET_DURATION = 58.0

VO_BEATS = [
    {
        "id": "title",
        "start": 0,
        "type": "title",
        "title": "Arka — AI-only mode",
        "subtitle": "Plain LLM chat · no routing · no tools",
        "tagline": "JUST_AI=1 · arka just-ai · arka --just-ai",
    },
    {
        "id": "contrast",
        "start": 5,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka route "time in tokyo"',
                "capture": "route_normal.txt",
                "max_lines": 5,
                "time_share": 0.45,
            },
            {
                "cmd": 'JUST_AI=1 arka "time in tokyo"',
                "capture": "just_ai_mode.txt",
                "max_lines": 6,
                "time_share": 0.55,
            },
        ],
    },
    {
        "id": "example_rust",
        "start": 15,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka just-ai "what is Rust?"',
                "capture": "just_ai_rust.txt",
                "max_lines": 8,
            },
        ],
    },
    {
        "id": "example_recursion",
        "start": 28,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'JUST_AI=1 arka "explain recursion in one sentence"',
                "capture": "just_ai_recursion.txt",
                "max_lines": 6,
            },
        ],
    },
    {
        "id": "example_haiku",
        "start": 38,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": 'arka --just-ai "write a haiku about coding"',
                "capture": "just_ai_haiku.txt",
                "max_lines": 6,
            },
        ],
    },
    {
        "id": "outro",
        "start": 48,
        "type": "title",
        "title": "Just ask. No routing.",
        "subtitle": 'pipx install "arka-agent[chat]"',
        "tagline": "github.com/Sumit884-byte/arka",
    },
]

SEGMENT_LABELS = {
    "contrast": "Normal vs AI-only",
    "example_rust": "Just AI",
    "example_recursion": "Just AI",
    "example_haiku": "Just AI",
}


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
    """Speed up if over 60s; trim silence tail if needed."""
    dur = tv.probe_duration(audio)
    if dur <= MAX_DURATION:
        if audio.resolve() != out.resolve():
            shutil.copy(audio, out)
        return out
    tv.fit_audio_to_limit(audio, out, limit=MAX_DURATION - 0.5)
    return out


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
        print(f"  [{start:>3.0f}s] {seg['id']:<18} {dur:5.1f}s  →  {', '.join(cmds[:2])}")

        if stype == "title":
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

    for cap in (
        "route_normal.txt",
        "just_ai_mode.txt",
        "just_ai_rust.txt",
        "just_ai_recursion.txt",
        "just_ai_haiku.txt",
    ):
        if not (CAPTURES / cap).is_file():
            raise SystemExit(f"Missing capture {CAPTURES / cap}")

    vo_beats = list(VO_BEATS)
    _patch_tv(vo_beats)
    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)

    print("=== Step 1: Voiceover ===")
    OUT_MP3.unlink(missing_ok=True)
    asyncio.run(tv.generate_voiceover())
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
