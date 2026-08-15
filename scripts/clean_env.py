#!/usr/bin/env python3
"""Keep only active .env values, dedupe, and group by section."""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

PLACEHOLDERS = {
    "your_key_here",
    "your_gemini_api_key_here",
    "your_groq_api_key_here",
    "changeme",
    "change_me",
    "xxx",
    "todo",
    "fixme",
    "placeholder",
    "your-key",
    "your_key",
    "insert_key_here",
    "api_key_here",
    "your-secret-here",
}

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "LLM — API keys",
        [
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "OPENROUTER_API_KEY",
            "OLLAMA_API_KEY",
            "HF_TOKEN",
            "CONTEXT7_API_KEY",
            "SARVAM_API_KEY",
            "ASSEMBLYAI_API_KEY",
            "UNSPLASH_ACCESS_KEY",
            "BRIGHTDATA_API_TOKEN",
            "BRIGHTDATA_SERP_ZONE",
            "RESEND_API_KEY",
            "PYPI_TOKEN",
            "KAGGLE_KEY",
            "KAGGLE_USERNAME",
        ],
    ),
    (
        "LLM — provider & models",
        [
            "AI_PREFERRED_PROVIDER",
            "AI_PREFERRED_MODEL",
            "GEMINI_MODELS",
            "OPENROUTER_FREE_ONLY",
            "LLM_FALLBACK_NOTIFY",
            "ROUTE_MODE",
            "OLLAMA_HOST",
            "OLLAMA_CHAT_MODEL",
            "VLLM_CLOUD_URL",
            "VLLM_CLOUD_API_KEY",
            "VLLM_CLOUD_MODEL",
            "OLLAMA_TUNNEL_TOKEN",
            "OLLAMA_TUNNEL_PORT",
        ],
    ),
    (
        "Arka agent & voice",
        [
            "AGENT_NAME",
            "AGENT_WAKE_WORDS",
            "AGENT_WAKE_AUTO",
            "AGENT_SPEAK",
            "AGENT_TTS",
            "STT",
            "LISTEN_ENGINE",
            "SARVAM_STT_MODE",
            "SARVAM_TTS_SPEAKER",
            "SPEAK_LANG",
            "SPEAK_VOICE",
            "AUTO_START",
        ],
    ),
    (
        "Arka remote & API",
        [
            "REMOTE_AUTO",
            "REMOTE_HOST",
            "REMOTE_PORT",
            "REMOTE_TOKEN",
            "WEBHOOK_HOST",
            "WEBHOOK_ENABLED",
            "ARKA_API_ENABLED",
            "ARKA_API_HOST",
            "ARKA_API_PORT",
            "ARKA_API_RPM",
            "ARKA_API_ONLY",
            "ARKA_FETCH_DEDUP",
            "ARKA_GRAPH_MEMORY",
            "USAGE_TRACK",
            "WEB_TRACK",
        ],
    ),
    (
        "Auth & OAuth",
        [
            "BETTER_AUTH_SECRET",
            "BETTER_AUTH_URL",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GITHUB_CLIENT_ID",
            "GITHUB_CLIENT_SECRET",
            "GITHUB_USERNAME",
            "DATABASE_URL",
        ],
    ),
    (
        "Observability (SigNoz / OTEL)",
        [
            "OTEL_TRACES_ENABLED",
            "OTEL_SERVICE_NAME",
            "OTEL_SERVICE_NAMESPACE",
            "SIGNOZ_ENDPOINT",
            "SIGNOZ_UI_URL",
            "signoz_gmail",
            "signoz_password",
        ],
    ),
    (
        "YouTube & media",
        [
            "YT_WHISPER_FALLBACK",
            "YT_PLAYER_CLIENT",
            "YT_RESEARCH_DELAY",
            "YT_RESEARCH_MAX",
            "YT_429_WAIT",
            "VIDEO_STOCK_FALLBACK",
        ],
    ),
    ("WhatsApp", ["WHATSAPP_FROM", "WHATSAPP_REPLY", "WHATSAPP_POLL"]),
    (
        "Personal / resume",
        [
            "RESUME_NAME",
            "RESUME_EMAIL",
            "RESUME_PHONE",
            "RESUME_LINKEDIN",
            "linkedin_email",
            "linkedin_password",
            "STOCK_PROJECT",
        ],
    ),
    (
        "OpenClaw",
        [
            "OPENCLAW_GATEWAY_PORT",
            "OPENCLAW_PATH_BOOTSTRAPPED",
            "OPENCLAW_SERVICE_KIND",
            "OPENCLAW_SERVICE_MARKER",
            "OPENCLAW_SERVICE_VERSION",
            "OPENCLAW_SHELL",
            "OPENCLAW_SYSTEMD_UNIT",
        ],
    ),
    (
        "Locale",
        [
            "LC_ADDRESS",
            "LC_IDENTIFICATION",
            "LC_MEASUREMENT",
            "LC_MONETARY",
            "LC_NAME",
            "LC_PAPER",
            "LC_TELEPHONE",
            "LC_TIME",
        ],
    ),
    ("Other", []),
]


def is_useful_value(value: str) -> bool:
    value = value.strip().strip('"').strip("'")
    if not value:
        return False
    low = value.lower()
    if low in PLACEHOLDERS:
        return False
    return not ("your_" in low and "here" in low)


def parse_entries(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if "#" in value:
            value = value.split("#", 1)[0]
        value = value.strip()
        if is_useful_value(value):
            entries[key] = value
    return entries


def render(entries: dict[str, str]) -> str:
    used: set[str] = set()
    lines: list[str] = [
        "# Arka .env — active values only (cleaned)",
        f"# Regenerated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "# See src/arka/env.example for optional vars and documentation.",
        "",
    ]

    for title, keys in SECTIONS:
        section_keys = [key for key in keys if key in entries]
        if title == "Other":
            section_keys = sorted(key for key in entries if key not in used)
        if not section_keys:
            continue
        lines.append(f"# {'=' * 75}")
        lines.append(f"# {title}")
        lines.append(f"# {'=' * 75}")
        for key in section_keys:
            lines.append(f"{key}={entries[key]}")
            used.add(key)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    env_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path(".env")
    if not env_path.is_file():
        print(f"Missing file: {env_path}", file=sys.stderr)
        return 1

    original = env_path.read_text(encoding="utf-8")
    entries = parse_entries(original)
    backup = env_path.with_suffix(env_path.suffix + f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(env_path, backup)
    env_path.write_text(render(entries), encoding="utf-8")

    before_lines = len(original.splitlines())
    after_lines = len(env_path.read_text(encoding="utf-8").splitlines())
    print(f"Backup: {backup.name}")
    print(f"Kept {len(entries)} keys ({before_lines} lines -> {after_lines} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
