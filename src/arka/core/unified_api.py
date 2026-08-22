"""Unified Arka HTTP API settings — one URL + token for agent server, bridges, CLI."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

DEFAULT_API_URL = "http://127.0.0.1:8765"
DEFAULT_REMOTE_HOST = "127.0.0.1"
DEFAULT_REMOTE_PORT = 8765

_URL_KEYS = (
    "API_URL",
    "ARKA_API_URL",
    "BACKEND_URL",
    "ARKA_BACKEND_URL",
    "REMOTE_URL",
    "ARKA_REMOTE_URL",
)
_TOKEN_KEYS = (
    "API_TOKEN",
    "ARKA_API_TOKEN",
    "BACKEND_TOKEN",
    "ARKA_BACKEND_TOKEN",
    "REMOTE_TOKEN",
    "ARKA_REMOTE_TOKEN",
)
_URL_SYNC_KEYS = _URL_KEYS
_TOKEN_SYNC_KEYS = _TOKEN_KEYS + ("ARKA_API_TOKEN", "WEBHOOK_TOKEN")


def _env(name: str, default: str = "") -> str:
    try:
        from arka.env import env_get

        return env_get(name, default)
    except ImportError:
        val = (os.environ.get(name) or default).strip()
        return val


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        val = _env(name)
        if val:
            return val
    return default


def _normalize_url(raw: str) -> str:
    text = (raw or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return f"http://{text}".rstrip("/")
    return text


def _url_from_host_port() -> str:
    host = _first_env("REMOTE_HOST", default=DEFAULT_REMOTE_HOST) or DEFAULT_REMOTE_HOST
    port_raw = _first_env("REMOTE_PORT", default=str(DEFAULT_REMOTE_PORT)) or str(DEFAULT_REMOTE_PORT)
    try:
        port = int(port_raw)
    except ValueError:
        port = DEFAULT_REMOTE_PORT
    if host.startswith("http://") or host.startswith("https://"):
        return _normalize_url(host)
    return f"http://{host}:{port}"


def api_url() -> str:
    """Resolved agent/backend base URL."""
    direct = _first_env(*_URL_KEYS)
    if direct:
        return _normalize_url(direct)
    return _url_from_host_port()


def api_token() -> str:
    """Resolved Bearer token for /v1/agent and related routes."""
    return _first_env(*_TOKEN_KEYS)


def api_timeout(default: int = 600) -> int:
    try:
        return max(1, int(_first_env("REMOTE_TIMEOUT", default=str(default)) or str(default)))
    except ValueError:
        return default


def status_payload() -> dict[str, Any]:
    url = api_url()
    token = api_token()
    return {
        "url": url,
        "token_set": bool(token),
        "health_url": f"{url}/v1/health",
        "agent_url": f"{url}/v1/agent",
        "timeout": api_timeout(),
        "sources": {
            "url": next((name for name in _URL_KEYS if _env(name)), "REMOTE_HOST:REMOTE_PORT"),
            "token": next((name for name in _TOKEN_KEYS if _env(name)), ""),
        },
    }


def apply_unified_api_env() -> None:
    """Mirror unified API settings into legacy env keys (setdefault only)."""
    url = api_url()
    token = api_token()
    if url:
        for key in _URL_SYNC_KEYS:
            os.environ.setdefault(key, url)
    if token:
        for key in _TOKEN_SYNC_KEYS:
            os.environ.setdefault(key, token)
    if url:
        os.environ.setdefault("API_URL", url)
    if token:
        os.environ.setdefault("API_TOKEN", token)
