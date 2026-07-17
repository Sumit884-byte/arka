"""Safe, local-first default configuration and first-run setup preview."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arka.paths import config_dir

VERSION = 1
CONFIG_NAME = "config.json"
DEFAULTS: dict[str, str] = {
    "ROUTE_MODE": "symbolic",
    "PROMPT_OPTIMIZE": "1",
    "ARKA_MODEL_MODE": "auto",
    "ARKA_HOSTED_MODE": "auto",
    "LLM_FALLBACK": "1",
    "UNIFIED_MEMORY": "1",
    "MEMORY": "auto",
    "USAGE_TRACK": "1",
    "ARKA_PREVIEW_WRITES": "1",
    "SHOW_MODEL": "0",
    "LLM_AUTO_START_SERVERS": "0",
    "TEAM_MAX_PARALLEL": "4",
    "SELF_IMPROVE_MAX_ROUNDS": "3",
    "LLM_SERVER_START_TIMEOUT": "60",
}


@dataclass(frozen=True)
class DefaultProfile:
    version: int
    values: dict[str, str]
    provider: str
    model: str
    hardware: dict[str, Any]


def path() -> Path:
    return config_dir() / CONFIG_NAME


def read() -> dict[str, Any]:
    try:
        data = json.loads(path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _local_recommendation() -> tuple[str, str, dict[str, Any]]:
    try:
        from arka.llm.model_advisor import build_report, strongest_runnable_local_models

        report = build_report()
        models = strongest_runnable_local_models(report.hardware, limit=1)
        if models:
            return "ollama", models[0], asdict(report.hardware)
        return "ollama", "llama3.2:3b", asdict(report.hardware)
    except (ImportError, OSError, RuntimeError, ValueError):
        return "ollama", "llama3.2:3b", {}


def preview() -> DefaultProfile:
    provider, model, hardware = _local_recommendation()
    values = dict(DEFAULTS)
    for key in DEFAULTS:
        if os.environ.get(key, "").strip():
            values[key] = os.environ[key].strip()
    explicit_provider = os.environ.get("AI_PREFERRED_PROVIDER", "").strip()
    explicit_model = os.environ.get("AI_PREFERRED_MODEL", "").strip()
    return DefaultProfile(VERSION, values, explicit_provider or provider, explicit_model or model, hardware)


def apply(profile: DefaultProfile | None = None) -> Path:
    profile = profile or preview()
    current = read()
    managed = dict(current.get("defaults", {})) if isinstance(current.get("defaults"), dict) else {}
    for key, value in profile.values.items():
        if os.environ.get(key, "").strip() or key not in managed:
            managed[key] = value
    payload = {
        "version": profile.version,
        "defaults": managed,
        "provider": profile.provider,
        "model": profile.model,
        "hardware": profile.hardware,
    }
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target


def reset() -> None:
    target = path()
    if target.exists():
        target.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka config")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    configure = sub.add_parser("configure")
    configure.add_argument("--apply", action="store_true")
    configure.add_argument("--json", action="store_true")
    sub.add_parser("reset")
    args = parser.parse_args(argv)
    if args.command == "reset":
        reset()
        print("config\treset")
        return 0
    profile = preview()
    payload = asdict(profile)
    if args.command == "show":
        stored = read()
        payload["stored"] = stored
    elif args.apply:
        payload["path"] = str(apply(profile))
        payload["applied"] = True
    else:
        payload["applied"] = False
        payload["note"] = "preview only; pass --apply to write"
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"provider\t{profile.provider}")
        print(f"model\t{profile.model}")
        print(f"values\t{len(profile.values)} defaults")
        print("status\t" + ("applied" if payload.get("applied") else "preview only"))
        if payload.get("path"):
            print(f"config\t{payload['path']}")
    return 0
