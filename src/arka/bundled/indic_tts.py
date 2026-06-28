#!/usr/bin/env python3
"""Indic Parler-TTS (local) + optional Sarvam routing helpers."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

CACHE = Path.home() / ".cache" / "fish-agent"
SOCK_PATH = CACHE / "parler.sock"
PID_PATH = CACHE / "parler.pid"
VENV_PY = Path.home() / ".config" / "fish" / "venv-tts" / "bin" / "python3"
MODEL_ID = os.environ.get("PARLER_MODEL", "ai4bharat/indic-parler-tts")

# lang code -> voice metadata (Indic Parler-TTS recommended speakers)
LANGS: dict[str, dict[str, str]] = {
    "en-IN": {
        "label": "English (India)",
        "speaker": "Mary",
        "desc": "Mary speaks with a clear Indian English accent, warm and natural, at a moderate pace. The recording is very high quality with very clear audio.",
    },
    "hi-IN": {
        "label": "Hindi",
        "speaker": "Divya",
        "desc": "Divya speaks with a slightly expressive and animated tone, moderate speed and pitch. The recording is of very high quality, with the speaker's voice sounding clear and very close up.",
    },
    "bn-IN": {
        "label": "Bengali",
        "speaker": "Aditi",
        "desc": "Aditi speaks with a clear Bengali voice, slightly expressive, moderate pace, very clear audio.",
    },
    "ta-IN": {
        "label": "Tamil",
        "speaker": "Jaya",
        "desc": "Jaya speaks with a clear Tamil voice, moderate speed and pitch, very clear audio.",
    },
    "te-IN": {
        "label": "Telugu",
        "speaker": "Lalitha",
        "desc": "Lalitha speaks with a clear Telugu voice, moderate pace, very clear audio.",
    },
    "mr-IN": {
        "label": "Marathi",
        "speaker": "Sunita",
        "desc": "Sunita speaks with a clear Marathi voice, moderate pace, very clear audio.",
    },
    "gu-IN": {
        "label": "Gujarati",
        "speaker": "Neha",
        "desc": "Neha speaks with a clear Gujarati voice, moderate pace, very clear audio.",
    },
    "kn-IN": {
        "label": "Kannada",
        "speaker": "Anu",
        "desc": "Anu speaks with a clear Kannada voice, moderate pace, very clear audio.",
    },
    "ml-IN": {
        "label": "Malayalam",
        "speaker": "Anjali",
        "desc": "Anjali speaks with a clear Malayalam voice, moderate pace, very clear audio.",
    },
    "pa-IN": {
        "label": "Punjabi",
        "speaker": "Gurpreet",
        "desc": "Gurpreet speaks with a clear Punjabi voice, moderate pace, very clear audio.",
    },
    "or-IN": {
        "label": "Odia",
        "speaker": "Debjani",
        "desc": "Debjani speaks with a clear Odia voice, moderate pace, very clear audio.",
    },
    "as-IN": {
        "label": "Assamese",
        "speaker": "Sita",
        "desc": "Sita speaks with a clear Assamese voice, moderate pace, very clear audio.",
    },
    "ur-IN": {
        "label": "Urdu",
        "speaker": "Mary",
        "desc": "Mary speaks with a clear voice at a moderate pace, very clear audio.",
    },
    "sa-IN": {
        "label": "Sanskrit",
        "speaker": "Aryan",
        "desc": "Aryan speaks with a clear Sanskrit voice, moderate pace, very clear audio.",
    },
}

# Sarvam BCP-47 mapping (same keys)
SARVAM_LANGS = {
    "en-IN": "en-IN",
    "hi-IN": "hi-IN",
    "bn-IN": "bn-IN",
    "ta-IN": "ta-IN",
    "te-IN": "te-IN",
    "mr-IN": "mr-IN",
    "gu-IN": "gu-IN",
    "kn-IN": "kn-IN",
    "ml-IN": "ml-IN",
    "pa-IN": "pa-IN",
    "or-IN": "od-IN",
    "as-IN": "as-IN",
    "ur-IN": "ur-IN",
}


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


def resolve_lang(code: str | None = None) -> str:
    lang = (code or os.environ.get("ARKA_SPEAK_LANG") or os.environ.get("SARVAM_TTS_LANG") or "en-IN").strip()
    if lang in LANGS:
        return lang
    # short aliases: hi, ta, en
    aliases = {
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
        "or": "or-IN",
        "as": "as-IN",
        "ur": "ur-IN",
        "sa": "sa-IN",
    }
    return aliases.get(lang.lower(), "en-IN")


def resolve_voice(lang: str, speaker: str | None = None) -> tuple[str, str]:
    meta = LANGS.get(lang, LANGS["en-IN"])
    sp = speaker or os.environ.get("ARKA_SPEAK_SPEAKER") or meta["speaker"]
    desc = meta["desc"]
    if sp and sp not in desc:
        desc = f"{sp}'s voice is clear and natural at a moderate pace, with very clear audio."
    return sp, desc


class ParlerEngine:
    def __init__(self) -> None:
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[parler] Loading {MODEL_ID} on {self.device} ...", file=sys.stderr, flush=True)
        self.model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_ID).to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        self.description_tokenizer = AutoTokenizer.from_pretrained(
            self.model.config.text_encoder._name_or_path
        )
        self.lock = threading.Lock()
        print("[parler] Ready.", file=sys.stderr, flush=True)

    def synthesize(self, text: str, lang: str, speaker: str | None = None) -> Path:
        import soundfile as sf

        text = " ".join(text.split())
        if not text:
            raise ValueError("empty text")

        max_len = int(os.environ.get("AGENT_SPEAK_MAX", "450"))
        if len(text) > max_len:
            text = text[: max_len - 3].rstrip() + "..."

        _, description = resolve_voice(lang, speaker)

        with self.lock:
            description_input_ids = self.description_tokenizer(description, return_tensors="pt").to(
                self.device
            )
            prompt_input_ids = self.tokenizer(text, return_tensors="pt").to(self.device)
            generation = self.model.generate(
                input_ids=description_input_ids.input_ids,
                attention_mask=description_input_ids.attention_mask,
                prompt_input_ids=prompt_input_ids.input_ids,
                prompt_attention_mask=prompt_input_ids.attention_mask,
            )
            audio_arr = generation.cpu().numpy().squeeze()

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        sf.write(str(tmp_path), audio_arr, self.model.config.sampling_rate)
        return tmp_path


def daemon_main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()

    engine = ParlerEngine()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCK_PATH))
    server.listen(4)
    PID_PATH.write_text(str(os.getpid()))

    def cleanup(*_args):
        PID_PATH.unlink(missing_ok=True)
        SOCK_PATH.unlink(missing_ok=True)
        sys.exit(0)

    import signal

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    while True:
        conn, _ = server.accept()
        with conn:
            data = conn.recv(65536).decode("utf-8").strip()
            if not data:
                continue
            try:
                req = json.loads(data)
                wav = engine.synthesize(
                    req.get("text", ""),
                    resolve_lang(req.get("lang")),
                    req.get("speaker"),
                )
                conn.sendall(json.dumps({"ok": True, "wav": str(wav)}).encode("utf-8"))
            except Exception as exc:
                conn.sendall(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))


def client_speak(text: str, lang: str | None = None, speaker: str | None = None) -> None:
    if not SOCK_PATH.exists():
        raise RuntimeError("Parler daemon not running (run: arka listen or indic_tts.py daemon)")

    payload = json.dumps(
        {"text": text, "lang": resolve_lang(lang), "speaker": speaker or os.environ.get("ARKA_SPEAK_SPEAKER")}
    ).encode("utf-8")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(300)
    sock.connect(str(SOCK_PATH))
    sock.sendall(payload)
    resp = json.loads(sock.recv(65536).decode("utf-8"))
    sock.close()
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error", "parler daemon error"))
    wav = Path(resp["wav"])
    try:
        play_wav(wav)
    finally:
        wav.unlink(missing_ok=True)


def ensure_venv() -> Path:
    py = VENV_PY
    if py.exists():
        return py
    import venv

    venv_dir = py.parent.parent
    print(f"[parler] Creating venv at {venv_dir} ...", file=sys.stderr)
    venv.create(venv_dir, with_pip=True)
    subprocess.run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "-q",
            "torch",
            "soundfile",
            "transformers",
            "git+https://github.com/huggingface/parler-tts.git",
        ],
        check=True,
    )
    return py


def start_daemon() -> None:
    if PID_PATH.exists():
        pid = int(PID_PATH.read_text().strip())
        try:
            os.kill(pid, 0)
            return
        except OSError:
            PID_PATH.unlink(missing_ok=True)
    py = ensure_venv()
    log = CACHE / "parler.log"
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        subprocess.Popen(
            [str(py), __file__, "daemon"],
            stdout=fh,
            stderr=fh,
            start_new_session=True,
        )
    for _ in range(120):
        if SOCK_PATH.exists():
            return
        import time

        time.sleep(1)
    raise RuntimeError(f"Parler daemon failed to start; see {log}")


def stop_daemon() -> None:
    import signal

    if not PID_PATH.exists():
        return
    pid = int(PID_PATH.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    PID_PATH.unlink(missing_ok=True)
    SOCK_PATH.unlink(missing_ok=True)


def print_langs() -> None:
    cur = resolve_lang()
    print(f"{'Code':<8} {'Language':<22} {'Speaker':<10} Current")
    print("-" * 50)
    for code, meta in LANGS.items():
        mark = " ←" if code == cur else ""
        print(f"{code:<8} {meta['label']:<22} {meta['speaker']:<10}{mark}")
    print("\nSet: arka speak-lang hi-IN   (or: hi, ta, en, ...)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Indic Parler-TTS for Arka")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("daemon")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("langs")
    p_setup = sub.add_parser("setup")
    p_resolve = sub.add_parser("resolve-lang")
    p_resolve.add_argument("code", nargs="?", default="")

    p_speak = sub.add_parser("speak")
    p_speak.add_argument("text", nargs="?", default="")
    p_speak.add_argument("--lang", default="")
    p_speak.add_argument("--speaker", default="")

    args = parser.parse_args()

    if args.cmd == "daemon":
        return daemon_main()
    if args.cmd == "setup":
        ensure_venv()
        print("Parler TTS venv ready.", file=sys.stderr)
        return 0
    if args.cmd == "start":
        start_daemon()
        print("Parler daemon started.", file=sys.stderr)
        return 0
    if args.cmd == "stop":
        stop_daemon()
        return 0
    if args.cmd == "langs":
        print_langs()
        return 0
    if args.cmd == "resolve-lang":
        print(resolve_lang(args.code or None))
        return 0
    if args.cmd == "speak":
        text = args.text or sys.stdin.read()
        text = text.strip()
        if not text:
            return 1
        try:
            if not SOCK_PATH.exists():
                start_daemon()
            client_speak(text, args.lang or None, args.speaker or None)
        except Exception as exc:
            print(f"indic_tts: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
