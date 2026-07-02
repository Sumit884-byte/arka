#!/usr/bin/env python3
"""Continuous wake-word listener for the Arka fish agent."""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import zipfile
from pathlib import Path

from arka_compute import ffmpeg_thread_args

SAMPLE_RATE = 16000
CHUNK = 8000
PID_FILE = Path.home() / ".cache" / "fish-agent" / "arka_listen.pid"
LOG_PREFIX = "[arka]"
VENV_PY = Path.home() / ".config" / "fish" / "venv-arka" / "bin" / "python3"


def _load_dotenv() -> None:
    """Load ~/.env / ARKA_HOME/.env so listen works outside a sourced fish session."""
    candidates: list[Path] = []
    for key in ("ARKA_CONFIG_DIR", "ARKA_HOME"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            candidates.append(Path(raw).expanduser() / ".env")
    candidates.extend(
        [
            Path.home() / "dev" / "arka" / ".env",
            Path.home() / ".config" / "arka" / ".env",
            Path.home() / ".config" / "fish" / ".env",
        ]
    )
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, val = line.partition("=")
            name = name.strip()
            if not name or name in os.environ:
                continue
            val = val.strip().strip('"').strip("'")
            val = re.sub(r"\s+#.*$", "", val).strip()
            if val:
                os.environ[name] = val
        break


_load_dotenv()
WAKE = os.environ.get("AGENT_NAME", "arka").strip().lower() or "arka"

MODEL_CATALOG: dict[str, tuple[str, str]] = {
    "small-us": (
        "vosk-model-small-en-us-0.15",
        "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    ),
    "small-in": (
        "vosk-model-small-en-in-0.4",
        "https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip",
    ),
    "medium-us": (
        "vosk-model-en-us-0.22-lgraph",
        "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip",
    ),
    "best-in": (
        "vosk-model-en-in-0.5",
        "https://alphacephei.com/vosk/models/vosk-model-en-in-0.5.zip",
    ),
}

DEBUG = os.environ.get("ARKA_LISTEN_DEBUG", "").strip().lower() in ("1", "true", "yes")
_LAST_PARTIAL: dict[str, str] = {"wake": "", "cmd": ""}


def log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}", flush=True)


def set_debug(enabled: bool) -> None:
    global DEBUG
    DEBUG = enabled


def debug_hear(label: str, text: str, *, partial: bool = False) -> None:
    text = text.strip()
    if not DEBUG or not text:
        return
    if partial:
        if _LAST_PARTIAL.get(label) == text:
            return
        _LAST_PARTIAL[label] = text
        log(f"hear [{label}~] {text}")
    else:
        _LAST_PARTIAL[label] = ""
        log(f"hear [{label}=] {text}")


def _speak_lang() -> str:
    return (os.environ.get("ARKA_SPEAK_LANG") or "en-IN").strip()


def _stt_backend() -> str:
    mode = (os.environ.get("ARKA_STT") or "auto").strip().lower()
    if mode in ("groq", "vosk", "sarvam", "assemblyai", "aai"):
        return "assemblyai" if mode in ("assemblyai", "aai") else mode
    if os.environ.get("ASSEMBLYAI_API_KEY", "").strip():
        return "assemblyai"
    if os.environ.get("SARVAM_API_KEY", "").strip():
        return "sarvam"
    if os.environ.get("GROQ_API_KEY", "").strip():
        return "groq"
    return "vosk"


def _use_assemblyai_commands() -> bool:
    return _stt_backend() == "assemblyai" and bool(os.environ.get("ASSEMBLYAI_API_KEY", "").strip())


def _stt_chain_label() -> str:
    """Human-readable command STT priority for logs."""
    backend = _stt_backend()
    if backend == "assemblyai":
        parts = ["AssemblyAI"]
        if os.environ.get("SARVAM_API_KEY", "").strip():
            parts.append("Sarvam")
        parts.append("Vosk")
        return " → ".join(parts)
    if backend == "sarvam":
        return "Sarvam → Vosk"
    if backend == "groq":
        return "Groq → Vosk"
    return "Vosk"


def resolve_model_preset() -> str:
    explicit = (os.environ.get("ARKA_VOSK_PRESET") or "").strip().lower()
    if explicit in MODEL_CATALOG:
        return explicit
    tier = (os.environ.get("ARKA_VOSK_TIER") or "medium").strip().lower()
    lang = _speak_lang().upper()
    indian = lang.endswith("-IN") or lang == "EN_IN"
    if tier in ("best", "large"):
        return "best-in" if indian else "medium-us"
    if tier in ("medium", "good"):
        return "small-in" if indian else "medium-us"
    return "small-in" if indian else "small-us"


def resolve_model_dir() -> Path:
    custom = (os.environ.get("ARKA_VOSK_MODEL") or "").strip()
    if custom:
        return Path(custom).expanduser()
    preset = resolve_model_preset()
    folder, _ = MODEL_CATALOG[preset]
    return Path.home() / ".cache" / folder


def resolve_model_url(model_dir: Path) -> str:
    custom = (os.environ.get("ARKA_VOSK_MODEL_URL") or "").strip()
    if custom:
        return custom
    name = model_dir.name
    for folder, url in MODEL_CATALOG.values():
        if folder == name:
            return url
    if "en-in" in name:
        return MODEL_CATALOG["small-in"][1]
    return MODEL_CATALOG["small-us"][1]


def ensure_model(model_dir: Path | None = None) -> Path:
    model_dir = model_dir or resolve_model_dir()
    if model_dir.is_dir() and any(model_dir.iterdir()):
        return model_dir
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    url = resolve_model_url(model_dir)
    zip_path = model_dir.parent / f"{model_dir.name}.zip"
    log(f"Downloading Vosk model {model_dir.name} (first run) …")
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(model_dir.parent)
    zip_path.unlink(missing_ok=True)
    if not model_dir.is_dir():
        for child in model_dir.parent.iterdir():
            if child.is_dir() and child.name.startswith(model_dir.name.split("-0")[0]):
                if child != model_dir:
                    child.rename(model_dir)
                break
    if not model_dir.is_dir():
        raise RuntimeError(f"Model download failed: {model_dir}")
    log(f"Model ready: {model_dir}")
    return model_dir


def ensure_venv_deps() -> Path:
    venv = VENV_PY.parent.parent
    py = VENV_PY
    if not py.exists():
        log("Creating venv for wake listener …")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    packages = ["vosk", "numpy"]
    if sys.platform == "darwin":
        packages.extend(["sounddevice", "pyaudio"])
    if os.environ.get("ASSEMBLYAI_API_KEY", "").strip() and _listen_engine() == "assemblyai":
        packages.append("assemblyai>=0.64.0")
    subprocess.run([str(py), "-m", "pip", "install", "-q", *packages], check=True)
    return py


def mic_device() -> str | None:
    dev = (os.environ.get("ARKA_MIC_DEVICE") or os.environ.get("PULSE_SOURCE") or "").strip()
    return dev or None


def _mic_stream_sounddevice():
    """Deprecated: use arka_mac_mic on Darwin."""
    from arka_mac_mic import mic_stream as _mac_stream

    yield from _mac_stream()


def mic_stream():
    """Yield 16 kHz mono PCM chunks from parec, arecord, or portable backends."""
    if sys.platform == "darwin":
        try:
            from arka_mac_mic import mic_stream as _mac_stream

            yield from _mac_stream()
            return
        except Exception as exc:
            log(f"macOS mic module failed ({exc}), trying fallbacks …")

    dev = mic_device()
    parec = ["parec", "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1"]
    if dev:
        parec[1:1] = ["-d", dev]
    arecord = ["arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw"]
    if dev and dev.startswith("hw:"):
        arecord.extend(["-D", dev])

    for cmd in (parec, arecord):
        label = cmd[0]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            continue
        assert proc.stdout is not None
        log(f"Microphone: {label}" + (f" device={dev}" if dev else " (default)"))
        try:
            while True:
                data = proc.stdout.read(CHUNK)
                if not data:
                    err = proc.stderr.read().decode() if proc.stderr else ""
                    if err.strip():
                        log(f"Mic ended: {err.strip()[:200]}")
                    break
                yield data
        finally:
            proc.terminate()
            proc.wait(timeout=2)
        return

    try:
        yield from _mic_stream_sounddevice()
        return
    except ImportError:
        pass
    except Exception as exc:
        if sys.platform == "darwin":
            raise RuntimeError(f"Microphone failed (sounddevice): {exc}") from exc

    raise RuntimeError(
        "No microphone capture tool found. Linux: install pulseaudio-utils (parec) or alsa-utils (arecord). "
        "macOS: pip install sounddevice in venv-arka. Set ARKA_MIC_DEVICE to device index or name."
    )


def load_media_pcm(path: Path) -> bytes:
    """Decode audio/video file to 16 kHz mono s16le PCM via ffmpeg."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Media file not found: {path}")
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *ffmpeg_thread_args(),
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
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found — install ffmpeg to test from .mp4/.wav files") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"ffmpeg failed: {err or proc.returncode}")
    pcm = proc.stdout
    if len(pcm) < SAMPLE_RATE // 2:
        raise RuntimeError(f"No usable audio in {path.name}")
    return pcm


def pcm_stream(pcm: bytes):
    """Yield fixed-size PCM chunks from an in-memory buffer."""
    for i in range(0, len(pcm), CHUNK):
        yield pcm[i : i + CHUNK]


def chunk_seconds(data: bytes) -> float:
    return len(data) / (SAMPLE_RATE * 2)


def wake_aliases() -> list[str]:
    raw = os.environ.get("AGENT_WAKE_WORDS", WAKE)
    aliases = {WAKE.lower()}
    for part in re.split(r"[,;]+", raw):
        part = part.strip().lower()
        if part:
            aliases.add(part)
            if part.startswith("hey "):
                aliases.add(part[4:].strip())
    aliases.update(
        {
            "hey " + WAKE,
            "ok " + WAKE,
            "a car",
            "our car",
            "archer",
            "marker",
            "arca",
            "he rk",
            "hey rk",
            "he arka",
            "hi arka",
            "hay arka",
            "hey irka",
            "hey erka",
            "hey arka",
        }
    )
    return sorted(aliases, key=len, reverse=True)


def _wake_required() -> bool:
    return os.environ.get("ARKA_WAKE_REQUIRED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def classify_transcript(text: str) -> tuple[str, str]:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from arka_stt_map import classify_phrase

        return classify_phrase(text, WAKE)
    except Exception:
        low = text.lower().strip()
        if contains_wake(low):
            return "wake_only", text.strip()
        return "none", text.strip()


def contains_wake(text: str) -> bool:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from arka_stt_map import normalize_stt, strip_wake

        norm = normalize_stt(text, WAKE)
        if strip_wake(norm, WAKE) != norm:
            return True
        text = norm
    except Exception:
        pass
    low = text.lower().strip().rstrip(".!?")
    if not low:
        return False
    for pat in (
        r"(?i)^he\s+rk\b",
        r"(?i)^hey\s+rk\b",
        r"(?i)^he\s+ah\s+cup\b",
        r"(?i)^he\s+can'?t\b",
        r"(?i)^hey\s+you\s+can'?t\b",
        r"(?i)^your\s+calf\b",
        r"(?i)^yeah\s+your\s+calf\b",
    ):
        if re.search(pat, low):
            return True
    for alias in wake_aliases():
        if not alias:
            continue
        if low == alias:
            return True
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return True
        if alias.startswith("hey ") and low.startswith(alias):
            return True
    return False


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def sarvam_transcribe(pcm: bytes) -> str:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key or len(pcm) < SAMPLE_RATE // 2:
        return ""
    try:
        # Import sibling module without adding pip deps
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from sarvam_stt import transcribe_pcm

        text = transcribe_pcm(pcm, sample_rate=SAMPLE_RATE)
        if text:
            log(f"Sarvam STT: {text!r}")
        return text
    except Exception as exc:
        log(f"Sarvam STT failed ({exc}); falling back to Vosk")
        return ""


def groq_transcribe(pcm: bytes) -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key or len(pcm) < SAMPLE_RATE // 2:
        return ""
    wav_bytes = pcm_to_wav(pcm)
    lang = _speak_lang().split("-")[0].lower() or "en"
    model = (os.environ.get("GROQ_WHISPER_MODEL") or "whisper-large-v3-turbo").strip()
    boundary = f"----Arka{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )

    add_field("model", model)
    add_field("language", lang)
    add_field("response_format", "json")
    add_field("temperature", "0")
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"command.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(wav_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        text = str(data.get("text") or "").strip()
        if text:
            log(f"Groq STT: {text!r}")
        return text
    except Exception as exc:
        log(f"Groq STT failed ({exc}); falling back to Vosk")
        return ""


def assemblyai_transcribe(pcm: bytes) -> str:
    if len(pcm) < SAMPLE_RATE // 2:
        return ""
    try:
        from arka_assemblyai_stt import transcribe_pcm

        text = transcribe_pcm(pcm, sample_rate=SAMPLE_RATE, log=log)
        return text
    except Exception as exc:
        log(f"AssemblyAI STT failed ({exc}); falling back to Vosk")
        return ""


def vosk_transcribe_pcm(model_path: Path, pcm: bytes) -> str:
    from vosk import KaldiRecognizer, Model

    if not pcm:
        return ""
    model = Model(str(model_path))
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(False)
    for i in range(0, len(pcm), CHUNK):
        rec.AcceptWaveform(pcm[i : i + CHUNK])
    return json.loads(rec.FinalResult()).get("text", "").strip()


def transcribe_command(
    model_path: Path,
    pcm: bytes,
    vosk_hint: str = "",
    *,
    aai_session=None,
) -> str:
    backend = _stt_backend()
    if backend == "assemblyai":
        if aai_session is not None:
            text = aai_session.finish()
            if text.strip():
                return text.strip()
        text = assemblyai_transcribe(pcm)
        if text.strip():
            return text.strip()
        log("AssemblyAI unavailable — trying Sarvam")
        text = sarvam_transcribe(pcm)
        if text.strip():
            return text.strip()
        log("Sarvam unavailable — using local Vosk")
    elif backend == "sarvam":
        text = sarvam_transcribe(pcm)
        if text:
            return text
    elif backend == "groq":
        text = groq_transcribe(pcm)
        if text:
            return text
    if vosk_hint.strip():
        return vosk_hint.strip()
    return vosk_transcribe_pcm(model_path, pcm)


def _start_aai_command_session():
    if not _use_assemblyai_commands():
        return None
    try:
        from arka_assemblyai_stt import RealtimeCommandSession

        session = RealtimeCommandSession(log=log)
        if session.start(sample_rate=SAMPLE_RATE):
            return session
        log("AssemblyAI stream unavailable — will try Sarvam or local Vosk")
    except Exception as exc:
        log(f"AssemblyAI stream setup failed ({exc}); will try Sarvam or local Vosk")
    return None


def normalize_stt_transcript(text: str) -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from arka_stt_map import normalize_stt

        fixed = normalize_stt(text)
        if fixed and fixed != text.strip():
            log(f"STT quick-map: {text!r} → {fixed!r}")
        return fixed or text.strip()
    except Exception as exc:
        log(f"STT quick-map skipped ({exc})")
        return text.strip()


def _fish_config() -> Path | None:
    for candidate in (
        Path(__file__).resolve().parent / "config.fish",
        Path.home() / ".config" / "fish" / "config.fish",
    ):
        if candidate.is_file():
            return candidate
    return None


def run_agent(transcript: str) -> None:
    transcript = normalize_stt_transcript(transcript.strip())
    if not transcript:
        return
    log(f"Running: {transcript}")
    env = os.environ.copy()
    fish = shutil.which("fish")
    cfg = _fish_config()
    if fish and cfg:
        env.setdefault("FISH_DIR", str(cfg.parent))
        inner = f"source {shlex.quote(str(cfg))}; agent_hear {shlex.quote(transcript)}"
        subprocess.Popen(
            [fish, "-c", inner],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    root = Path(__file__).resolve().parent
    py = str(VENV_PY if VENV_PY.is_file() else sys.executable)
    env.setdefault("ARKA_HOME", str(root))
    cmd = [py, str(root / "arka_talents.py"), "ask", transcript]
    if os.environ.get("AGENT_SPEAK", "1").strip().lower() not in ("0", "false", "no"):
        cmd.append("--speak")
    subprocess.Popen(cmd, env=env, start_new_session=True)


def _try_run_transcript(text: str, *, last_phrase: list[str], last_at: list[float], tick: float) -> bool:
    """Classify and run wake+command or direct command. Returns True if handled."""
    text = text.strip()
    if not text:
        return False
    kind, phrase = classify_transcript(text)
    if kind == "none":
        return False
    if kind == "wake_only":
        return False
    if kind == "direct" and _wake_required():
        return False
    if phrase == last_phrase[0] and tick - last_at[0] < 3.0:
        return True
    label = "Wake+command" if kind == "wake_cmd" else "Direct command"
    log(f"{label}: {phrase!r}")
    run_agent(phrase)
    last_phrase[0] = phrase
    last_at[0] = tick
    return True


def listen_loop(model_path: Path, stream=None, *, realtime: bool = True) -> list[dict]:
    from vosk import KaldiRecognizer, Model

    model = Model(str(model_path))
    wake_rec = KaldiRecognizer(model, SAMPLE_RATE)
    wake_rec.SetWords(False)

    preset = resolve_model_preset()
    if stream is None:
        stream = mic_stream()
        stop_hint = (
            "Control+C to stop, or 'arka listen stop' in another tab"
            if sys.platform == "darwin"
            else "Ctrl+C to stop"
        )
        log(
            f"Listening for '{WAKE}' … model={model_path.name} preset={preset} "
            f"command_stt={_stt_chain_label()} lang={_speak_lang()} ({stop_hint})"
        )
        log(f"Say: hey {WAKE} … then your command (pause briefly after the wake phrase)")
    else:
        log(
            f"Replaying audio for '{WAKE}' … model={model_path.name} preset={preset} "
            f"command_stt={_stt_chain_label()} lang={_speak_lang()}"
        )

    command_mode = False
    command_rec = None
    command_pcm = bytearray()
    command_aai = None
    command_deadline = 0.0
    wake_cooldown_until = 0.0
    command_seconds = float(os.environ.get("ARKA_COMMAND_SECONDS", "10"))
    audio_clock = 0.0
    results: list[dict] = []
    wake_text = ""
    last_run_phrase = [""]
    last_run_at = [0.0]

    def now() -> float:
        return time.time() if realtime else audio_clock

    for data in stream:
        if not realtime:
            audio_clock += chunk_seconds(data)
        tick = now()
        if command_mode:
            assert command_rec is not None
            command_pcm.extend(data)
            if command_aai is not None:
                command_aai.feed(data)
            vosk_hint = ""
            if command_rec.AcceptWaveform(data):
                vosk_hint = json.loads(command_rec.Result()).get("text", "")
            elif tick >= command_deadline:
                vosk_hint = json.loads(command_rec.PartialResult()).get("partial", "")
            else:
                partial = json.loads(command_rec.PartialResult()).get("partial", "")
                if partial.strip():
                    debug_hear("cmd", partial, partial=True)
                continue

            text = transcribe_command(
                model_path, bytes(command_pcm), vosk_hint, aai_session=command_aai
            )
            debug_hear("cmd", text or vosk_hint)
            final_text = text or vosk_hint
            if final_text:
                entry = {"wake": wake_text, "command": final_text.strip()}
                results.append(entry)
                if realtime:
                    run_agent(final_text)
                else:
                    log(f"Command transcript: {final_text!r}")
            command_mode = False
            command_rec = None
            command_pcm = bytearray()
            command_aai = None
            wake_cooldown_until = tick + 1.0
            if realtime:
                log(f"Listening for '{WAKE}' …")
            continue

        if tick < wake_cooldown_until:
            continue

        if wake_rec.AcceptWaveform(data):
            text = json.loads(wake_rec.Result()).get("text", "")
            if text.strip():
                debug_hear("wake", text)
            if _try_run_transcript(text, last_phrase=last_run_phrase, last_at=last_run_at, tick=tick):
                wake_cooldown_until = tick + 2.0
                wake_rec = KaldiRecognizer(model, SAMPLE_RATE)
                continue
            if contains_wake(text):
                wake_text = text.strip()
                log(f"Wake detected: {text!r} — speak your command …")
                command_mode = True
                command_rec = KaldiRecognizer(model, SAMPLE_RATE)
                command_pcm = bytearray()
                command_aai = _start_aai_command_session()
                command_deadline = tick + command_seconds
                wake_rec = KaldiRecognizer(model, SAMPLE_RATE)
        else:
            partial = json.loads(wake_rec.PartialResult()).get("partial", "")
            if partial.strip():
                debug_hear("wake", partial, partial=True)
            if _try_run_transcript(partial, last_phrase=last_run_phrase, last_at=last_run_at, tick=tick):
                wake_cooldown_until = tick + 2.0
                wake_rec = KaldiRecognizer(model, SAMPLE_RATE)
            elif contains_wake(partial):
                wake_text = partial.strip()
                log(f"Wake detected: {partial!r} — speak your command …")
                command_mode = True
                command_rec = KaldiRecognizer(model, SAMPLE_RATE)
                command_pcm = bytearray()
                command_aai = _start_aai_command_session()
                command_deadline = tick + command_seconds
                wake_rec = KaldiRecognizer(model, SAMPLE_RATE)

    if command_mode and command_pcm:
        assert command_rec is not None
        vosk_hint = json.loads(command_rec.FinalResult()).get("text", "")
        text = transcribe_command(
            model_path, bytes(command_pcm), vosk_hint, aai_session=command_aai
        )
        final_text = text or vosk_hint
        if final_text:
            entry = {"wake": wake_text, "command": final_text.strip()}
            results.append(entry)
            log(f"Command transcript (EOF): {final_text!r}")
            if realtime:
                run_agent(final_text)

    return results


def _listen_engine() -> str:
    """auto | assemblyai | vosk — which engine drives wake+command detection."""
    mode = (os.environ.get("ARKA_LISTEN_ENGINE") or "auto").strip().lower()
    if mode in ("assemblyai", "aai"):
        return "assemblyai"
    if mode == "vosk":
        return "vosk"
    # auto: use AssemblyAI streaming for the whole pipeline when a key is present
    if _stt_backend() == "assemblyai" and os.environ.get("ASSEMBLYAI_API_KEY", "").strip():
        return "assemblyai"
    return "vosk"


def listen_loop_streaming() -> bool:
    """Continuous AssemblyAI streaming listener: accurate wake + command in one pass.

    Returns True if the session ran (caller is done), False if AssemblyAI could
    not start at all and the caller should fall back to the Vosk listen loop.
    """
    try:
        from assemblyai.streaming.v3 import (
            StreamingClient,
            StreamingClientOptions,
            StreamingEvents,
            StreamingParameters,
            TurnEvent,
        )
    except ImportError as exc:
        log(f"AssemblyAI SDK missing ({exc}); using local Vosk")
        return False

    import queue as _queue
    import threading

    try:
        from arka_assemblyai_stt import (
            _keyterms,
            _realtime_speech_model,
            api_key,
            streaming_host,
        )
    except ImportError as exc:
        log(f"AssemblyAI helper missing ({exc}); using local Vosk")
        return False

    key = api_key()
    if not key:
        return False

    turn_q: "_queue.Queue[str]" = _queue.Queue()
    state: dict[str, object] = {"error": None}

    def on_turn(_client, event: "TurnEvent") -> None:
        text = (event.transcript or "").strip()
        if not text:
            return
        if event.end_of_turn:
            turn_q.put(text)
        else:
            debug_hear("wake", text, partial=True)

    def on_error(_client, event) -> None:
        state["error"] = str(getattr(event, "error", event) or "AssemblyAI stream error")
        turn_q.put("")  # unblock the consumer

    client = StreamingClient(
        StreamingClientOptions(api_key=key, api_host=streaming_host())
    )
    client.on(StreamingEvents.Turn, on_turn)
    client.on(StreamingEvents.Error, on_error)

    params = StreamingParameters(
        sample_rate=SAMPLE_RATE,
        speech_model=_realtime_speech_model(),
    )
    terms = _keyterms()
    if terms:
        params.keyterms_prompt = terms

    try:
        client.connect(params)
    except Exception as exc:
        log(f"AssemblyAI streaming connect failed ({exc}); using local Vosk")
        return False

    # connect() dispatches auth/HTTP rejections via on_error instead of raising.
    time.sleep(0.3)
    if state["error"]:
        log(f"AssemblyAI streaming rejected ({state['error']}); using local Vosk")
        try:
            client.disconnect(terminate=False)
        except Exception:
            pass
        return False

    stop_hint = (
        "Control+C to stop, or 'arka listen stop' in another tab"
        if sys.platform == "darwin"
        else "Ctrl+C to stop"
    )
    log(
        f"Listening for '{WAKE}' … engine=AssemblyAI streaming "
        f"model={_realtime_speech_model()} lang={_speak_lang()} ({stop_hint})"
    )
    log(f"Say: hey {WAKE} … then your command in one breath")

    feeder_stop = threading.Event()

    def feed_mic() -> None:
        try:
            for chunk in mic_stream():
                if feeder_stop.is_set():
                    break
                client.stream(chunk)
        except Exception as exc:
            state["error"] = f"mic: {exc}"
            turn_q.put("")

    feeder = threading.Thread(target=feed_mic, daemon=True)
    feeder.start()

    last_run_phrase = ""
    last_run_at = 0.0
    try:
        while True:
            transcript = turn_q.get()
            if state["error"]:
                log(f"AssemblyAI streaming error ({state['error']}); falling back to local Vosk")
                return False
            if not transcript:
                continue
            debug_hear("wake", transcript)
            transcript = normalize_stt_transcript(transcript)
            kind, phrase = classify_transcript(transcript)
            if kind in ("none", "wake_only"):
                continue
            if kind == "direct" and _wake_required():
                continue
            tick = time.time()
            if phrase == last_run_phrase and tick - last_run_at < 3.0:
                continue
            label = "Wake+command" if kind == "wake_cmd" else "Direct command"
            log(f"{label}: {phrase!r}")
            run_agent(phrase)
            last_run_phrase = phrase
            last_run_at = tick
    finally:
        feeder_stop.set()
        try:
            client.disconnect(terminate=True)
        except Exception:
            pass
    return True


def normalize_words(text: str) -> list[str]:
    text = re.sub(r"[^\w\s']", " ", text.lower())
    return [w for w in text.split() if w]


def word_accuracy(expected: str, actual: str) -> float:
    exp = normalize_words(expected)
    act = normalize_words(actual)
    if not exp:
        return 0.0
    if not act:
        return 0.0
    matches = sum(1 for w in exp if w in act)
    return round(100.0 * matches / len(exp), 1)


def fish_agent_route(transcript: str) -> str:
    cfg = _fish_config()
    if not cfg:
        return ""
    fish = shutil.which("fish")
    if not fish:
        return ""
    cfg_q = shlex.quote(str(cfg))
    cmd_q = shlex.quote(transcript)
    try:
        proc = subprocess.run(
            [fish, "-c", f"source {cfg_q}; agent_route {cmd_q}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("Action:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def fish_strip_wake(transcript: str) -> str:
    cfg = _fish_config()
    fish = shutil.which("fish")
    if not cfg or not fish:
        return transcript.strip()
    cfg_q = shlex.quote(str(cfg))
    cmd_q = shlex.quote(transcript)
    try:
        proc = subprocess.run(
            [
                fish,
                "-c",
                (
                    f"source {cfg_q}; "
                    f"set -l t (_agent_stt_quick_map {cmd_q}); "
                    f"_agent_strip_wake \"$t\""
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.stdout.strip()
    except Exception:
        return transcript.strip()


def transcribe_full_file(model_path: Path, pcm: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    backend = _stt_backend()
    if backend == "assemblyai" and os.environ.get("ASSEMBLYAI_API_KEY", "").strip():
        try:
            from arka_assemblyai_stt import transcribe_pcm

            out["assemblyai"] = transcribe_pcm(pcm, sample_rate=SAMPLE_RATE, log=log)
        except Exception as exc:
            out["assemblyai"] = f"(error: {exc})"
        if not (out.get("assemblyai") or "").strip() and os.environ.get("SARVAM_API_KEY", "").strip():
            out["sarvam"] = sarvam_transcribe(pcm)
    elif backend == "sarvam" and os.environ.get("SARVAM_API_KEY", "").strip():
        out["sarvam"] = sarvam_transcribe(pcm)
    elif backend == "groq" and os.environ.get("GROQ_API_KEY", "").strip():
        out["groq"] = groq_transcribe(pcm)
    try:
        out["vosk"] = vosk_transcribe_pcm(model_path, pcm)
    except Exception as exc:
        out["vosk"] = f"(error: {exc})"
    return out


def write_pid() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def remove_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def print_model_info() -> None:
    preset = resolve_model_preset()
    folder, url = MODEL_CATALOG[preset]
    print(f"preset={preset}")
    print(f"model_dir={resolve_model_dir()}")
    print(f"download={url}")
    print(f"listen_engine={_listen_engine()}")
    print(f"command_stt={_stt_chain_label()}")
    print(f"lang={_speak_lang()}")
    print("available_presets:", ", ".join(MODEL_CATALOG))


def reexec_in_venv() -> None:
    py = ensure_venv_deps()
    if Path(sys.executable).resolve() == Path(py).resolve():
        return
    os.execv(str(py), [str(py), *sys.argv])


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        ensure_venv_deps()
        ensure_model()
        log("Dependencies OK")
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "--models":
        print_model_info()
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "--list-mics":
        from arka_mac_mic import list_input_devices, permission_hint

        for d in list_input_devices():
            print(f"[{d['index']}] {d['name']}")
        if sys.platform == "darwin":
            print(f"\n{permission_hint()}")
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "--mic-test":
        reexec_in_venv()
        from arka_mac_mic import mic_selftest

        return mic_selftest()

    if "--debug" in sys.argv:
        set_debug(True)

    reexec_in_venv()

    write_pid()

    def _stop(_signum, _frame):
        log("Stopping listener")
        remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        if _listen_engine() == "assemblyai":
            if listen_loop_streaming():
                return 0
            log("Falling back to local Vosk wake detection")
        model_path = ensure_model()
        listen_loop(model_path)
    finally:
        remove_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
