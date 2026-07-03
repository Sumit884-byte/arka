"""Rotate through multiple API keys per provider on quota/rate-limit errors."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field

_PLACEHOLDER_RE = re.compile(
    r"your_.*_here|^changeme$|^xxx+$|^replace[_-]?me$",
    re.IGNORECASE,
)

_PROVIDER_ENV: dict[str, list[str]] = {
    "gemini": ["GEMINI_API_KEY", "GEMINI_API_KEYS", "GOOGLE_API_KEY"],
    "groq": ["GROQ_API_KEY", "GROQ_API_KEYS"],
    "ollama": ["OLLAMA_API_KEY", "OLLAMA_API_KEYS"],
    "openai": ["OPENAI_API_KEY", "OPENAI_API_KEYS"],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS"],
}

_ENV_TARGETS: dict[str, list[str]] = {
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "ollama": ["OLLAMA_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
}


def _truthy(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in {"1", "true", "yes", "on"}


def _is_placeholder(val: str) -> bool:
    v = (val or "").strip()
    if not v:
        return True
    return bool(_PLACEHOLDER_RE.search(v))


def _split_keys(raw: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[,;]+", raw):
        key = part.strip().strip('"').strip("'")
        if key and not _is_placeholder(key) and key not in out:
            out.append(key)
    return out


def collect_provider_keys(provider: str) -> list[str]:
    """All keys for a provider: primary env, *_API_KEYS, and *_API_KEY_N."""
    provider = provider.lower()
    keys: list[str] = []
    seen: set[str] = set()

    def add_raw(raw: str) -> None:
        for key in _split_keys(raw):
            if key not in seen:
                seen.add(key)
                keys.append(key)

    for name in _PROVIDER_ENV.get(provider, [f"{provider.upper()}_API_KEY"]):
        add_raw(os.environ.get(name, ""))

    prefix = f"{provider.upper()}_API_KEY_"
    numbered: list[tuple[int, str]] = []
    for name, val in os.environ.items():
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix) :]
        if suffix.isdigit():
            numbered.append((int(suffix), val))
    for _, val in sorted(numbered):
        add_raw(val)

    return keys


def is_key_retryable(msg: str) -> bool:
    low = (msg or "").lower()
    return any(
        x in low
        for x in (
            "429",
            "resource_exhausted",
            "quota exceeded",
            "rate limit",
            "rate_limit",
            "too many requests",
            "invalid api key",
            "invalid_api_key",
            "api_key_invalid",
            "api key not valid",
            "permission denied",
            "unauthorized",
            "401",
            "403",
            "503",
            "502",
            "500",
            "timed out",
            "timeout",
        )
    )


def _set_provider_env(provider: str, key: str) -> None:
    for name in _ENV_TARGETS.get(provider.lower(), [f"{provider.upper()}_API_KEY"]):
        os.environ[name] = key


@dataclass
class KeyRotator:
    provider: str
    keys: list[str]
    index: int = 0
    exhausted: set[int] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def active_index(self) -> int | None:
        with self._lock:
            if not self.keys:
                return None
            for _ in range(len(self.keys)):
                if self.index not in self.exhausted:
                    return self.index
                self.index = (self.index + 1) % len(self.keys)
            return None

    def active_key(self) -> str | None:
        idx = self.active_index()
        if idx is None:
            return None
        return self.keys[idx]

    def apply(self) -> str | None:
        key = self.active_key()
        if not key:
            return None
        _set_provider_env(self.provider, key)
        return key

    def mark_failed(self, exc: Exception | str) -> bool:
        if not is_key_retryable(str(exc)):
            return False
        with self._lock:
            if len(self.keys) <= 1:
                return False
            self.exhausted.add(self.index)
            if len(self.exhausted) >= len(self.keys):
                return False
            self.index = (self.index + 1) % len(self.keys)
            while self.index in self.exhausted:
                self.index = (self.index + 1) % len(self.keys)
            return True

    def reset(self) -> None:
        with self._lock:
            self.exhausted.clear()
            self.index = 0


_ROTATORS: dict[str, KeyRotator] = {}
_ROTATOR_LOCK = threading.Lock()


def _get_rotator(provider: str) -> KeyRotator:
    provider = provider.lower()
    with _ROTATOR_LOCK:
        rot = _ROTATORS.get(provider)
        keys = collect_provider_keys(provider)
        if rot is None or rot.keys != keys:
            rot = KeyRotator(provider, keys)
            _ROTATORS[provider] = rot
        return rot


def rotation_enabled() -> bool:
    return _truthy("API_KEY_ROTATION", "1")


def provider_has_keys(provider: str) -> bool:
    return bool(collect_provider_keys(provider))


def apply_provider_key(provider: str) -> str | None:
    """Set os.environ to the active key for this provider."""
    keys = collect_provider_keys(provider)
    if not keys:
        return None
    if not rotation_enabled() or len(keys) == 1:
        key = keys[0]
        _set_provider_env(provider, key)
        return key
    return _get_rotator(provider).apply()


def active_provider_key(provider: str) -> str | None:
    keys = collect_provider_keys(provider)
    if not keys:
        return None
    if not rotation_enabled() or len(keys) == 1:
        return keys[0]
    return _get_rotator(provider).active_key()


def rotate_provider_key(provider: str, exc: Exception | str) -> bool:
    """Mark current key failed and switch to the next. Returns True if rotated."""
    if not rotation_enabled():
        return False
    rot = _get_rotator(provider)
    if len(rot.keys) <= 1:
        return False
    if not rot.mark_failed(exc):
        return False
    rot.apply()
    return True


def iter_provider_keys(provider: str) -> list[str]:
    return collect_provider_keys(provider)


def reset_key_rotators() -> None:
    with _ROTATOR_LOCK:
        for rot in _ROTATORS.values():
            rot.reset()


def key_rotation_label(provider: str) -> str:
    rot = _get_rotator(provider)
    idx = rot.active_index()
    if idx is None or not rot.keys:
        return ""
    return f"key {idx + 1}/{len(rot.keys)}"
