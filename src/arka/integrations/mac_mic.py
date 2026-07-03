#!/usr/bin/env python3
"""macOS microphone capture for Arka listen.

Patterns from proven GitHub projects:
  - creativoma/jarvis — blocking sounddevice RawInputStream.read()
  - Nenotriple/PySpeech — PyAudio fallback
  - ffmpeg avfoundation — system-level Core Audio fallback

See: https://github.com/creativoma/jarvis
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Iterator

SAMPLE_RATE = 16000
READ_FRAMES = 4000  # jarvis uses 4000 frames per read


def log(msg: str) -> None:
    print(f"[arka-mic] {msg}", flush=True)


def _env_device() -> str | None:
    dev = (os.environ.get("MIC_DEVICE") or os.environ.get("PULSE_SOURCE") or "").strip()
    return dev or None


def list_input_devices() -> list[dict]:
    """Return input-capable audio devices with index and name."""
    devices: list[dict] = []
    try:
        import sounddevice as sd

        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                devices.append({"index": i, "name": d.get("name", "?"), "channels": d["max_input_channels"]})
        return devices
    except ImportError:
        pass

    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
    )
    text = (proc.stderr or "") + (proc.stdout or "")
    for line in text.splitlines():
        m = re.search(r"\[AVFoundation input device @ .+\]\s+(\[\d+\]\s+.+)", line)
        if m:
            label = m.group(1).strip()
            idx_m = re.match(r"\[(\d+)\]\s*(.*)", label)
            if idx_m:
                devices.append({"index": int(idx_m.group(1)), "name": idx_m.group(2).strip(), "channels": 1})
    return devices


def resolve_input_device() -> int | None:
    """Pick mic index: ARKA_MIC_DEVICE > MacBook built-in > default."""
    env = _env_device()
    try:
        import sounddevice as sd
    except ImportError:
        return int(env) if env and env.isdigit() else None

    if env:
        if env.isdigit():
            return int(env)
        for i, d in enumerate(sd.query_devices()):
            if env.lower() in str(d.get("name", "")).lower() and d.get("max_input_channels", 0) > 0:
                return i

    if sys.platform == "darwin":
        prefer = (
            "macbook pro microphone",
            "macbook air microphone",
            "macbook microphone",
            "built-in microphone",
            "internal microphone",
        )
        for needle in prefer:
            for i, d in enumerate(sd.query_devices()):
                name = str(d.get("name", "")).lower()
                if needle in name and d.get("max_input_channels", 0) > 0:
                    log(f"Using built-in mic [{i}] {d.get('name')}")
                    return i

    default = sd.default.device
    if isinstance(default, (list, tuple)) and default:
        inp = default[0]
        if inp is not None and inp >= 0:
            return int(inp)
    return None


def permission_hint() -> str:
    return (
        "macOS microphone: run `arka listen fg` once in Terminal and click Allow when prompted. "
        "Background listen needs permission granted to the Python binary first "
        "(System Settings → Privacy & Security → Microphone)."
    )


def mic_selftest(seconds: float = 2.0) -> int:
    """Record briefly and report peak level; 0 = OK, 1 = no signal, 2 = error."""
    log("Mic self-test — speak now …")
    chunks: list[bytes] = []
    try:
        for data in mic_stream():
            chunks.append(data)
            if sum(len(c) for c in chunks) >= int(SAMPLE_RATE * 2 * seconds):
                break
    except Exception as exc:
        log(f"FAILED: {exc}")
        log(permission_hint())
        return 2

    if not chunks:
        log("FAILED: no audio captured")
        return 2

    pcm = b"".join(chunks)
    peak = max(abs(int.from_bytes(pcm[i : i + 2], "little", signed=True)) for i in range(0, len(pcm) - 1, 2))
    log(f"Captured {len(pcm)} bytes, peak amplitude {peak}")
    if peak < 100:
        log("WARNING: very quiet — check mic input level or wrong device (try ARKA_MIC_DEVICE=2)")
        return 1
    log("OK — microphone is hearing audio")
    return 0


def _stream_sounddevice_blocking(device: int | None) -> Iterator[bytes]:
    """Blocking read loop (creativoma/jarvis pattern — reliable on macOS)."""
    import sounddevice as sd

    kwargs: dict = {
        "samplerate": SAMPLE_RATE,
        "blocksize": READ_FRAMES,
        "dtype": "int16",
        "channels": 1,
    }
    if device is not None:
        kwargs["device"] = device

    name = "default"
    if device is not None:
        try:
            name = sd.query_devices(device).get("name", str(device))
        except Exception:
            name = str(device)
    log(f"sounddevice RawInputStream [{device if device is not None else 'default'}] {name}")

    with sd.RawInputStream(**kwargs) as stream:
        while True:
            data, _overflowed = stream.read(READ_FRAMES)
            if data:
                yield bytes(data)


def _stream_pyaudio(device_index: int | None) -> Iterator[bytes]:
    """PyAudio fallback (Nenotriple/PySpeech pattern)."""
    import pyaudio

    pa = pyaudio.PyAudio()
    chunk = READ_FRAMES * 2  # bytes for int16 mono
    kwargs: dict = {
        "format": pyaudio.paInt16,
        "channels": 1,
        "rate": SAMPLE_RATE,
        "input": True,
        "frames_per_buffer": READ_FRAMES,
    }
    if device_index is not None:
        kwargs["input_device_index"] = device_index

    log(f"PyAudio input device_index={device_index if device_index is not None else 'default'}")
    stream = pa.open(**kwargs)
    try:
        while True:
            yield stream.read(READ_FRAMES, exception_on_overflow=False)
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def _stream_ffmpeg_avfoundation(device_index: int | None) -> Iterator[bytes]:
    """ffmpeg avfoundation — works when Python libs fail (needs brew/conda ffmpeg)."""
    idx = device_index if device_index is not None else 0
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "avfoundation",
        "-i",
        f":{idx}",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    ]
    log(f"ffmpeg avfoundation device :{idx}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        while True:
            data = proc.stdout.read(READ_FRAMES * 2)
            if not data:
                err = proc.stderr.read().decode() if proc.stderr else ""
                if err.strip():
                    raise RuntimeError(err.strip()[:300])
                break
            yield data
    finally:
        proc.terminate()
        proc.wait(timeout=2)


def mic_stream() -> Iterator[bytes]:
    """Best available macOS/Linux portable mic stream at 16 kHz mono s16le."""
    device = resolve_input_device()

    if sys.platform == "darwin":
        order = ("sounddevice", "pyaudio", "ffmpeg")
    else:
        order = ("sounddevice", "pyaudio")

    errors: list[str] = []
    for backend in order:
        try:
            if backend == "sounddevice":
                yield from _stream_sounddevice_blocking(device)
                return
            if backend == "pyaudio":
                idx = device
                try:
                    import pyaudio  # noqa: F401
                except ImportError:
                    continue
                yield from _stream_pyaudio(idx)
                return
            if backend == "ffmpeg" and shutil_which("ffmpeg"):
                yield from _stream_ffmpeg_avfoundation(device)
                return
        except Exception as exc:
            errors.append(f"{backend}: {exc}")

    hint = permission_hint() if sys.platform == "darwin" else ""
    detail = "; ".join(errors) if errors else "no backend available"
    raise RuntimeError(f"Microphone capture failed ({detail}). {hint}".strip())


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="macOS mic utilities for Arka")
    p.add_argument("--list", action="store_true", help="List input devices")
    args = p.parse_args()
    if args.list:
        for d in list_input_devices():
            print(f"[{d['index']}] {d['name']}")
        raise SystemExit(0)
    p.print_help()
