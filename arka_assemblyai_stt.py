#!/usr/bin/env python3
"""AssemblyAI STT for Arka — realtime command capture with local Vosk fallback."""

from __future__ import annotations

import io
import os
import tempfile
import wave
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]


def _log(msg: str, log: LogFn | None = None) -> None:
    if log:
        log(msg)


def api_key() -> str:
    return (os.environ.get("ASSEMBLYAI_API_KEY") or "").strip()


def enabled() -> bool:
    return bool(api_key())


def rest_base_url() -> str:
    if (os.environ.get("ARKA_ASSEMBLYAI_REGION") or "us").strip().lower() == "eu":
        return "https://api.eu.assemblyai.com"
    return "https://api.assemblyai.com"


def streaming_host() -> str:
    custom = (os.environ.get("ARKA_ASSEMBLYAI_STREAMING_HOST") or "").strip()
    if custom:
        return custom
    region = (os.environ.get("ARKA_ASSEMBLYAI_REGION") or "us").strip().lower()
    if region == "eu":
        return "streaming.eu.assemblyai.com"
    if region == "us-pinned":
        return "streaming.us.assemblyai.com"
    return "streaming.assemblyai.com"


def _speech_models_prerecorded() -> list[str]:
    raw = (os.environ.get("ARKA_ASSEMBLYAI_SPEECH_MODELS") or "universal-3-pro,universal-2").strip()
    return [m.strip() for m in raw.split(",") if m.strip()]


def _realtime_speech_model():
    from assemblyai.streaming.v3.models import SpeechModel

    name = (os.environ.get("ARKA_ASSEMBLYAI_REALTIME_MODEL") or "universal-3-5-pro").strip()
    for candidate in SpeechModel:
        if candidate.value == name:
            return candidate
    return SpeechModel.universal_3_5_pro


def _keyterms() -> list[str] | None:
    raw = (os.environ.get("ARKA_ASSEMBLYAI_KEYTERMS") or os.environ.get("AGENT_NAME") or "").strip()
    if not raw:
        return None
    terms = [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]
    wake = (os.environ.get("AGENT_NAME") or "arka").strip()
    if wake and wake.lower() not in {t.lower() for t in terms}:
        terms.insert(0, wake)
    return terms[:100] or None


def pcm_to_wav(pcm: bytes, *, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class RealtimeCommandSession:
    """Stream mic PCM to AssemblyAI during a wake-word command window."""

    def __init__(self, *, log: LogFn | None = None) -> None:
        self._log = log
        self._client = None
        self._final = ""
        self._partial = ""
        self._error: str | None = None
        self._started = False

    @property
    def ok(self) -> bool:
        return self._started and not self._error

    def start(self, *, sample_rate: int = 16000) -> bool:
        key = api_key()
        if not key:
            return False
        try:
            from assemblyai.streaming.v3 import (
                StreamingClient,
                StreamingClientOptions,
                StreamingEvents,
                StreamingParameters,
                TurnEvent,
            )
        except ImportError as exc:
            _log(f"AssemblyAI SDK missing ({exc})", self._log)
            return False

        self._final = ""
        self._partial = ""
        self._error = None

        client = StreamingClient(
            StreamingClientOptions(api_key=key, api_host=streaming_host())
        )

        def on_turn(_client, event: TurnEvent) -> None:
            text = (event.transcript or "").strip()
            if not text:
                return
            if event.end_of_turn:
                self._final = text
            else:
                self._partial = text

        def on_error(_client, event) -> None:
            self._error = str(getattr(event, "error", event) or "AssemblyAI stream error")

        client.on(StreamingEvents.Turn, on_turn)
        client.on(StreamingEvents.Error, on_error)

        params = StreamingParameters(
            sample_rate=sample_rate,
            speech_model=_realtime_speech_model(),
        )
        terms = _keyterms()
        if terms:
            params.keyterms_prompt = terms

        try:
            client.connect(params)
        except Exception as exc:
            _log(f"AssemblyAI connect failed ({exc})", self._log)
            return False

        self._client = client
        self._started = True
        return True

    def feed(self, chunk: bytes) -> None:
        if self._client and not self._error and chunk:
            self._client.stream(chunk)

    def finish(self) -> str:
        if not self._client:
            return ""
        try:
            self._client.force_endpoint()
            self._client.disconnect(terminate=True)
        except Exception as exc:
            _log(f"AssemblyAI disconnect ({exc})", self._log)
        self._client = None
        self._started = False
        if self._error:
            return ""
        text = (self._final or self._partial).strip()
        if text:
            _log(f"AssemblyAI STT: {text!r}", self._log)
        return text


def transcribe_pcm(pcm: bytes, *, sample_rate: int = 16000, log: LogFn | None = None) -> str:
    """Pre-recorded fallback — upload WAV and poll (used when streaming fails)."""
    key = api_key()
    if not key or len(pcm) < sample_rate // 2:
        return ""
    try:
        import assemblyai as aai
    except ImportError as exc:
        _log(f"AssemblyAI SDK missing ({exc})", log)
        return ""

    aai.settings.api_key = key
    aai.settings.base_url = rest_base_url()

    wav_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(pcm_to_wav(pcm, sample_rate=sample_rate))
            wav_path = Path(tmp.name)

        config = aai.TranscriptionConfig(speech_models=_speech_models_prerecorded())
        transcript = aai.Transcriber(config=config).transcribe(str(wav_path))
        if transcript.status == aai.TranscriptStatus.error:
            raise RuntimeError(transcript.error or "transcription error")
        text = (transcript.text or "").strip()
        if text:
            _log(f"AssemblyAI STT (batch): {text!r}", log)
        return text
    except Exception as exc:
        _log(f"AssemblyAI batch STT failed ({exc})", log)
        return ""
    finally:
        if wav_path and wav_path.is_file():
            wav_path.unlink(missing_ok=True)
