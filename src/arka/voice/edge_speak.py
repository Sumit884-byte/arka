#!/usr/bin/env python3
"""Natural neural TTS via Microsoft Edge voices (edge-tts). Free, fast, human-like."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VENV_PY = Path.home() / ".config" / "fish" / "venv-tts" / "bin" / "python3"


def _tts_python() -> Path:
    arka_home = Path(os.environ.get("INSTALL_HOME", Path.home() / "dev/arka")).expanduser()
    for candidate in (
        arka_home / "venv-arka/bin/python3",
        Path.home() / "dev/arka/venv-arka/bin/python3",
        Path.home() / ".config/fish/venv-arka/bin/python3",
        VENV_PY,
        Path(sys.executable),
    ):
        if candidate.is_file():
            return candidate
    return VENV_PY

# Curated natural-sounding neural voices per language
VOICES: dict[str, dict[str, str]] = {
    "en-IN": {
        "label": "English (India)",
        "female": "en-IN-NeerjaNeural",
        "male": "en-IN-PrabhatNeural",
        "default": "en-IN-NeerjaNeural",
    },
    "hi-IN": {
        "label": "Hindi",
        "female": "hi-IN-SwaraNeural",
        "male": "hi-IN-MadhurNeural",
        "default": "hi-IN-SwaraNeural",
    },
    "bn-IN": {
        "label": "Bengali",
        "female": "bn-IN-TanishaaNeural",
        "male": "bn-IN-BashkarNeural",
        "default": "bn-IN-TanishaaNeural",
    },
    "ta-IN": {
        "label": "Tamil",
        "female": "ta-IN-PallaviNeural",
        "male": "ta-IN-ValluvarNeural",
        "default": "ta-IN-PallaviNeural",
    },
    "te-IN": {
        "label": "Telugu",
        "female": "te-IN-ShrutiNeural",
        "male": "te-IN-MohanNeural",
        "default": "te-IN-ShrutiNeural",
    },
    "mr-IN": {
        "label": "Marathi",
        "female": "mr-IN-AarohiNeural",
        "male": "mr-IN-ManoharNeural",
        "default": "mr-IN-AarohiNeural",
    },
    "gu-IN": {
        "label": "Gujarati",
        "female": "gu-IN-DhwaniNeural",
        "male": "gu-IN-NiranjanNeural",
        "default": "gu-IN-DhwaniNeural",
    },
    "kn-IN": {
        "label": "Kannada",
        "female": "kn-IN-SapnaNeural",
        "male": "kn-IN-GaganNeural",
        "default": "kn-IN-SapnaNeural",
    },
    "ml-IN": {
        "label": "Malayalam",
        "female": "ml-IN-SobhanaNeural",
        "male": "ml-IN-MidhunNeural",
        "default": "ml-IN-SobhanaNeural",
    },
    "pa-IN": {
        "label": "Punjabi",
        "female": "pa-IN-GurpreetNeural",
        "male": "pa-IN-HarpreetNeural",
        "default": "pa-IN-GurpreetNeural",
    },
    "as-IN": {
        "label": "Assamese",
        "female": "as-IN-YashicaNeural",
        "male": "as-IN-PriyomNeural",
        "default": "as-IN-YashicaNeural",
    },
    "ur-IN": {
        "label": "Urdu",
        "female": "ur-IN-GulNeural",
        "male": "ur-IN-AsadNeural",
        "default": "ur-IN-GulNeural",
    },
}

LANG_ALIASES = {
    "en": "en-IN",
    "hi": "hi-IN",
    "bn": "bn-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "pa": "pa-IN",
    "as": "as-IN",
    "ur": "ur-IN",
}


def resolve_lang(code: str | None = None) -> str:
    lang = (code or os.environ.get("SPEAK_LANG") or "en-IN").strip()
    if lang in VOICES:
        return lang
    return LANG_ALIASES.get(lang.lower(), "en-IN")


def resolve_voice(lang: str | None = None, voice: str | None = None) -> str:
    explicit = (voice or os.environ.get("SPEAK_VOICE") or "").strip()
    if explicit:
        return explicit
    code = resolve_lang(lang)
    meta = VOICES.get(code, VOICES["en-IN"])
    gender = os.environ.get("SPEAK_GENDER", "female").strip().lower()
    if gender in ("male", "m"):
        return meta["male"]
    if gender in ("female", "f"):
        return meta["female"]
    return meta["default"]


def play_audio(path: Path) -> None:
    for cmd in (
        ["mpv", "--no-video", str(path)],
        ["afplay", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
        ["paplay", str(path)],
        ["aplay", str(path)],
    ):
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise RuntimeError("No audio player found (install mpv or ffmpeg)")


async def _synthesize(text: str, voice: str, rate: str, pitch: str, out: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(out))


DEFAULT_CHUNK = 2000


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


def synthesize_to_file(text: str, output: Path, *, voice: str | None = None) -> Path:
    """Synthesize narration to an MP3 file using Arka voice settings (edge-tts)."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("empty text")

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    voice_id = resolve_voice(voice=voice)
    rate = os.environ.get("SPEAK_RATE", "-5%")
    pitch = os.environ.get("SPEAK_PITCH", "+0Hz")
    max_len = int(os.environ.get("AGENT_SPEAK_MAX", str(DEFAULT_CHUNK)))
    max_len = min(max_len, 2500)
    chunks = chunk_text(text, max_len)

    if len(chunks) == 1:
        asyncio.run(_synthesize(chunks[0], voice_id, rate, pitch, out))
        return out

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg required to merge long narration")

    chunk_paths: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="arka-tts-") as tmp:
        tmpdir = Path(tmp)
        for i, chunk in enumerate(chunks):
            mp3 = tmpdir / f"chunk_{i:03d}.mp3"
            asyncio.run(_synthesize(chunk, voice_id, rate, pitch, mp3))
            chunk_paths.append(mp3)
        list_file = tmpdir / "concat.txt"
        list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in chunk_paths), encoding="utf-8")
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg concat failed").strip())
    return out


def speak(text: str, lang: str | None = None, voice: str | None = None) -> None:
    text = " ".join(text.split())
    if not text:
        return

    max_len = int(os.environ.get("AGENT_SPEAK_MAX", str(DEFAULT_CHUNK)))
    max_len = min(max_len, 2500)
    voice_id = resolve_voice(lang, voice)
    rate = os.environ.get("SPEAK_RATE", "-5%")
    pitch = os.environ.get("SPEAK_PITCH", "+0Hz")

    for chunk in chunk_text(text, max_len):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3 = Path(tmp.name)
        try:
            asyncio.run(_synthesize(chunk, voice_id, rate, pitch, mp3))
            play_audio(mp3)
        finally:
            mp3.unlink(missing_ok=True)


def ensure_venv() -> None:
    py = _tts_python()
    if not py.parent.parent.exists():
        import venv

        venv.create(py.parent.parent, with_pip=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "edge-tts"], check=True)


def print_voices(lang_filter: str | None = None) -> None:
    cur_lang = resolve_lang()
    cur_voice = resolve_voice()
    if lang_filter:
        codes = [resolve_lang(lang_filter)]
    else:
        codes = list(VOICES.keys())

    print(f"{'Language':<22} {'Female':<28} {'Male':<28}")
    print("-" * 80)
    for code in codes:
        meta = VOICES[code]
        mark = " ←" if code == cur_lang else ""
        print(f"{meta['label']:<22} {meta['female']:<28} {meta['male']:<28}{mark}")
    print(f"\nCurrent voice: {cur_voice}")
    print("Set: arka speak-voice hi-IN-SwaraNeural")
    print("Or:  ARKA_SPEAK_GENDER=male   ARKA_SPEAK_RATE=-5%")


def main() -> int:
    venv_py = _tts_python()
    if venv_py.is_file() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), __file__, *sys.argv[1:]])

    parser = argparse.ArgumentParser(description="Natural neural TTS for Arka")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("setup")
    sub.add_parser("voices")
    p_voices = sub.add_parser("list")
    p_voices.add_argument("--lang", default="")

    p_speak = sub.add_parser("speak")
    p_speak.add_argument("text", nargs="?", default="")
    p_speak.add_argument("--lang", default="")
    p_speak.add_argument("--voice", default="")

    p_resolve = sub.add_parser("resolve-voice")
    p_resolve.add_argument("lang", nargs="?", default="")

    args = parser.parse_args()

    if args.cmd == "setup":
        ensure_venv()
        print("edge-tts ready.", file=sys.stderr)
        return 0
    if args.cmd in ("voices", "list"):
        print_voices(getattr(args, "lang", "") or None)
        return 0
    if args.cmd == "resolve-voice":
        print(resolve_voice(args.lang or None))
        return 0
    if args.cmd == "speak":
        text = (args.text or sys.stdin.read()).strip()
        if not text:
            return 1
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            ensure_venv()
            os.execv(str(_tts_python()), [str(_tts_python()), __file__, *sys.argv])
        try:
            speak(text, args.lang or None, args.voice or None)
        except Exception as exc:
            print(f"edge_speak: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
