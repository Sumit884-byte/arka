#!/usr/bin/env python3
"""Speak text via Sarvam Bulbul v3 (Indian English / Indic)."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.sarvam.ai/text-to-speech"
DEFAULT_CHUNK = 2000  # Sarvam REST limit is 2500 chars per request


def play_wav(path: Path) -> None:
    for cmd in (
        ["paplay", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
        ["mpv", "--no-video", str(path)],
        ["aplay", str(path)],
    ):
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise RuntimeError("No audio player found (install pulseaudio-utils: paplay)")


def chunk_text(text: str, max_len: int) -> list[str]:
    text = " ".join(text.split())
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        candidate = f"{current} {part}".strip() if current else part
        if len(candidate) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(part) <= max_len:
            current = part
            continue
        for i in range(0, len(part), max_len):
            chunks.append(part[i : i + max_len].rstrip())
        current = ""
    if current:
        chunks.append(current)
    return chunks or [text[:max_len]]


def synthesize_chunk(text: str) -> bytes:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")

    payload = {
        "text": text,
        "target_language_code": (
            os.environ.get("ARKA_SPEAK_LANG")
            or os.environ.get("SARVAM_TTS_LANG")
            or "en-IN"
        ),
        "model": os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3"),
        "speaker": os.environ.get("SARVAM_TTS_SPEAKER", "anushka"),
        "speech_sample_rate": int(os.environ.get("SARVAM_TTS_SAMPLE_RATE", "24000")),
    }

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-subscription-key": key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Sarvam TTS HTTP {exc.code}: {body[:300]}") from exc

    audios = data.get("audios") or []
    if not audios:
        raise RuntimeError("Sarvam TTS returned no audio")
    return base64.b64decode("".join(audios))


def speak(text: str) -> None:
    text = " ".join(text.split())
    if not text:
        return

    max_len = int(os.environ.get("AGENT_SPEAK_MAX", str(DEFAULT_CHUNK)))
    max_len = min(max_len, 2500)

    for chunk in chunk_text(text, max_len):
        audio_bytes = synthesize_chunk(chunk)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = Path(tmp.name)
        try:
            play_wav(wav_path)
        finally:
            wav_path.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read()
    try:
        speak(text)
    except Exception as exc:
        print(f"sarvam_speak: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
