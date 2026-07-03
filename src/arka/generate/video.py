#!/usr/bin/env python3
"""Generate real AI video via Pollinations or Gemini Veo."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_GEMINI_MODEL = "veo-2.0-generate-001"
DEFAULT_POLLINATIONS_MODEL = "wan-fast"
ALLOWED_ASPECTS = {"16:9", "9:16", "1:1"}


def _api_key() -> str:
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _pollinations_key() -> str:
    for name in ("POLLINATIONS_API_KEY", "POLLINATIONS_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _backend() -> str:
    return os.environ.get("ARKA_VIDEO_BACKEND", "auto").strip().lower() or "auto"


def _default_output(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "video"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path.home() / "Videos" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.mp4"


def _setup_hint() -> str:
    return (
        "Real AI video needs a video API — still photos stitched together are not supported.\n\n"
        "Option 1 — Pollinations (free signup, recommended):\n"
        "  1. Get a key: https://enter.pollinations.ai/\n"
        "  2. Add to ~/.config/fish/.env:\n"
        "       POLLINATIONS_API_KEY=pk_...\n"
        "  3. Run: arka generate video of a queen walking\n\n"
        "Option 2 — Gemini Veo (needs GCP billing):\n"
        "  • Enable billing: https://aistudio.google.com/\n"
        "  • Uses your existing GEMINI_API_KEY\n\n"
        "For still images only, use: arka generate image of ..."
    )


def _friendly_error(provider: str, exc: Exception) -> str:
    text = str(exc)
    if provider == "gemini":
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            return "Gemini video quota exceeded."
        if "billing" in text.lower() or "FAILED_PRECONDITION" in text:
            return "Gemini Veo needs GCP billing enabled."
    if provider == "pollinations":
        if "401" in text or "403" in text:
            return "Pollinations rejected the API key — check POLLINATIONS_API_KEY in .env"
    return f"{provider}: {text[:240]}"


def _download_url(url: str, headers: dict[str, str] | None = None, timeout: int = 600) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "arka-generate-video/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError("Empty response from video provider")
    if data[:1] == b"{":
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
            msg = payload.get("error") or payload.get("message") or payload
            raise RuntimeError(str(msg))
        except json.JSONDecodeError:
            pass
    return data


def generate_gemini(prompt: str, output: Path, aspect: str, model: str, duration: int) -> Path:
    from google import genai
    from google.genai import types

    key = _api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=key)
    cfg = types.GenerateVideosConfig(
        aspect_ratio=aspect,
        number_of_videos=1,
        duration_seconds=min(max(duration, 4), 8),
    )
    print(f"  Gemini Veo ({model}) — generating real video, may take 1–3 minutes …", file=sys.stderr)
    operation = client.models.generate_videos(
        model=model,
        source=types.GenerateVideosSource(prompt=prompt),
        config=cfg,
    )
    while not getattr(operation, "done", False):
        time.sleep(10)
        operation = client.operations.get(operation)
        print("  … still generating", file=sys.stderr)

    if getattr(operation, "error", None):
        raise RuntimeError(str(operation.error))

    result = getattr(operation, "result", None)
    videos = getattr(result, "generated_videos", None) if result else None
    if not videos:
        raise RuntimeError("Gemini returned no video")

    video = videos[0].video
    if video is None:
        raise RuntimeError("Gemini returned empty video")

    client.files.download(file=video)
    if not video.video_bytes:
        raise RuntimeError("Gemini video download failed")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(video.video_bytes)
    return output


def generate_pollinations(
    prompt: str, output: Path, aspect: str, model: str, duration: int, audio: bool
) -> Path:
    key = _pollinations_key()
    if not key:
        raise RuntimeError("POLLINATIONS_API_KEY not set")

    encoded = urllib.parse.quote(prompt)
    params = urllib.parse.urlencode(
        {
            "model": model,
            "duration": duration,
            "aspectRatio": aspect,
            "audio": "true" if audio else "false",
        }
    )
    url = f"https://gen.pollinations.ai/video/{encoded}?{params}"
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "arka-generate-video/1.0"}
    print(f"  Pollinations ({model}, {duration}s) — generating real video, may take a few minutes …", file=sys.stderr)
    data = _download_url(url, headers=headers, timeout=600)

    out = output if output.suffix.lower() == ".mp4" else output.with_suffix(".mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def generate(
    prompt: str,
    output: Path,
    aspect: str,
    model: str,
    duration: int,
    audio: bool,
) -> tuple[Path, str]:
    backend = _backend()
    errors: list[str] = []

    def _try(name: str, fn) -> tuple[Path, str] | None:
        try:
            return fn(), name
        except SystemExit:
            raise
        except Exception as exc:
            errors.append(_friendly_error(name, exc))
            return None

    if backend == "gemini":
        if not _api_key():
            raise SystemExit(_setup_hint())
        result = _try("gemini", lambda: generate_gemini(prompt, output, aspect, model, duration))
        if result:
            return result
        raise SystemExit("\n".join(errors) or "Gemini video generation failed")

    if backend == "pollinations":
        if not _pollinations_key():
            raise SystemExit(_setup_hint())
        poll_model = os.environ.get("ARKA_VIDEO_POLLINATIONS_MODEL", DEFAULT_POLLINATIONS_MODEL)
        result = _try("pollinations", lambda: generate_pollinations(prompt, output, aspect, poll_model, duration, audio))
        if result:
            return result
        raise SystemExit("\n".join(errors) or "Pollinations video generation failed")

    # auto: Pollinations first (works with free key), then Gemini Veo
    if not _pollinations_key() and not _api_key():
        raise SystemExit(_setup_hint())

    if _pollinations_key():
        poll_model = os.environ.get("ARKA_VIDEO_POLLINATIONS_MODEL", DEFAULT_POLLINATIONS_MODEL)
        result = _try("pollinations", lambda: generate_pollinations(prompt, output, aspect, poll_model, duration, audio))
        if result:
            return result

    if _api_key():
        result = _try("gemini", lambda: generate_gemini(prompt, output, aspect, model, duration))
        if result:
            return result

    detail = "\n".join(f"  • {e}" for e in errors if e)
    raise SystemExit(f"All video backends failed.\n{detail}\n\n{_setup_hint()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate real AI video (Pollinations or Gemini Veo)")
    parser.add_argument("prompt", help="Video description")
    parser.add_argument("-o", "--output", help="Output .mp4 path")
    parser.add_argument("-a", "--aspect", default=os.environ.get("ARKA_VIDEO_ASPECT", "16:9"))
    parser.add_argument("-d", "--duration", type=int, default=int(os.environ.get("ARKA_VIDEO_DURATION", "5")))
    parser.add_argument("-m", "--model", default=os.environ.get("ARKA_VIDEO_MODEL", DEFAULT_GEMINI_MODEL))
    parser.add_argument("--no-audio", action="store_true", help="Disable Pollinations audio track")
    args = parser.parse_args()

    aspect = args.aspect
    if aspect not in ALLOWED_ASPECTS:
        print(f"Invalid aspect '{aspect}'. Choose: {', '.join(sorted(ALLOWED_ASPECTS))}", file=sys.stderr)
        return 1

    duration = min(max(args.duration, 2), 15)
    audio = not args.no_audio and os.environ.get("ARKA_VIDEO_AUDIO", "1") not in ("0", "false")

    print(f"Generating video ({aspect}, {duration}s) …")
    try:
        backend = _backend()
        if backend == "auto" and not _pollinations_key() and not _api_key():
            raise SystemExit(_setup_hint())
        if backend == "pollinations" and not _pollinations_key():
            raise SystemExit(_setup_hint())
        if backend == "gemini" and not _api_key():
            raise SystemExit(_setup_hint())

        out = Path(args.output) if args.output else _default_output(args.prompt)
        saved, provider = generate(args.prompt, out, aspect, args.model, duration, audio)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Saved ({provider}): {saved}")
    if os.environ.get("ARKA_OPEN_VIDEO", "1") not in ("0", "false"):
        try:
            subprocess.Popen(["xdg-open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
