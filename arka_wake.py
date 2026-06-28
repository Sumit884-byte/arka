#!/usr/bin/env python3
"""Continuous wake-word listener for the Arka fish agent."""

from __future__ import annotations

import io
import json
import os
import re
import shlex
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
WAKE = os.environ.get("AGENT_NAME", "arka").strip().lower() or "arka"
PID_FILE = Path.home() / ".cache" / "fish-agent" / "arka_listen.pid"
LOG_PREFIX = "[arka]"
VENV_PY = Path.home() / ".config" / "fish" / "venv-arka" / "bin" / "python3"

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
    if mode in ("groq", "vosk", "sarvam"):
        return mode
    if os.environ.get("SARVAM_API_KEY", "").strip():
        return "sarvam"
    if os.environ.get("GROQ_API_KEY", "").strip():
        return "groq"
    return "vosk"


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
    subprocess.run([str(py), "-m", "pip", "install", "-q", "vosk"], check=True)
    return py


def mic_device() -> str | None:
    dev = (os.environ.get("ARKA_MIC_DEVICE") or os.environ.get("PULSE_SOURCE") or "").strip()
    return dev or None


def mic_stream():
    """Yield 16 kHz mono PCM chunks from parec or arecord."""
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
    raise RuntimeError(
        "No microphone capture tool found. Install pulseaudio-utils (parec) or alsa-utils (arecord). "
        "Set ARKA_MIC_DEVICE to your mic name from: pactl list sources short"
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


def transcribe_command(model_path: Path, pcm: bytes, vosk_hint: str = "") -> str:
    backend = _stt_backend()
    if backend == "sarvam":
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


def run_agent(transcript: str) -> None:
    transcript = normalize_stt_transcript(transcript.strip())
    if not transcript:
        return
    log(f"Running: {transcript}")
    env = os.environ.copy()
    fish_cmd = f"agent_hear {shlex.quote(transcript)}"
    subprocess.Popen(
        ["fish", "-ic", fish_cmd],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


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

    stt = _stt_backend()
    preset = resolve_model_preset()
    if stream is None:
        stream = mic_stream()
        log(
            f"Listening for '{WAKE}' … model={model_path.name} preset={preset} "
            f"command_stt={stt} lang={_speak_lang()} (Ctrl+C to stop)"
        )
    else:
        log(
            f"Replaying audio for '{WAKE}' … model={model_path.name} preset={preset} "
            f"command_stt={stt} lang={_speak_lang()}"
        )

    command_mode = False
    command_rec = None
    command_pcm = bytearray()
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

            text = transcribe_command(model_path, bytes(command_pcm), vosk_hint)
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
                command_deadline = tick + command_seconds
                wake_rec = KaldiRecognizer(model, SAMPLE_RATE)

    if command_mode and command_pcm:
        assert command_rec is not None
        vosk_hint = json.loads(command_rec.FinalResult()).get("text", "")
        text = transcribe_command(model_path, bytes(command_pcm), vosk_hint)
        final_text = text or vosk_hint
        if final_text:
            entry = {"wake": wake_text, "command": final_text.strip()}
            results.append(entry)
            log(f"Command transcript (EOF): {final_text!r}")
            if realtime:
                run_agent(final_text)

    return results


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
    try:
        proc = subprocess.run(
            ["fish", "-c", f"source ~/.config/fish/config.fish; agent_route {shlex.quote(transcript)}"],
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
    try:
        proc = subprocess.run(
            [
                "fish",
                "-c",
                (
                    f"source ~/.config/fish/config.fish; "
                    f"set -l t (_agent_stt_quick_map {shlex.quote(transcript)}); "
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
    if backend == "sarvam" and os.environ.get("SARVAM_API_KEY", "").strip():
        out["sarvam"] = sarvam_transcribe(pcm)
    elif backend == "groq" and os.environ.get("GROQ_API_KEY", "").strip():
        out["groq"] = groq_transcribe(pcm)
    try:
        out["vosk"] = vosk_transcribe_pcm(model_path, pcm)
    except Exception as exc:
        out["vosk"] = f"(error: {exc})"
    return out


def test_media_file(
    media_path: Path,
    *,
    expected: str = "",
    run_agent_cmd: bool = False,
    full: bool = False,
    no_wake: bool = False,
) -> int:
    set_debug(True)
    media_path = media_path.expanduser().resolve()
    pcm = load_media_pcm(media_path)
    duration = len(pcm) / (SAMPLE_RATE * 2)
    model_path = ensure_model()
    stt = _stt_backend()

    print(f"file={media_path}")
    print(f"duration={duration:.2f}s pcm_bytes={len(pcm)} stt={stt}")
    print(f"wake_words={', '.join(wake_aliases()[:6])}…")
    print("")

    if full or no_wake:
        texts = transcribe_full_file(model_path, pcm)
        print("=== Full-file transcription ===")
        for backend, text in texts.items():
            if text.startswith("(error"):
                print(f"{backend}: {text}")
                continue
            print(f"{backend}: {text!r}")
            if expected:
                print(f"  accuracy vs expected: {word_accuracy(expected, text)}%")
            stripped = fish_strip_wake(text) or text
            route = fish_agent_route(stripped)
            if route:
                print(f"  route: {route}")
        print("")

    if no_wake:
        best = ""
        for text in transcribe_full_file(model_path, pcm).values():
            if text and not text.startswith("(error"):
                best = text
        if best and run_agent_cmd:
            run_agent(best)
        return 0 if best else 1

    detections = listen_loop(model_path, pcm_stream(pcm), realtime=False)
    print(f"=== Wake+command detections: {len(detections)} ===")
    if not detections:
        print("No wake word detected in this clip.")
        if not full:
            texts = transcribe_full_file(model_path, pcm)
            print("")
            print("Full-file fallback (no wake gate):")
            for backend, text in texts.items():
                print(f"  {backend}: {text!r}")
                if expected:
                    print(f"    accuracy: {word_accuracy(expected, text)}%")
        return 1

    ok = 0
    for i, hit in enumerate(detections, 1):
        wake = hit.get("wake", "")
        command = hit.get("command", "")
        full_phrase = f"{wake} {command}".strip()
        stripped = fish_strip_wake(full_phrase) or fish_strip_wake(command) or command
        route = fish_agent_route(stripped or full_phrase)

        print(f"[{i}] wake={wake!r}")
        print(f"    command={command!r}")
        print(f"    stripped={stripped!r}")
        if route:
            print(f"    route={route}")
        if expected:
            acc_cmd = word_accuracy(expected, command)
            acc_strip = word_accuracy(expected, stripped)
            print(f"    accuracy(command)={acc_cmd}%  accuracy(stripped)={acc_strip}%")
            if acc_strip >= 70.0 or acc_cmd >= 70.0:
                ok += 1

        if run_agent_cmd and command:
            run_agent(command)

    if expected:
        print("")
        print(f"Summary: {ok}/{len(detections)} detection(s) ≥70% word match vs {expected!r}")
    return 0 if detections else 1


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
    print(f"command_stt={_stt_backend()}")
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

    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        reexec_in_venv()
        args = sys.argv[2:]
        if not args or args[0].startswith("-"):
            print("Usage: arka_wake.py --file <audio|video> [--expected phrase] [--full] [--no-wake] [--run]")
            return 1
        media = Path(args[0])
        expected = ""
        run_agent_cmd = False
        full = False
        no_wake = False
        i = 1
        while i < len(args):
            if args[i] == "--expected" and i + 1 < len(args):
                expected = args[i + 1]
                i += 2
            elif args[i] == "--run":
                run_agent_cmd = True
                i += 1
            elif args[i] == "--full":
                full = True
                i += 1
            elif args[i] == "--no-wake":
                no_wake = True
                i += 1
            else:
                print(f"Unknown option: {args[i]}")
                return 1
        return test_media_file(
            media,
            expected=expected,
            run_agent_cmd=run_agent_cmd,
            full=full,
            no_wake=no_wake,
        )

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
        model_path = ensure_model()
        listen_loop(model_path)
    finally:
        remove_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
