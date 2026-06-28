#!/usr/bin/env python3
"""Transcribe speech via Sarvam Saaras v3 (Indian English / Indic)."""

from __future__ import annotations

import io
import json
import os
import sys
import uuid
import urllib.error
import urllib.request
import wave

API_URL = "https://api.sarvam.ai/speech-to-text"


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def transcribe_pcm(pcm: bytes, *, sample_rate: int = 16000) -> str:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    if len(pcm) < sample_rate // 2:
        return ""

    wav_bytes = pcm_to_wav(pcm, sample_rate)
    model = (os.environ.get("SARVAM_STT_MODEL") or "saaras:v3").strip()
    mode = (os.environ.get("SARVAM_STT_MODE") or "transcribe").strip()
    lang = (
        os.environ.get("SARVAM_STT_LANG")
        or os.environ.get("ARKA_SPEAK_LANG")
        or os.environ.get("SARVAM_TTS_LANG")
        or "hi-IN"
    ).strip()

    boundary = f"----ArkaSarvam{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )

    add_field("model", model)
    add_field("mode", mode)
    if lang and lang.lower() not in ("unknown", "auto"):
        add_field("language_code", lang)
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"command.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(wav_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "api-subscription-key": key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Sarvam STT HTTP {exc.code}: {body_text[:300]}") from exc

    text = str(data.get("transcript") or "").strip()
    return text


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        path = sys.argv[2] if len(sys.argv) > 2 else ""
        if not path:
            print("Usage: sarvam_stt.py --file <wav|mp3|mp4>", file=sys.stderr)
            return 1
        from pathlib import Path
        import subprocess

        proc = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            print(proc.stderr.decode(), file=sys.stderr)
            return 1
        try:
            print(transcribe_pcm(proc.stdout))
        except Exception as exc:
            print(f"sarvam_stt: {exc}", file=sys.stderr)
            return 1
        return 0

    print("Usage: sarvam_stt.py --file <audio|video>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
