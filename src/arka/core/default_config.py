"""Safe, local-first default configuration and first-run setup preview."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arka.paths import config_dir, env_file

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

SHARE_VERSION = 1
SECRET_KEY_RE = re.compile(r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PRIVATE|CREDENTIAL|COOKIE|WEBHOOK)", re.I)
SAFE_ENV_ALLOWLIST = {
    "ROUTE_MODE",
    "PROMPT_OPTIMIZE",
    "ARKA_MODEL_MODE",
    "ARKA_HOSTED_MODE",
    "ARKA_PREFERRED_SMALL_MODEL",
    "ARKA_PREFERRED_CODING_MODEL",
    "ARKA_MAX_CONTEXT",
    "ARKA_QUANT",
    "ARKA_PROMPT_CHUNKING",
    "ARKA_PROMPT_CHUNK_SIZE",
    "ARKA_USAGE_TRACK",
    "USAGE_TRACK",
    "LLM_FALLBACK",
    "LLM_AUTO_START_SERVERS",
    "AI_PREFERRED_PROVIDER",
    "AI_PREFERRED_MODEL",
    "TEAM_MAX_PARALLEL",
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


def _read_env_file(path: Path | None = None) -> dict[str, str]:
    path = path or env_file()
    rows: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rows
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        rows[key.strip()] = value.strip().strip("'\"")
    return rows


def _is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_RE.search(key))


def export_share_bundle(*, include_env: bool = True) -> dict[str, Any]:
    """Return a safe-to-share config bundle with secrets removed."""
    stored = read()
    profile = preview()
    env_rows = _read_env_file() if include_env else {}
    safe_env: dict[str, str] = {}
    required_env: list[str] = []
    redacted_env: list[str] = []
    for key, value in sorted(env_rows.items()):
        if _is_secret_key(key):
            redacted_env.append(key)
            required_env.append(key)
        elif key in SAFE_ENV_ALLOWLIST or key.startswith(("ARKA_", "LLM_", "AI_")):
            safe_env[key] = value
    return {
        "kind": "arka-config-share",
        "version": SHARE_VERSION,
        "exported_by": "arka",
        "defaults": stored.get("defaults", profile.values) if isinstance(stored, dict) else profile.values,
        "provider": stored.get("provider", profile.provider) if isinstance(stored, dict) else profile.provider,
        "model": stored.get("model", profile.model) if isinstance(stored, dict) else profile.model,
        "env": safe_env,
        "required_env": sorted(set(required_env)),
        "redacted_env": sorted(set(redacted_env)),
        "notes": [
            "Secrets are never exported. Recipients must fill required_env values themselves.",
            "Import is preview-only unless --apply is passed.",
        ],
    }


def import_share_bundle(bundle: dict[str, Any], *, apply_changes: bool = False) -> dict[str, Any]:
    if bundle.get("kind") != "arka-config-share":
        raise ValueError("not an Arka config share bundle")
    defaults = bundle.get("defaults", {})
    safe_env = bundle.get("env", {})
    if not isinstance(defaults, dict) or not isinstance(safe_env, dict):
        raise ValueError("invalid Arka config share bundle")
    proposed_defaults = {str(k): str(v) for k, v in defaults.items() if isinstance(k, str)}
    proposed_env = {str(k): str(v) for k, v in safe_env.items() if isinstance(k, str) and not _is_secret_key(k)}
    result = {
        "apply": apply_changes,
        "defaults": proposed_defaults,
        "env": proposed_env,
        "required_env": bundle.get("required_env", []),
        "redacted_env": bundle.get("redacted_env", []),
    }
    if not apply_changes:
        return result
    current = read()
    managed = dict(current.get("defaults", {})) if isinstance(current.get("defaults"), dict) else {}
    for key, value in proposed_defaults.items():
        managed.setdefault(key, value)
    payload = {
        "version": VERSION,
        "defaults": managed,
        "provider": current.get("provider") or bundle.get("provider", ""),
        "model": current.get("model") or bundle.get("model", ""),
        "hardware": current.get("hardware", {}),
    }
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    existing_env = _read_env_file()
    env_target = env_file()
    env_target.parent.mkdir(parents=True, exist_ok=True)
    additions = []
    for key, value in proposed_env.items():
        if key not in existing_env and key not in os.environ:
            additions.append(f"{key}={value}")
    if additions:
        prefix = "\n" if env_target.exists() and env_target.read_text(encoding="utf-8", errors="replace").strip() else ""
        with env_target.open("a", encoding="utf-8") as fh:
            fh.write(prefix + "\n".join(additions) + "\n")
    result["path"] = str(target)
    result["env_path"] = str(env_target)
    result["env_added"] = additions
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka config")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    configure = sub.add_parser("configure")
    configure.add_argument("--apply", action="store_true")
    configure.add_argument("--json", action="store_true")
    share = sub.add_parser("share")
    share_sub = share.add_subparsers(dest="share_command", required=True)
    share_export = share_sub.add_parser("export")
    share_export.add_argument("--out", default="")
    share_export.add_argument("--no-env", action="store_true")
    share_import = share_sub.add_parser("import")
    share_import.add_argument("file")
    share_import.add_argument("--apply", action="store_true")
    share_import.add_argument("--json", action="store_true")
    sub.add_parser("reset")
    args = parser.parse_args(argv)
    if args.command == "share" and args.share_command == "export":
        bundle = export_share_bundle(include_env=not args.no_env)
        text = json.dumps(bundle, indent=2, sort_keys=True) + "\n"
        if args.out:
            target = Path(args.out).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"config_share\t{target}")
        else:
            print(text, end="")
        return 0
    if args.command == "share" and args.share_command == "import":
        try:
            bundle = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
            result = import_share_bundle(bundle, apply_changes=args.apply)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"config share import failed: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("status\t" + ("applied" if args.apply else "preview only"))
            print(f"defaults\t{len(result['defaults'])}")
            print(f"env\t{len(result['env'])}")
            if result.get("required_env"):
                print("required_env\t" + ", ".join(result["required_env"]))
            if result.get("path"):
                print(f"config\t{result['path']}")
        return 0
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
