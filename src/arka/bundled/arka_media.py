#!/usr/bin/env python3
"""Transcribe and summarize local audio/video (mp3, mp4, wav, m4a, …)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import urllib.error
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from arka_progress import ProgressBar, progress_enabled, run_spinner
from arka_media_qa import QA_CONTEXT_CHARS, answer_system_prompt, retrieve_transcript_context
from arka_compute import (
    export_env_defaults,
    ffmpeg_thread_args,
    llm_parallel_workers,
    log_compute_summary,
    process_workers,
    stt_parallel_workers,
    whisper_compute_type,
    whisper_device,
)

MEDIA_EXTENSIONS = frozenset({
    ".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".opus", ".webm", ".mkv", ".mov", ".aac", ".flac",
})
CACHE_DIR = Path.home() / ".cache/fish-agent/transcripts"
SAMPLE_RATE = 16000
GROQ_MAX_BYTES = 24 * 1024 * 1024
SARVAM_MAX_CHUNK_SECONDS = 25
LOCAL_FULL_MAX_SECONDS = int(os.environ.get("ARKA_LOCAL_FULL_MAX_SECONDS", "1800"))
DEFAULT_LOCAL_MODEL = "base"
DEFAULT_SUMMARY_QUESTION = (
    "Summarize the entire video from beginning to end. Explain everything important — "
    "plot, characters, key events, turning points, and how it ends — in a short, concise way. "
    "Use clear paragraphs or bullets. No filler or repetition, but do not skip major story beats."
)
SUMMARY_CHUNK_CHARS = int(os.environ.get("ARKA_MEDIA_SUMMARY_CHUNK", "12000"))
STT_CHUNK_SECONDS = int(os.environ.get("ARKA_STT_CHUNK_SECONDS", "300"))


def _emit_status(msg: str) -> None:
    """Status lines on stderr — hidden when progress bar mode is active."""
    if progress_enabled():
        return
    print(msg, file=sys.stderr)


def _load_fish_env() -> None:
    """Load user .env when Python is not started from a fully-sourced fish shell."""
    try:
        import arka_paths as ap

        ap.load_env_file()
        return
    except ImportError:
        pass
    for env_file in (
        Path.home() / ".config" / "arka" / ".env",
        Path.home() / ".config" / "fish" / ".env",
    ):
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            val = re.sub(r"\s+#.*$", "", val).strip()
            if key and not os.environ.get(key, "").strip():
                os.environ[key] = val
        return


def _which(name: str) -> str | None:
    for p in os.environ.get("PATH", "").split(":"):
        candidate = Path(p) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _speak_lang_code() -> str:
    raw = (
        os.environ.get("ARKA_MEDIA_LANG")
        or os.environ.get("ARKA_SPEAK_LANG")
        or os.environ.get("SARVAM_STT_LANG")
        or "en-IN"
    ).strip()
    return raw.split("-")[0].lower() or "en"


def _duration_seconds(path: Path) -> float:
    ffprobe = _which("ffprobe")
    if not ffprobe:
        return 0.0
    proc = subprocess.run(
        [
            ffprobe,
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
        check=False,
    )
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return 0.0


def _ffmpeg_to_wav(src: Path, dst: Path) -> None:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required — install: sudo apt install ffmpeg")
    proc = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *ffmpeg_thread_args(),
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            str(dst),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {(proc.stderr or proc.stdout or proc.returncode).strip()}")


def _compress_for_upload(src: Path) -> Path:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        return src
    tmp = Path(tempfile.mkdtemp(prefix="arka-media-"))
    out = tmp / f"{src.stem}.mp3"
    proc = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *ffmpeg_thread_args(),
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not out.is_file():
        return src
    return out


def _pcm_to_wav_bytes(pcm: bytes) -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _read_pcm(path: Path, duration: float = 0.0, bar: ProgressBar | None = None) -> bytes:
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *ffmpeg_thread_args(),
        "-progress",
        "pipe:2",
        "-nostats",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    assert proc.stdout is not None
    assert proc.stderr is not None

    pcm = bytearray()
    read_done = threading.Event()

    def _track_ffmpeg() -> None:
        if bar is None:
            proc.stderr.read()
            return
        for raw in proc.stderr:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("out_time_ms="):
                continue
            try:
                ms = int(line.split("=", 1)[1])
            except ValueError:
                continue
            if duration > 0:
                bar.fraction(ms / 1_000_000 / duration, label="Extracting audio")
        read_done.set()

    tracker = threading.Thread(target=_track_ffmpeg, daemon=True)
    tracker.start()
    while True:
        chunk = proc.stdout.read(1024 * 1024)
        if not chunk:
            break
        pcm.extend(chunk)
    proc.wait()
    read_done.wait(timeout=2)
    if proc.returncode != 0:
        err = proc.stderr.read().decode(errors="replace").strip()
        raise SystemExit(f"ffmpeg audio extract failed: {err or proc.returncode}")
    if len(pcm) < SAMPLE_RATE // 2:
        raise SystemExit(f"No usable audio in {path.name}")
    if bar is not None:
        bar.set(bar.total, label="Extracting audio")
    return bytes(pcm)


def _groq_transcribe_upload(path: Path) -> str | None:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return None
    upload = path
    if path.stat().st_size > GROQ_MAX_BYTES:
        upload = _compress_for_upload(path)
    model = (os.environ.get("GROQ_WHISPER_MODEL") or "whisper-large-v3-turbo").strip()
    lang = _speak_lang_code()
    boundary = f"----ArkaMedia{uuid.uuid4().hex}"
    file_bytes = upload.read_bytes()
    ext = upload.suffix.lower()
    mime = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")
    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    add_field("model", model)
    add_field("language", lang)
    add_field("response_format", "json")
    add_field("temperature", "0")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{upload.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    timeout = max(120, min(900, int(upload.stat().st_size / 20000) + 60))
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return str(data.get("text") or "").strip()
    except Exception as exc:
        print(f"arka_media: Groq STT failed: {exc}", file=sys.stderr)
        return None


def _sarvam_transcribe_pcm(pcm: bytes) -> str | None:
    try:
        from sarvam_stt import transcribe_pcm
    except ImportError:
        return None
    try:
        return transcribe_pcm(pcm, sample_rate=SAMPLE_RATE).strip()
    except Exception as exc:
        print(f"arka_media: Sarvam STT failed: {exc}", file=sys.stderr)
        return None


def _local_python_candidates() -> list[str]:
    raw: list[str] = []
    if os.environ.get("ARKA_MEDIA_PYTHON", "").strip():
        raw.append(os.environ["ARKA_MEDIA_PYTHON"].strip())
    try:
        import arka_paths as ap

        raw.append(str(ap.arka_home() / "venv-arka/bin/python3"))
        raw.append(str(ap.config_dir() / "venv-voice-hf/bin/python3"))
    except ImportError:
        pass
    raw.extend([
        str(Path.home() / ".config/arka/venv-voice-hf/bin/python3"),
        str(Path.home() / ".config/fish/venv-voice-hf/bin/python3"),
        str(Path.home() / ".config/fish/venv-arka/bin/python3"),
        sys.executable,
    ])
    out: list[str] = []
    for py in raw:
        if py and py not in out and Path(py).is_file():
            out.append(py)
    return out


def _faster_whisper_available(py: str) -> bool:
    proc = subprocess.run(
        [py, "-c", "from faster_whisper import WhisperModel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _ensure_local_stt(*, auto_install: bool = True) -> bool:
    for py in _local_python_candidates():
        if _faster_whisper_available(py):
            if not os.environ.get("ARKA_MEDIA_PYTHON", "").strip():
                os.environ["ARKA_MEDIA_PYTHON"] = py
            return True
    if not auto_install:
        return False
    print("arka_media: setting up offline STT (faster-whisper) …", file=sys.stderr)
    if cmd_setup_local(argparse.Namespace()) != 0:
        return False
    for py in _local_python_candidates():
        if _faster_whisper_available(py):
            os.environ["ARKA_MEDIA_PYTHON"] = py
            return True
    return False


def _local_whisper_config() -> tuple[str, str, str, str | None]:
    model = (
        os.environ.get("ARKA_LOCAL_WHISPER_MODEL")
        or os.environ.get("ARKA_HF_STT_MODEL")
        or DEFAULT_LOCAL_MODEL
    ).strip()
    device = whisper_device()
    compute = whisper_compute_type(device)
    lang = _speak_lang_code() or None
    if lang == "auto":
        lang = None
    return model, device, compute, lang


def _ensure_wav(path: Path) -> tuple[Path, bool]:
    if path.suffix.lower() == ".wav":
        return path, False
    fh = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    fh.close()
    wav = Path(fh.name)
    _ffmpeg_to_wav(path, wav)
    return wav, True


def _faster_whisper_via_python(py: str, wav: Path) -> str | None:
    model, device, compute, lang = _local_whisper_config()
    cpu_threads = str(process_workers())
    script = r"""
import sys
from faster_whisper import WhisperModel

wav, model_name, device, compute, lang, cpu_threads = sys.argv[1:7]
lang = lang or None
model = WhisperModel(
    model_name,
    device=device,
    compute_type=compute,
    cpu_threads=int(cpu_threads),
)
segments, _info = model.transcribe(wav, language=lang or None, vad_filter=True)
parts = [s.text.strip() for s in segments if s.text and s.text.strip()]
print(" ".join(parts))
"""
    proc = subprocess.run(
        [py, "-c", script, str(wav), model, device, compute, lang or "", cpu_threads],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if err and "No module named" not in err:
            print(f"arka_media: faster-whisper ({py}): {err[:240]}", file=sys.stderr)
        return None
    return (proc.stdout or "").strip()


def _whisper_cli_transcribe(wav: Path) -> str | None:
    whisper = _which("whisper")
    if not whisper:
        return None
    model = (os.environ.get("ARKA_LOCAL_WHISPER_MODEL") or "small").strip()
    lang = _speak_lang_code()
    out_dir = Path(tempfile.mkdtemp(prefix="arka-whisper-"))
    proc = subprocess.run(
        [
            whisper,
            str(wav),
            "--model",
            model,
            "--language",
            lang,
            "--output_dir",
            str(out_dir),
            "--output_format",
            "txt",
            "--fp16",
            "False",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"arka_media: whisper CLI failed: {(proc.stderr or proc.stdout or '').strip()[:240]}", file=sys.stderr)
        return None
    txt_files = sorted(out_dir.glob("*.txt"))
    if not txt_files:
        return ""
    return txt_files[0].read_text(encoding="utf-8", errors="replace").strip()


def _local_whisper_transcribe(path: Path, bar: ProgressBar | None = None) -> str | None:
    wav, is_temp = _ensure_wav(path)
    try:
        label = "Transcribing locally"
        if bar is not None:
            bar.set(0, label=label)
        elif progress_enabled():
            print("Transcribing locally (faster-whisper) …", file=sys.stderr)

        def _run() -> str | None:
            for py in _local_python_candidates():
                text = _faster_whisper_via_python(py, wav)
                if text is not None:
                    if not bar and progress_enabled():
                        print(f"arka_media: local STT via {py}", file=sys.stderr)
                    return text
            if _ensure_local_stt(auto_install=True):
                for py in _local_python_candidates():
                    text = _faster_whisper_via_python(py, wav)
                    if text is not None:
                        if not bar and progress_enabled():
                            print(f"arka_media: local STT via {py}", file=sys.stderr)
                        return text
            text = _whisper_cli_transcribe(wav)
            if text is not None and not bar and progress_enabled():
                print("arka_media: local STT via whisper CLI", file=sys.stderr)
            return text

        result = run_spinner(label, _run) if bar is None and progress_enabled() else _run()
        if bar is not None:
            bar.set(bar.total, label=label)
        return result
    finally:
        if is_temp:
            wav.unlink(missing_ok=True)


def _stt_preference() -> str:
    return (os.environ.get("ARKA_MEDIA_STT") or os.environ.get("ARKA_STT") or "auto").strip().lower()


def _cloud_allowed() -> bool:
    return _stt_preference() in {"auto", "groq", "sarvam", "cloud"}


def _local_allowed() -> bool:
    return _stt_preference() in {"auto", "local", "offline", "whisper", "faster-whisper"}


def _local_setup_hint() -> str:
    try:
        import arka_paths as ap

        venv = ap.config_dir() / "venv-voice-hf"
    except ImportError:
        venv = Path.home() / ".config/fish/venv-voice-hf"
    return (
        "Local STT not available. Install faster-whisper:\n"
        f"  media_transcript --setup-local\n"
        f"  (creates {venv})\n"
        "Then set ARKA_MEDIA_STT=local to force offline, or leave auto for cloud+local fallback."
    )


def cmd_setup_local(_args: argparse.Namespace) -> int:
    try:
        import arka_paths as ap

        venv = ap.config_dir() / "venv-voice-hf"
    except ImportError:
        venv = Path.home() / ".config/fish/venv-voice-hf"
    venv.parent.mkdir(parents=True, exist_ok=True)
    py = venv / "bin/python3"
    if not py.is_file():
        print(f"Creating {venv} …", file=sys.stderr)
        for creator in ("python3.12", "python3.11", "python3", sys.executable):
            if creator == sys.executable or shutil.which(creator.split()[0]):
                r = subprocess.run([creator, "-m", "venv", str(venv)], check=False)
                if r.returncode == 0 and py.is_file():
                    break
    if not py.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    print("Installing faster-whisper (CPU) …", file=sys.stderr)
    subprocess.run([str(py), "-m", "pip", "install", "-U", "pip", "wheel"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "faster-whisper"], check=True)
    proc = subprocess.run([str(py), "-c", "from faster_whisper import WhisperModel; print('ok')"], check=False)
    if proc.returncode != 0:
        return 1
    print(f"Ready. Use: ARKA_MEDIA_PYTHON={py} media_transcript <file>")
    return 0


def _partial_transcript_path(src: Path) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-") or "media"
    return CACHE_DIR / f"{slug}.parts.json"


def _load_partial_transcript(src: Path) -> dict[int, str]:
    path = _partial_transcript_path(src)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {int(k): str(v) for k, v in raw.items()}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def _save_partial_transcript(src: Path, parts: dict[int, str]) -> None:
    path = _partial_transcript_path(src)
    path.write_text(
        json.dumps({str(k): v for k, v in sorted(parts.items())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _chunk_pcm(pcm: bytes, chunk_seconds: int | None = None) -> list[bytes]:
    if chunk_seconds is None:
        chunk_seconds = STT_CHUNK_SECONDS
    bytes_per_chunk = chunk_seconds * SAMPLE_RATE * 2
    return [pcm[i : i + bytes_per_chunk] for i in range(0, len(pcm), bytes_per_chunk)]


def _transcribe_pcm_chunk_groq(pcm: bytes) -> str | None:
    if not (_cloud_allowed() and os.environ.get("GROQ_API_KEY")):
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
        fh.write(_pcm_to_wav_bytes(pcm))
        tmp = Path(fh.name)
    try:
        return _groq_transcribe_upload(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _transcribe_pcm_chunk_local(pcm: bytes) -> str | None:
    if not _local_allowed():
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
        fh.write(_pcm_to_wav_bytes(pcm))
        tmp = Path(fh.name)
    try:
        for py in _local_python_candidates():
            text = _faster_whisper_via_python(py, tmp)
            if text is not None:
                return text
        return _whisper_cli_transcribe(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _transcribe_pcm_chunk_sarvam(pcm: bytes) -> str | None:
    if not (_cloud_allowed() and os.environ.get("SARVAM_API_KEY")):
        return None
    parts: list[str] = []
    for sub in _chunk_pcm(pcm, SARVAM_MAX_CHUNK_SECONDS):
        part = _sarvam_transcribe_pcm(sub)
        if part is None:
            return None
        if part:
            parts.append(part)
    return " ".join(parts)


def _transcribe_pcm_chunk(pcm: bytes, *, skip_groq: bool = False) -> str | None:
    prefer = _stt_preference()
    text: str | None = None
    if (
        not skip_groq
        and _cloud_allowed()
        and prefer in {"groq", "auto", "cloud"}
        and os.environ.get("GROQ_API_KEY")
    ):
        text = _transcribe_pcm_chunk_groq(pcm)
    if text is None and _local_allowed() and prefer in {"local", "offline", "whisper", "faster-whisper", "auto"}:
        text = _transcribe_pcm_chunk_local(pcm)
    if text is None and _cloud_allowed() and prefer in {"sarvam", "auto", "cloud"} and os.environ.get("SARVAM_API_KEY"):
        text = _transcribe_pcm_chunk_sarvam(pcm)
    if text is None and _local_allowed() and prefer in {"auto", "groq", "sarvam", "cloud"}:
        text = _transcribe_pcm_chunk_local(pcm)
    return text


def _transcribe_pcm(pcm: bytes, bar: ProgressBar | None = None, src: Path | None = None) -> str:
    chunks = _chunk_pcm(pcm)
    prefer = _stt_preference()
    local_only = prefer in {"local", "offline", "whisper", "faster-whisper"}
    results: dict[int, str] = {}

    if src is not None:
        cached = _load_partial_transcript(src)
        for idx, text in cached.items():
            if 0 <= idx < len(chunks) and text:
                results[idx] = text
        if results:
            _emit_status(f"Resuming transcription ({len(results)}/{len(chunks)} parts cached) …")

    pending = [i for i in range(len(chunks)) if i not in results]
    if not pending:
        return " ".join(results[i] for i in range(len(chunks))).strip()

    use_groq = (
        not local_only
        and _cloud_allowed()
        and prefer in {"groq", "auto", "cloud"}
        and os.environ.get("GROQ_API_KEY")
    )
    groq_workers = min(stt_parallel_workers(local=False), 3) if use_groq else 0

    groq_failed: set[int] = set()

    if use_groq and len(pending) > 1 and groq_workers > 1:
        _emit_status(f"Transcribing {len(pending)} parts via Groq ({groq_workers} at a time) …")
        failed: list[int] = []
        done = len(results)
        with ThreadPoolExecutor(max_workers=groq_workers) as pool:
            futures = {pool.submit(_transcribe_pcm_chunk_groq, chunks[i]): i for i in pending}
            for fut in as_completed(futures):
                idx = futures[fut]
                text = fut.result()
                if text is None:
                    failed.append(idx)
                else:
                    results[idx] = text
                    if src is not None:
                        _save_partial_transcript(src, results)
                done += 1
                if bar is not None:
                    bar.set(done, total=len(chunks), label=f"Transcribing {done}/{len(chunks)}")
        groq_failed = set(failed)
        pending = failed

    for idx in pending:
        if bar is not None:
            bar.set(len(results), total=len(chunks), label=f"Transcribing {idx + 1}/{len(chunks)}")
        elif len(chunks) > 1 and not progress_enabled():
            _emit_status(f"Transcribing part {idx + 1}/{len(chunks)} …")
        text = _transcribe_pcm_chunk(chunks[idx], skip_groq=idx in groq_failed)
        if text is None and _local_allowed():
            _ensure_local_stt(auto_install=(idx == 0))
            text = _transcribe_pcm_chunk_local(chunks[idx])
        if text is None:
            hints = [_local_setup_hint()]
            if _cloud_allowed():
                hints.insert(
                    0,
                    f"STT failed on part {idx + 1}/{len(chunks)}. "
                    "Check GROQ_API_KEY/SARVAM_API_KEY in ~/.config/fish/.env or run: media_transcript --setup-local",
                )
            raise SystemExit("\n\n".join(hints))
        results[idx] = text
        if src is not None:
            _save_partial_transcript(src, results)
        if bar is not None:
            bar.set(len(results), total=len(chunks), label=f"Transcribing {len(results)}/{len(chunks)}")

    if bar is not None:
        bar.set(len(chunks), total=len(chunks), label="Transcribing")
    if src is not None:
        _partial_transcript_path(src).unlink(missing_ok=True)
    return " ".join(results[i] for i in range(len(chunks))).strip()


def _groq_transcribe_upload_path_from_pcm(pcm: bytes) -> str | None:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
        fh.write(_pcm_to_wav_bytes(pcm))
        tmp = Path(fh.name)
    try:
        return _groq_transcribe_upload(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _youtube_captions_allowed() -> bool:
    pref = (os.environ.get("ARKA_MEDIA_YOUTUBE") or "auto").strip().lower()
    return pref not in {"0", "no", "false", "off", "never", "skip"}


def _try_youtube_captions(
    path: Path,
    *,
    youtube_url: str | None = None,
    bar: ProgressBar | None = None,
) -> str | None:
    try:
        from arka_youtube import try_transcript_for_media
    except ImportError:
        return None
    if bar is not None:
        bar.set(0, label="Fetching YouTube captions")
    elif not progress_enabled():
        _emit_status("Trying YouTube captions …")
    result = try_transcript_for_media(path, youtube_url=youtube_url)
    if not result:
        return None
    video_id, text, source = result
    _emit_status(
        f"YouTube captions ({source}): https://youtube.com/watch?v={video_id} "
        f"({len(text.split())} words)"
    )
    if bar is not None:
        bar.set(bar.total, label="YouTube captions")
    return text


def transcribe_file(
    path: Path,
    bar: ProgressBar | None = None,
    *,
    youtube_url: str | None = None,
    skip_youtube: bool = False,
) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"Not a file: {path}")
    ext = path.suffix.lower()
    if ext and ext not in MEDIA_EXTENSIONS:
        raise SystemExit(
            f"Unsupported media type '{ext}'. Supported: {', '.join(sorted(MEDIA_EXTENSIONS))}"
        )

    dur = _duration_seconds(path)
    size = path.stat().st_size
    _emit_status(f"Media: {path.name} ({size // 1024} KB" + (f", ~{int(dur)}s" if dur else "") + ")")

    if not skip_youtube and _youtube_captions_allowed():
        yt_text = _try_youtube_captions(path, youtube_url=youtube_url, bar=bar)
        if yt_text:
            return yt_text
        _emit_status("YouTube captions unavailable — falling back to speech-to-text …")

    prefer = _stt_preference()

    if prefer in {"local", "offline", "whisper", "faster-whisper"}:
        text = _local_whisper_transcribe(path, bar=bar)
        if text is not None:
            return text
        raise SystemExit(_local_setup_hint())

    # Fast path: upload whole file to Groq when reasonably sized
    if _cloud_allowed() and prefer in {"groq", "auto", "cloud"} and os.environ.get("GROQ_API_KEY") and size <= GROQ_MAX_BYTES:
        if bar is not None:
            bar.set(0, label="Uploading to Groq STT")
        text = _groq_transcribe_upload(path)
        if text:
            if bar is not None:
                bar.set(bar.total, label="Transcribing")
            return text

    # Local full-file before chunking — skip for very long media (use chunked path instead)
    if _local_allowed() and (not dur or dur <= LOCAL_FULL_MAX_SECONDS):
        text = _local_whisper_transcribe(path, bar=bar)
        if text is not None:
            return text
    elif _local_allowed() and dur and dur > LOCAL_FULL_MAX_SECONDS:
        _emit_status(
            f"arka_media: skipping local full-file STT (~{int(dur)}s > {LOCAL_FULL_MAX_SECONDS}s); "
            "using chunked transcription"
        )

    pcm = _read_pcm(path, duration=dur, bar=bar)
    return _transcribe_pcm(pcm, bar=bar, src=path)


def _split_text_for_summary(text: str, max_chars: int = SUMMARY_CHUNK_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in sentences:
        if not sentence:
            continue
        add = len(sentence) + (1 if current else 0)
        if current and size + add > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            size = len(sentence)
        else:
            current.append(sentence)
            size += add
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def _is_default_summary_question(question: str) -> bool:
    q = question.strip()
    if q in {
        DEFAULT_SUMMARY_QUESTION,
        "Summarize the main points",
        "Summarize the main points clearly and concisely.",
    }:
        return True
    if not re.search(r"\b(summarize|summary|overview|tldr|brief)\b", q, re.I):
        return False
    if re.search(
        r"\b(who|why|how|when|where|what happened to|what did|what is|explain|describe|focus on|tell me about)\b",
        q,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"\b(entire|full|whole|complete|main points|beginning to end|start to finish|video|story|plot)\b",
            q,
            re.I,
        )
    )


def _llm_answer_question(context: str, question: str) -> str:
    from arka_llm import llm_complete

    system = answer_system_prompt(question)
    user = f"Question: {question}\n\nTranscript excerpts:\n{context[:QA_CONTEXT_CHARS + 2000]}"
    return llm_complete(system, user, temperature=0.2, task="summarize").strip()


def _answer_question_from_transcript(
    text: str,
    question: str,
    bar: ProgressBar | None = None,
    *,
    src: Path | None = None,
) -> str:
    if bar is not None:
        bar.set(0, total=3, label="Indexing transcript")
    context = retrieve_transcript_context(text, question, src=src)
    if bar is not None:
        bar.set(2, total=3, label="Answering")
    answer = _llm_answer_question(context, question)
    if bar is not None:
        bar.set(3, total=3, label="Answering")
    return answer


def _llm_summarize_once(text: str, question: str) -> str:
    from arka_llm import llm_complete, llm_last_error

    system = (
        "Summarize or answer from the audio/video transcript. Follow the user's instructions exactly "
        "(length, focus, format, questions). Use short paragraphs or bullets when helpful."
    )
    user = f"Question/focus: {question}\n\nTranscript:\n{text[:SUMMARY_CHUNK_CHARS + 2000]}"
    out = llm_complete(system, user, temperature=0.2, task="summarize").strip()
    if not out:
        detail = llm_last_error().strip()
        hint = "check GEMINI_API_KEY / GROQ_API_KEY or AI_PREFERRED_MODEL in .env"
        if detail:
            low = detail.lower()
            if "quota" in low or "resource_exhausted" in low or "429" in low:
                hint = (
                    "Gemini quota exceeded — set AI_PREFERRED_PROVIDER=groq, wait for quota reset, "
                    "or enable billing"
                )
            elif "invalid api key" in low or "invalid_api_key" in low:
                hint = "API key rejected — fix keys in ~/.config/arka/.env or dev/arka/.env"
            detail = detail[:240]
            raise RuntimeError(f"LLM returned empty summary ({detail}). {hint}")
        raise RuntimeError(f"LLM returned empty summary — {hint}")
    return out


def _summarize_fallback(text: str, question: str) -> str:
    """Single-shot summarize when chunked/parallel path yields nothing."""
    snippet = text[:80000]
    if len(text) > len(snippet):
        _emit_status(f"Fallback: summarizing first {len(snippet.split())} words …")
    return _llm_summarize_once(snippet, question)


def _merge_partial_summaries(partials: list[str], question: str) -> str:
    body = "\n\n".join(f"### Section {idx}\n{part}" for idx, part in enumerate(partials, start=1))
    merge_q = (
        f"{question}\n\n"
        "Combine these section summaries into ONE short, concise summary of the FULL video. "
        "Cover the complete story from start to finish; remove duplication; keep every major beat."
    )
    return _llm_summarize_once(body, merge_q)


def summarize_text(
    text: str,
    question: str,
    bar: ProgressBar | None = None,
    *,
    src: Path | None = None,
) -> str:
    if not _is_default_summary_question(question):
        return _answer_question_from_transcript(text, question, bar=bar, src=src)

    chunks = _split_text_for_summary(text)
    if len(chunks) == 1:
        if bar is not None:
            bar.set(0, total=1, label="Summarizing")
        out = _llm_summarize_once(text, question)
        if bar is not None:
            bar.set(1, label="Summarizing")
        return out

    section_q = (
        f"{question}\n\n"
        "This is one section of a longer video. Briefly capture ALL events, characters, and "
        "plot points in this section — do not skip anything important."
    )
    partials: list[str] = []
    merge_steps = 0
    groups = len(chunks)
    while groups > 1:
        groups = (groups + 3) // 4
        merge_steps += groups
    total_steps = len(chunks) + merge_steps
    step = 0
    llm_workers = llm_parallel_workers()

    if llm_workers > 1 and len(chunks) > 1 and bar is None:
        _emit_status(f"Summarizing {len(chunks)} sections on {llm_workers} workers …")
        indexed: list[str | None] = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=llm_workers) as pool:
            futures = {
                pool.submit(_llm_summarize_once, chunk, section_q): i
                for i, chunk in enumerate(chunks)
            }
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    indexed[i] = fut.result()
                except Exception as exc:
                    _emit_status(f"  Section {i + 1}/{len(chunks)} failed: {exc}")
                step += 1
                if bar is not None:
                    bar.set(step, total=total_steps, label=f"Summarizing {step}/{len(chunks)}")
        partials = [t for t in indexed if t]
    else:
        for idx, chunk in enumerate(chunks, start=1):
            if bar is not None:
                bar.set(step, total=total_steps, label=f"Summarizing {idx}/{len(chunks)}")
            elif not progress_enabled():
                _emit_status(f"  Section {idx}/{len(chunks)} …")
            try:
                partials.append(_llm_summarize_once(chunk, section_q))
            except Exception as exc:
                _emit_status(f"  Section {idx}/{len(chunks)} failed: {exc}")
            step += 1

    if not partials:
        return _summarize_fallback(text, question)

    while len(partials) > 1:
        next_partials: list[str] = []
        batch = 4
        for i in range(0, len(partials), batch):
            group = partials[i : i + batch]
            if len(group) == 1:
                next_partials.append(group[0])
            else:
                if bar is not None:
                    bar.set(step, total=total_steps, label=f"Merging {len(group)} sections")
                elif not progress_enabled():
                    _emit_status(f"  Merging {len(group)} sections …")
                try:
                    next_partials.append(_merge_partial_summaries(group, question))
                except Exception as exc:
                    _emit_status(f"  Merge failed ({len(group)} sections): {exc}")
                    next_partials.extend(group)
                step += 1
        partials = [p for p in next_partials if p]
        if not partials:
            return _summarize_fallback(text, question)

    if bar is not None:
        bar.set(total_steps, total=total_steps, label="Summarizing")
    return partials[0]


def _load_cached_transcript(src: Path) -> str | None:
    path = _default_output_path(src)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def _default_output_path(src: Path) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-") or "media"
    return CACHE_DIR / f"{slug}.txt"


def cmd_transcript(args: argparse.Namespace) -> int:
    _load_fish_env()
    export_env_defaults()
    if not progress_enabled():
        log_compute_summary()
    bar = ProgressBar("Transcribing", total=100) if progress_enabled() else None
    text = transcribe_file(
        Path(args.file),
        bar=bar,
        youtube_url=getattr(args, "youtube_url", None),
        skip_youtube=getattr(args, "no_youtube_captions", False),
    )
    if bar is not None:
        bar.done("Transcribed")
    print(f"Words: {len(text.split())}\n")
    print(text)
    if args.output:
        out = Path(args.output)
    elif args.save:
        out = _default_output_path(Path(args.file))
    else:
        out = None
    if out:
        out.write_text(text, encoding="utf-8")
        _emit_status(f"\nSaved transcript: {out}")
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    _load_fish_env()
    export_env_defaults()
    if not progress_enabled():
        log_compute_summary()
    src = Path(args.file)
    question = (args.question or DEFAULT_SUMMARY_QUESTION).strip()
    if question in {"Summarize the main points", "Summarize the main points clearly and concisely."}:
        question = DEFAULT_SUMMARY_QUESTION

    cached = _load_cached_transcript(src)
    if cached and not args.retranscribe:
        _emit_status(f"Using saved transcript ({len(cached.split())} words)")
        text = cached
    else:
        tx_bar = ProgressBar("Transcribing", total=100) if progress_enabled() else None
        text = transcribe_file(
            src,
            bar=tx_bar,
            youtube_url=getattr(args, "youtube_url", None),
            skip_youtube=getattr(args, "no_youtube_captions", False),
        )
        if tx_bar is not None:
            tx_bar.done("Transcribed")
        _emit_status(f"Words: {len(text.split())}\n")
    if args.save or args.output:
        out = Path(args.output) if args.output else _default_output_path(src)
        if args.retranscribe or not out.is_file():
            out.write_text(text, encoding="utf-8")
            _emit_status(f"Saved transcript: {out}")

    sum_bar = ProgressBar(
        "Answering" if not _is_default_summary_question(question) else "Summarizing",
        total=100,
    ) if progress_enabled() else None
    summary = summarize_text(text, question, bar=sum_bar, src=src)
    if sum_bar is not None:
        sum_bar.done("Answer ready" if not _is_default_summary_question(question) else "Summary ready")
    header = "━━━ Answer ━━━" if not _is_default_summary_question(question) else "━━━ Summary ━━━"
    print(header)
    print(summary)
    return 0


def main() -> int:
    _load_fish_env()
    parser = argparse.ArgumentParser(description="Transcribe/summarize mp3, mp4, and other media")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tx = sub.add_parser("transcript", aliases=["transcribe"], help="Transcribe media to text")
    p_tx.add_argument("file", help="Path to mp3, mp4, wav, …")
    p_tx.add_argument("-o", "--output", help="Save transcript to file")
    p_tx.add_argument("-u", "--youtube-url", help="YouTube URL/id for caption lookup (optional)")
    p_tx.add_argument("--no-youtube-captions", action="store_true", help="Skip YouTube captions; use STT only")
    p_tx.add_argument("--save", action="store_true", help="Save transcript under ~/.cache/fish-agent/transcripts/")
    p_tx.set_defaults(func=cmd_transcript)

    p_sum = sub.add_parser("summarize", help="Transcribe then summarize via LLM")
    p_sum.add_argument("file")
    p_sum.add_argument("-q", "--question", default=DEFAULT_SUMMARY_QUESTION)
    p_sum.add_argument("-o", "--output", help="Save transcript to file")
    p_sum.add_argument("-u", "--youtube-url", help="YouTube URL/id for caption lookup (optional)")
    p_sum.add_argument("--no-youtube-captions", action="store_true", help="Skip YouTube captions; use STT only")
    p_sum.add_argument("--save", action="store_true", help="Also save transcript")
    p_sum.add_argument(
        "--retranscribe",
        action="store_true",
        help="Ignore saved transcript and transcribe again",
    )
    p_sum.set_defaults(func=cmd_summarize)

    p_setup = sub.add_parser("setup-local", help="Install faster-whisper in venv-voice-hf for offline STT")
    p_setup.set_defaults(func=cmd_setup_local)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
