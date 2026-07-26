#!/usr/bin/env python3
"""Build SigNoz hackathon demo MP4 — terminal captures + SigNoz UI screenshots + voiceover."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from arka.media import terminal_video as tv  # noqa: E402

SHOTS = REPO / "recordings" / "signoz-screenshots"
CAPTURES = REPO / "recordings" / "signoz_captures"
CAPTURE_SCRIPT = SHOTS / "capture_signoz_ui.py"
OUT_MP4 = REPO / "recordings" / "arka-signoz-hackathon-demo.mp4"
OUT_MP3 = REPO / "recordings" / "signoz-hackathon-voiceover.mp3"
OUT_TXT = REPO / "recordings" / "signoz-hackathon-voiceover.txt"
WORK = REPO / "recordings" / "_signoz_demo_build"

# Track 01 = traces + logs + services metrics (no dashboards, no synthetic charts).
BLOCKED_SHOTS = frozenset(
    {
        "traces-arka-service.png",  # 404 page
        "api-telemetry-summary.png",  # generated chart, not SigNoz UI
        "dashboard-observability.png",
        "dashboard-observability-long.png",
        "home-dashboard.png",
        "debug-after-login.png",
        "debug-dashboard-list.png",
        "debug-import-dashboard.png",
        "debug-import-step2.png",
        "debug-import-upload.png",
        "debug-new-dashboard.png",
    }
)

# Pick newest verified PNG per slot (mtime). Patterns tried in order.
SCREENSHOT_SLOTS = [
    {
        "id": "traces",
        "start": 66,
        "patterns": ("traces-explorer*.png", "traces-*.png"),
        "caption": "Traces — arka.llm.attempt · arka.route · arka.demo",
    },
    {
        "id": "services",
        "start": 78,
        "patterns": ("services*.png",),
        "caption": "Services — P99 latency · error rate · ops/sec",
    },
    {
        "id": "logs",
        "start": 90,
        "patterns": ("logs-explorer*.png", "logs*.png"),
        "caption": "Logs — LLM failover & agent events",
    },
]

TITLE_BEATS = [
    {
        "id": "title",
        "start": 0,
        "type": "title",
        "title": "Arka × SigNoz",
        "subtitle": "AI Agent Observability",
        "tagline": "Agents of SigNoz Hackathon · Track 01",
    },
    {
        "id": "problem",
        "start": 10,
        "type": "title",
        "title": "The problem",
        "subtitle": "AI agents are a black box",
        "tagline": "LLM calls · tools · vector DBs · failover",
    },
    {
        "id": "setup",
        "start": 22,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka signoz setup -y",
                "capture": "signoz_setup_help.txt",
                "max_lines": 11,
            },
        ],
    },
    {
        "id": "status",
        "start": 38,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka signoz status",
                "capture": "signoz_status.txt",
                "max_lines": 14,
                "skip_typing": True,
            },
        ],
    },
    {
        "id": "demo",
        "start": 52,
        "type": "terminal_anim",
        "scenes": [
            {
                "cmd": "arka signoz demo-scenarios --synthetic",
                "capture": "signoz_demo_scenarios.txt",
                "max_lines": 10,
            },
        ],
    },
    {
        "id": "outro",
        "start": 102,
        "type": "title",
        "title": "Reproducible locally",
        "subtitle": "foundryctl cast · casting.yaml in repo",
        "tagline": "github.com/Sumit884-byte/arka",
    },
]

SEGMENT_LABELS = {
    "setup": "Deploy",
    "status": "Status",
    "demo": "Demo scenarios",
}


def verify_screenshot(path: Path) -> tuple[bool, str]:
    """Reject blank, broken, or dashboard screenshots before they reach the video."""
    import statistics

    from PIL import Image

    if not path.is_file():
        return False, "file missing"
    if path.name in BLOCKED_SHOTS:
        return False, f"blocked for Track 01 ({path.name})"
    if "dashboard" in path.name.lower():
        return False, "Track 01 demo excludes dashboards"

    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w < 800 or h < 400:
        return False, f"too small ({w}x{h})"

    sample = img.resize((min(w, 400), min(h, 300))).getdata()
    brightness = [sum(px) / 3 for px in sample]
    if statistics.pstdev(brightness) < 8:
        return False, "image appears blank or uniform"

    top = img.crop((0, 0, w, h // 6))
    top_px = list(top.getdata())[::20]
    top_brightness = [sum(px) / 3 for px in top_px]
    if statistics.mean(top_brightness) < 25:
        body = img.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
        body_px = list(body.getdata())[::30]
        purpleish = sum(1 for r, g, b in body_px if r > 80 and b > 100 and g < 80)
        if purpleish > len(body_px) * 0.05:
            return False, "looks like SigNoz 404 page — recapture"

    kb = path.stat().st_size // 1024
    return True, f"ok ({w}x{h}, {kb}KB)"


def _signoz_ui_url() -> str:
    import os

    return os.environ.get("SIGNOZ_UI_URL", "http://localhost:8080").rstrip("/")


def _signoz_reachable() -> bool:
    url = f"{_signoz_ui_url()}/login"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def try_refresh_screenshots() -> None:
    """Capture fresh SigNoz UI PNGs when the local instance is up."""
    if not CAPTURE_SCRIPT.is_file():
        return
    if not _signoz_reachable():
        print(f"SigNoz not reachable at {_signoz_ui_url()} — using latest PNGs on disk")
        return
    print(f"SigNoz reachable — refreshing screenshots via {CAPTURE_SCRIPT.name}")
    proc = subprocess.run(
        [sys.executable, str(CAPTURE_SCRIPT), "--no-dashboard"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            # Prefer explicit capture password when .env password is too weak for SigNoz policy
            **(
                {"SIGNOZ_CAPTURE_PASSWORD": os.environ["SIGNOZ_CAPTURE_PASSWORD"]}
                if os.environ.get("SIGNOZ_CAPTURE_PASSWORD")
                else {}
            ),
        },
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        print("Screenshot capture failed (using existing PNGs):")
        for line in tail:
            print(f"  {line}")
        return
    for line in (proc.stdout or "").splitlines():
        if line.endswith(".png"):
            print(f"  captured {line}")


def _candidates(patterns: tuple[str, ...]) -> list[Path]:
    if not SHOTS.is_dir():
        return []
    names = {p.name for p in SHOTS.glob("*.png")}
    out: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        for name in sorted(names):
            if name in seen or not fnmatch.fnmatch(name, pattern):
                continue
            seen.add(name)
            out.append(SHOTS / name)
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_latest_screenshots() -> list[dict]:
    """Select newest verified SigNoz UI screenshot for each demo slot."""
    resolved: list[dict] = []
    print("\n=== Resolving latest SigNoz screenshots ===")
    for slot in SCREENSHOT_SLOTS:
        chosen: Path | None = None
        reason = ""
        for path in _candidates(slot["patterns"]):
            ok, msg = verify_screenshot(path)
            if ok:
                chosen = path
                reason = msg
                break
        if not chosen:
            tried = ", ".join(slot["patterns"])
            raise SystemExit(
                f"No verified screenshot for slot '{slot['id']}' "
                f"(patterns: {tried}). Run capture_signoz_ui.py with SigNoz up."
            )
        mtime = chosen.stat().st_mtime
        print(f"  {slot['id']:<10} ← {chosen.name}  ({reason})")
        resolved.append(
            {
                "id": slot["id"],
                "start": slot["start"],
                "type": "screenshot",
                "image": chosen,
                "caption": slot["caption"],
                "_mtime": mtime,
            }
        )
    return resolved


def build_vo_beats() -> list[dict]:
    beats = list(TITLE_BEATS[:5])  # title → demo (terminal segments)
    beats.extend(resolve_latest_screenshots())
    beats.append(TITLE_BEATS[5])  # outro
    return beats


def frame_screenshot(image: Path, out_png: Path, *, caption: str = "") -> None:
    from PIL import Image, ImageDraw

    img = Image.open(image).convert("RGB")
    iw, ih = img.size
    scale = min((tv.WIDTH - 120) / iw, (tv.HEIGHT - 200) / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (tv.WIDTH, tv.HEIGHT), tv.BG)
    draw = ImageDraw.Draw(canvas)
    x = (tv.WIDTH - nw) // 2
    y = 72 + (tv.HEIGHT - 200 - nh) // 2
    canvas.paste(img, (x, y))

    font = tv.load_mono_font(28)
    cap_font = tv.load_mono_font(24)
    draw.rounded_rectangle((40, 24, tv.WIDTH - 40, 64), radius=8, fill=tv.CHROME_BAR)
    title = "SigNoz UI"
    tw = draw.textlength(title, font=cap_font)
    draw.text(((tv.WIDTH - tw) / 2, 32), title, fill=tv.CHROME_TITLE, font=cap_font)

    if caption:
        draw.rounded_rectangle((40, tv.HEIGHT - 72, tv.WIDTH - 40, tv.HEIGHT - 24), radius=8, fill=tv.CHROME)
        cw = draw.textlength(caption, font=font)
        draw.text(((tv.WIDTH - cw) / 2, tv.HEIGHT - 62), caption, fill=tv.TEXT, font=font)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png)


def verify_all_screenshots(vo_beats: list[dict]) -> None:
    print("=== Screenshot verification (Track 01 — traces/logs only) ===")
    verify_dir = WORK / "verify_previews"
    verify_dir.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []

    for seg in vo_beats:
        if seg.get("type") != "screenshot":
            continue
        path = Path(seg["image"])
        ok, msg = verify_screenshot(path)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {path.name}: {msg}")
        if not ok:
            failed.append(f"{path.name}: {msg}")
            continue
        preview = verify_dir / f"preview_{seg['id']}.png"
        frame_screenshot(path, preview, caption=seg.get("caption", ""))
        print(f"         preview → {preview.relative_to(REPO)}")

    if failed:
        raise SystemExit("Screenshot verification failed:\n  " + "\n  ".join(failed))


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


def screenshot_to_clip(image: Path, duration: float, out_path: Path, *, caption: str = "") -> None:
    if not image.is_file():
        raise SystemExit(f"Missing screenshot: {image}")

    framed = WORK / f"frame_{out_path.stem}.png"
    frame_screenshot(image, framed, caption=caption)
    tv.image_to_clip(framed, duration, out_path)


def build_visual_segments(target_total: float, vo_beats: list[dict]) -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    tv.FRAMES.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []

    print("\nVoiceover-aligned segment map:")
    for i, (seg, dur) in enumerate(tv.beat_durations(target_total)):
        start = seg["start"]
        stype = seg["type"]
        out = WORK / f"{i:02d}_{seg['id']}.mp4"
        label = seg.get("caption") or seg.get("title") or seg["id"]
        shot = f" [{Path(seg['image']).name}]" if stype == "screenshot" else ""
        print(f"  [{start:>3.0f}s] {seg['id']:<16} {dur:5.1f}s  →  {label}{shot}")

        if stype == "title":
            png = WORK / f"{seg['id']}.png"
            tv.make_title_png(png, seg["title"], seg.get("subtitle", ""), seg.get("tagline", ""))
            tv.image_to_clip(png, dur, out)
        elif stype == "terminal_anim":
            tv.animate_scenes(seg["scenes"], dur, seg["id"], out)
        elif stype == "screenshot":
            screenshot_to_clip(seg["image"], dur, out, caption=seg.get("caption", ""))
        else:
            raise SystemExit(f"Unknown segment type: {stype}")
        clips.append(out)

    return clips


def run_build(*, skip_verify: bool = True) -> Path:
    tv.MIN_DURATION = 60.0

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg/ffprobe required")

    for cap in ("signoz_status.txt", "signoz_demo_scenarios.txt", "signoz_setup_help.txt"):
        if not (CAPTURES / cap).is_file():
            raise SystemExit(f"Missing capture {CAPTURES / cap} — run capture first")

    try_refresh_screenshots()
    vo_beats = build_vo_beats()
    _patch_tv(vo_beats)
    verify_all_screenshots(vo_beats)

    print("=== Step 1: Voiceover ===")
    OUT_MP3.unlink(missing_ok=True)
    asyncio.run(tv.generate_voiceover())
    raw_dur = tv.probe_duration(OUT_MP3)
    print(f"Audio duration: {raw_dur:.1f}s")
    fitted = tv.fit_audio_to_limit(OUT_MP3, WORK / "voiceover_fitted.mp3")
    audio_dur = tv.probe_duration(fitted)

    print("=== Step 2: Build segments ===")
    clips = build_visual_segments(audio_dur, vo_beats)

    print("=== Step 3: Concat + mux ===")
    tv.concat_and_mux(clips, fitted, OUT_MP4)

    final_dur = tv.probe_duration(OUT_MP4)
    size_mb = OUT_MP4.stat().st_size / (1024 * 1024)
    print(f"\nDone: {OUT_MP4}")
    print(f"Duration: {final_dur:.1f}s ({final_dur / 60:.2f} min)")
    print(f"Size: {size_mb:.1f} MB")
    if final_dur > 180:
        print("WARNING: exceeds 3 minute Devpost limit")
    return OUT_MP4


def main() -> None:
    run_build()


if __name__ == "__main__":
    main()
