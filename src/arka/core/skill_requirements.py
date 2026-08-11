"""Shared skill/API-key requirement checks with clear user-facing setup messages."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any, Callable

ENV_SETUP_HINTS: dict[str, str] = {
    "GEMINI_API_KEY": "Get a key at https://aistudio.google.com/apikey → add GEMINI_API_KEY to ~/.config/arka/.env",
    "GOOGLE_API_KEY": "Same as GEMINI_API_KEY (or set GOOGLE_API_KEY) — https://aistudio.google.com/apikey",
    "GROQ_API_KEY": "Free tier at https://console.groq.com → set GROQ_API_KEY in ~/.config/arka/.env",
    "SARVAM_API_KEY": "Sign up at https://sarvam.ai → set SARVAM_API_KEY for Indic STT/TTS",
    "POLLINATIONS_API_KEY": "Optional at https://enter.pollinations.ai/ — or use free flux fallback without a key",
    "UNSPLASH_ACCESS_KEY": "Create an app at https://unsplash.com/oauth/applications → UNSPLASH_ACCESS_KEY",
    "OPENAI_API_KEY": "https://platform.openai.com/api-keys → OPENAI_API_KEY",
    "ANTHROPIC_API_KEY": "https://console.anthropic.com/ → ANTHROPIC_API_KEY",
    "GITHUB_TOKEN": "GitHub → Settings → Developer settings → Personal access tokens",
    "KAGGLE_USERNAME": "https://www.kaggle.com/settings → API → KAGGLE_USERNAME + KAGGLE_KEY",
    "KAGGLE_KEY": "Pair with KAGGLE_USERNAME in ~/.config/arka/.env",
    "HF_TOKEN": "https://huggingface.co/settings/tokens → HF_TOKEN (for some 3D/text-to-3d backends)",
}

# Dispatch-backed skills without a plugin skill.json entry.
DISPATCH_SKILL_REQUIRES: dict[str, dict[str, Any]] = {
    "dub_video": {
        "bins": ["ffmpeg", "ffprobe"],
        "checks": ["stt", "tts"],
        "note": "Skip STT by passing --script. STT: GROQ_API_KEY, SARVAM_API_KEY, or local faster-whisper. TTS: pip install edge-tts (free) or SARVAM_API_KEY for Indic.",
    },
    "generate_image": {
        "note": "Uses GEMINI/GOOGLE_API_KEY or POLLINATIONS_API_KEY; free Pollinations flux works without a key when IMAGE_FALLBACK=1 (default).",
    },
    "ai_video": {
        "env_any": ["POLLINATIONS_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "note": "Set POLLINATIONS_API_KEY or enable Gemini billing on GEMINI_API_KEY.",
    },
    "compose_video": {
        "bins": ["ffmpeg"],
        "note": "Needs Pillow + ffmpeg. Stock photos: UNSPLASH_ACCESS_KEY (or Pexels/Pixabay). LLM slides: GEMINI_API_KEY or GROQ_API_KEY.",
    },
    "media_transcript": {
        "note": "STT: set GROQ_API_KEY or SARVAM_API_KEY, or install local faster-whisper (pip install faster-whisper).",
    },
}


def is_env_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def missing_env(names: list[str]) -> list[str]:
    return [n for n in names if n and not is_env_set(n)]


def any_env_set(names: list[str]) -> bool:
    return any(is_env_set(n) for n in names)


def hint_for_env(name: str) -> str:
    return ENV_SETUP_HINTS.get(name, f"Set {name} in ~/.config/arka/.env or your shell environment.")


def _which(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def stt_backend_available() -> bool:
    if any_env_set(["GROQ_API_KEY", "SARVAM_API_KEY", "ASSEMBLYAI_API_KEY"]):
        return True
    try:
        from arka.media.transcript import _faster_whisper_available, _local_python_candidates

        for py in _local_python_candidates():
            if _faster_whisper_available(py):
                return True
    except ImportError:
        pass
    return False


def tts_backend_available(*, prefer_sarvam: bool = False) -> bool:
    if prefer_sarvam and is_env_set("SARVAM_API_KEY"):
        return True
    if is_env_set("SARVAM_API_KEY"):
        return True
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return is_env_set("SARVAM_API_KEY")
    return True


def image_generation_available() -> bool:
    if any_env_set(["GOOGLE_API_KEY", "GEMINI_API_KEY", "POLLINATIONS_API_KEY"]):
        return True
    if os.environ.get("IMAGE_FALLBACK", "1") not in ("0", "false", "no"):
        return True
    return False


CUSTOM_CHECKS: dict[str, Callable[[], tuple[bool, str]]] = {
    "stt": lambda: (stt_backend_available(), "speech-to-text (GROQ_API_KEY, SARVAM_API_KEY, or local faster-whisper)"),
    "tts": lambda: (tts_backend_available(), "text-to-speech (pip install edge-tts, or SARVAM_API_KEY)"),
    "image_gen": lambda: (image_generation_available(), "image generation (GEMINI/GOOGLE/POLLINATIONS key or free fallback)"),
}


def check_requires(requires: dict[str, Any] | None, *, skill: str = "") -> tuple[bool, str]:
    """Return (ok, user_message). Empty message when ok."""
    req = requires or {}
    label = skill or "this skill"
    problems: list[str] = []

    for bin_name in req.get("bins") or []:
        if not _which(str(bin_name)):
            problems.append(f"Missing program: {bin_name} (install and ensure it is on PATH)")

    missing_all = missing_env([str(e) for e in req.get("env") or []])
    for env_name in missing_all:
        problems.append(f"Missing API key: {env_name}. {hint_for_env(env_name)}")

    env_any = [str(e) for e in req.get("env_any") or []]
    if env_any and not any_env_set(env_any):
        opts = ", ".join(env_any)
        hints = " · ".join(hint_for_env(e) for e in env_any[:3])
        problems.append(f"Needs at least one API key: {opts}. {hints}")

    for check_name in req.get("checks") or []:
        fn = CUSTOM_CHECKS.get(str(check_name))
        if not fn:
            continue
        ok, desc = fn()
        if not ok:
            problems.append(f"Missing setup: {desc}")

    note = str(req.get("note") or "").strip()
    if problems:
        lines = [f"Cannot run {label} — setup incomplete:", *[f"  • {p}" for p in problems]]
        if note:
            lines.append(f"Note: {note}")
        lines.append("Run with `check` subcommand if available, or `arka env` / ~/.config/arka/.env")
        return False, "\n".join(lines)

    if note and req.get("warn_if_incomplete"):
        pass
    return True, ""


def ensure_requires(requires: dict[str, Any] | None, *, skill: str = "") -> None:
    ok, msg = check_requires(requires, skill=skill)
    if not ok:
        raise SystemExit(msg)


def requirements_for_skill_name(name: str) -> dict[str, Any]:
    """Merge plugin skill.json requires with dispatch registry."""
    req: dict[str, Any] = dict(DISPATCH_SKILL_REQUIRES.get(name) or {})
    try:
        from arka.agent.skills import get_skill

        sk = get_skill(name)
        if sk and isinstance(sk.get("requires"), dict):
            plugin_req = sk["requires"]
            for key, val in plugin_req.items():
                if key not in req or not req[key]:
                    req[key] = val
                elif isinstance(val, list) and isinstance(req.get(key), list):
                    merged = list(dict.fromkeys([*req[key], *val]))
                    req[key] = merged
    except ImportError:
        pass
    return req


def preflight_skill(name: str, *, extra: dict[str, Any] | None = None) -> tuple[bool, str]:
    req = requirements_for_skill_name(name)
    if extra:
        merged = dict(req)
        merged.update(extra)
        req = merged
    return check_requires(req, skill=name)


def format_gate_reason(skill: str, reason: str) -> str:
    """Turn terse gate reasons into actionable messages."""
    if reason.startswith("missing env:"):
        env_name = reason.split(":", 1)[1].strip()
        return f"Cannot run {skill}: missing {env_name}. {hint_for_env(env_name)}"
    if reason.startswith("missing binary:"):
        bin_name = reason.split(":", 1)[1].strip()
        return f"Cannot run {skill}: {bin_name} not found on PATH."
    return f"Cannot run {skill}: {reason}"


def exit_if_blocked(ok: bool, message: str, *, code: int = 2) -> None:
    if not ok and message:
        print(message, file=sys.stderr)
        raise SystemExit(code)
