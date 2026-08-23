"""HTTP/API exposure checks — bind addresses, tokens, and local service safety."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Severity = Literal["ok", "warn", "critical"]

_PLACEHOLDER_TOKENS = frozenset(
    {
        "",
        "your-secret-here",
        "your_secret_here",
        "changeme",
        "change-me",
    }
)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def is_public_bind(host: str) -> bool:
    """True when a listen address accepts non-local connections."""
    h = (host or "").strip().lower()
    if not h:
        return False
    if h in {"0.0.0.0", "::", "[::]", "*"}:
        return True
    if h.startswith("0.0.0.0:"):
        return True
    return False


def host_only(value: str, *, default: str = "127.0.0.1") -> str:
    """Extract host from host:port or URL-ish values."""
    raw = (value or default).strip()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if raw.startswith("[") and "]" in raw:
        return raw[1 : raw.index("]")]
    if raw.count(":") == 1 and raw.rsplit(":", 1)[-1].isdigit():
        return raw.rsplit(":", 1)[0] or default
    return raw or default


def safe_ollama_host(default: str = "127.0.0.1:11434") -> str:
    """Client connect + auto-start bind — never use 0.0.0.0 for local Ollama."""
    host = _env("OLLAMA_HOST", default)
    if is_public_bind(host_only(host)):
        port = "11434"
        if ":" in host and host.rsplit(":", 1)[-1].isdigit():
            port = host.rsplit(":", 1)[-1]
        return f"127.0.0.1:{port}"
    return host


def resolve_remote_host() -> str:
    """Listen address for arka remote server."""
    explicit = _env("REMOTE_HOST")
    if explicit:
        return explicit
    if _env("PORT"):
        return "0.0.0.0"
    return "127.0.0.1"


def token_configured(name: str, *, fallback: str = "") -> bool:
    value = (_env(name) or _env(fallback)).strip()
    return bool(value) and value.lower() not in _PLACEHOLDER_TOKENS


@dataclass(frozen=True)
class SecurityFinding:
    severity: Severity
    message: str
    hint: str = ""


def security_findings() -> list[SecurityFinding]:
    """Non-secret audit of HTTP/API exposure settings."""
    findings: list[SecurityFinding] = []

    ollama_raw = _env("OLLAMA_HOST", "127.0.0.1:11434")
    if is_public_bind(host_only(ollama_raw)):
        findings.append(
            SecurityFinding(
                "critical",
                f"OLLAMA_HOST binds publicly ({ollama_raw}) — Ollama has no auth by default",
                "Set OLLAMA_HOST=127.0.0.1:11434 (Arka auto-start uses localhost)",
            )
        )

    remote_host = resolve_remote_host()
    remote_token_ok = token_configured("REMOTE_TOKEN")
    if is_public_bind(remote_host):
        if not remote_token_ok:
            findings.append(
                SecurityFinding(
                    "critical",
                    f"Remote server on {remote_host} without REMOTE_TOKEN",
                    "Set REMOTE_TOKEN in .env before exposing REMOTE_HOST=0.0.0.0",
                )
            )
        else:
            findings.append(
                SecurityFinding(
                    "warn",
                    f"Remote server listens on {remote_host} (LAN/internet reachable)",
                    "Use REMOTE_HOST=127.0.0.1 locally; require Bearer token on all API routes",
                )
            )

    webhook_enabled = _env("WEBHOOK_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    webhook_host = _env("WEBHOOK_HOST", "127.0.0.1")
    if webhook_enabled:
        if not token_configured("WEBHOOK_TOKEN", fallback="REMOTE_TOKEN"):
            findings.append(
                SecurityFinding(
                    "critical",
                    "WEBHOOK_ENABLED=1 but no WEBHOOK_TOKEN or REMOTE_TOKEN",
                    "Set WEBHOOK_TOKEN before enabling webhook ingress",
                )
            )
        if is_public_bind(webhook_host):
            findings.append(
                SecurityFinding(
                    "warn",
                    f"Webhook listens on {webhook_host}",
                    "Prefer WEBHOOK_HOST=127.0.0.1 and reverse-proxy with TLS",
                )
            )

    api_enabled = _env("ARKA_API_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    api_host = _env("ARKA_API_HOST", "127.0.0.1")
    if api_enabled:
        if not token_configured("ARKA_API_TOKEN", fallback="REMOTE_TOKEN"):
            findings.append(
                SecurityFinding(
                    "critical",
                    "ARKA_API_ENABLED=1 but no ARKA_API_TOKEN or REMOTE_TOKEN",
                    "Set ARKA_API_TOKEN before enabling the inference API",
                )
            )
        if is_public_bind(api_host):
            findings.append(
                SecurityFinding(
                    "warn",
                    f"Arka API listens on {api_host}",
                    "Prefer ARKA_API_HOST=127.0.0.1 and reverse-proxy with TLS",
                )
            )

    bridge_host = _env("ARKA_BRIDGE_HOST", "127.0.0.1")
    if is_public_bind(bridge_host):
        findings.append(
            SecurityFinding(
                "warn",
                f"Desktop bridge on {bridge_host}",
                "Keep ARKA_BRIDGE_HOST=127.0.0.1 unless behind auth",
            )
        )

    if not findings:
        findings.append(SecurityFinding("ok", "HTTP/API bind addresses look local-only", ""))
    return findings


def doctor_lines() -> list[str]:
    lines = ["  API security:"]
    for item in security_findings():
        prefix = {"ok": "ok", "warn": "WARN", "critical": "CRITICAL"}[item.severity]
        lines.append(f"    {prefix}: {item.message}")
        if item.hint:
            lines.append(f"           → {item.hint}")
    lines.append("    MCP: stdio-only (no network listener)")
    lines.append(
        "    Docs: API_URL, API_TOKEN, REMOTE_TOKEN, WEBHOOK_TOKEN, OLLAMA_HOST, REMOTE_HOST in .env"
    )
    return lines


def warn_if_insecure_startup(service: str) -> None:
    """Print one-line stderr warnings when starting HTTP services."""
    for item in security_findings():
        if item.severity != "critical":
            continue
        if service == "remote" and "Remote server" not in item.message and "OLLAMA" in item.message:
            continue
        if service == "webhook" and "Webhook" not in item.message and "WEBHOOK" not in item.message:
            continue
        if service == "arka-api" and "Arka API" not in item.message and "ARKA_API" not in item.message:
            continue
        if service == "ollama" and "OLLAMA" not in item.message:
            continue
        print(f"[arka-{service}] SECURITY: {item.message}. {item.hint}", flush=True)
