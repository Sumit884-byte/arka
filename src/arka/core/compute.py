#!/usr/bin/env python3
"""Auto-detect CPU cores and GPU for parallel work across Arka scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


@lru_cache(maxsize=1)
def cpu_count() -> int:
    return _env_int("CPU_WORKERS", max(1, os.cpu_count() or 4))


@lru_cache(maxsize=1)
def gpu_available() -> bool:
    if os.environ.get("FORCE_CPU", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if shutil.which("nvidia-smi"):
        try:
            proc = subprocess.run(
                ["nvidia-smi", "-L"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return Path("/dev/nvidia0").exists()


@lru_cache(maxsize=1)
def gpu_name() -> str:
    if not gpu_available():
        return ""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().split("\n")[0].strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "CUDA GPU"


def whisper_device() -> str:
    raw = os.environ.get("LOCAL_WHISPER_DEVICE", "").strip()
    if raw:
        return raw
    return "cuda" if gpu_available() else "cpu"


def whisper_compute_type(device: str | None = None) -> str:
    raw = os.environ.get("LOCAL_WHISPER_COMPUTE", "").strip()
    if raw:
        return raw
    dev = device or whisper_device()
    return "float16" if dev == "cuda" else "int8"


def ffmpeg_threads() -> int:
    return _env_int("FFMPEG_THREADS", max(1, min(cpu_count(), 8)))


def ffmpeg_thread_args() -> list[str]:
    return ["-threads", str(ffmpeg_threads())]


def io_workers(cap: int = 16) -> int:
    return _env_int("IO_WORKERS", max(2, min(cpu_count(), cap)))


def process_workers(cap: int = 8) -> int:
    default = max(1, min(cpu_count() - 1, cap)) if cpu_count() > 1 else 1
    return _env_int("PROCESS_WORKERS", default)


def stt_parallel_workers(*, local: bool = False) -> int:
    if os.environ.get("STT_WORKERS", "").strip():
        return _env_int("STT_WORKERS", 1)
    if local:
        return 1
    return min(3, io_workers(16))


def llm_parallel_workers() -> int:
    return _env_int("LLM_WORKERS", max(2, min(8, io_workers(8))))


def yt_dlp_concurrent_fragments() -> int:
    return _env_int("YTDLP_FRAGMENTS", max(4, min(16, io_workers(16))))


def export_env_defaults() -> None:
    """Set worker env vars for child processes (youtube_bulk app, etc.)."""
    os.environ.setdefault("IO_WORKERS", str(io_workers()))
    os.environ.setdefault("YOUTUBE_BULK_WORKERS", str(io_workers(8)))


def log_compute_summary(stream=None) -> None:
    stream = stream or sys.stderr
    gpu = gpu_name()
    if gpu:
        print(
            f"arka: using {cpu_count()} CPU threads"
            f" + GPU ({gpu}, whisper={whisper_device()}/{whisper_compute_type()})",
            file=stream,
        )
    else:
        print(f"arka: using {cpu_count()} CPU threads (no GPU — whisper=cpu/int8)", file=stream)


def cmd_status(_args) -> int:
    log_compute_summary(sys.stdout)
    print(f"ffmpeg_threads={ffmpeg_threads()}")
    print(f"io_workers={io_workers()}")
    print(f"process_workers={process_workers()}")
    print(f"stt_parallel={stt_parallel_workers()} (cloud) / {stt_parallel_workers(local=True)} (local)")
    print(f"llm_parallel={llm_parallel_workers()}")
    print(f"yt_dlp_fragments={yt_dlp_concurrent_fragments()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cmd_status(None))
