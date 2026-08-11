"""Guided setup for hosting local or OpenAI-compatible AI models."""
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class HostOption:
    name: str
    kind: str
    env: tuple[str, ...]
    command: str
    notes: str


OPTIONS = {
    "ollama": HostOption("ollama", "local", ("OLLAMA_HOST", "OLLAMA_CHAT_MODEL"), "OLLAMA_HOST=127.0.0.1:11434 ollama serve", "Bind localhost only — Ollama has no auth by default"),
    "apple-fm": HostOption(
        "apple-fm",
        "local",
        ("APPLE_FM_ENABLED", "APPLE_FM_MODELS"),
        "pip install apple-fm-sdk",
        "Requires macOS 26+, Apple Intelligence enabled. Optional: apple-fm-cli server for OpenAI-compatible fallback",
    ),
    "vllm": HostOption("vllm", "local", ("VLLM_API_URL", "VLLM_MODEL"), "vllm serve <model> --host 127.0.0.1 --port 8000", "GPU recommended; Arka can auto-start when VLLM_START_CMD is configured"),
    "lmstudio": HostOption("lmstudio", "local", ("LMSTUDIO_API_BASE", "LMSTUDIO_MODELS"), "Start the LM Studio local server", "Use the OpenAI-compatible server URL, normally http://127.0.0.1:1234/v1"),
    "exo": HostOption("exo", "local-cluster", ("EXO_API_BASE", "EXO_MODEL"), "Start Exo on the LAN and join worker nodes", "Exo combines available Macs/Linux workstations; expose its OpenAI-compatible endpoint only on your trusted network"),
    "openai-compatible": HostOption("openai-compatible", "hosted", ("OPENAI_API_KEY", "OPENAI_API_BASE", "AI_PREFERRED_MODEL"), "Use the provider's OpenAI-compatible endpoint", "Keep API keys in Arka's protected .env; never commit them"),
}


def setup(name: str, *, model: str = "", url: str = "") -> dict[str, str]:
    if name not in OPTIONS:
        raise ValueError(f"unknown host: {name}; choose {', '.join(OPTIONS)}")
    from arka.llm.provider_select import set_env_vars
    option = OPTIONS[name]
    values: dict[str, str] = {"AI_PREFERRED_PROVIDER": "openai" if name == "openai-compatible" else name}
    if name == "apple-fm":
        values["APPLE_FM_ENABLED"] = "1"
    if model:
        values["AI_PREFERRED_MODEL"] = model
        if name == "ollama":
            values["OLLAMA_CHAT_MODEL"] = model
        elif name == "apple-fm":
            values["APPLE_FM_MODELS"] = model
        elif name == "vllm":
            values["VLLM_MODEL"] = model
        elif name == "lmstudio":
            values["LMSTUDIO_MODELS"] = model
        elif name == "exo":
            values["EXO_MODEL"] = model
    if url:
        values["OPENAI_API_BASE" if name == "openai-compatible" else f"{name.upper().replace('-', '_')}_API_BASE"] = url.rstrip("/")
    path = set_env_vars(values)
    pull_note = ""
    if name == "ollama" and model:
        try:
            from arka.llm.servers import ensure_ollama_model, ollama_auto_pull_enabled

            if ollama_auto_pull_enabled():
                ok, msg = ensure_ollama_model(model)
                pull_note = f"\nOllama pull: {msg}" if msg else ""
                if not ok and "disabled" not in msg and "already attempted" not in msg:
                    pull_note = f"\nOllama pull failed: {msg}"
        except ImportError:
            pass
    return {"host": name, "kind": option.kind, "config": str(path), "command": option.command, "notes": option.notes + pull_note}


def status_report(*, json_output: bool = False) -> dict[str, str]:
    """Status for all model hosts including Apple Intelligence."""
    rows: dict[str, str] = {}
    for option in OPTIONS.values():
        binary = option.name if option.name not in {"openai-compatible", "apple-fm"} else ""
        if option.name == "apple-fm":
            try:
                from arka.llm.apple_fm import check_availability

                st = check_availability()
                rows[option.name] = "ready" if st.available else "unavailable"
            except ImportError:
                rows[option.name] = "missing"
        elif not binary or shutil.which(binary):
            rows[option.name] = "installed"
        else:
            rows[option.name] = "missing"
    return rows


def cmd_status(*, json_output: bool = False) -> int:
    rows = status_report()
    if json_output:
        print(json.dumps(rows, indent=2))
        return 0
    for name, state in rows.items():
        option = OPTIONS[name]
        print(f"{name}\t{state}\t{option.notes}")
    try:
        from arka.llm.apple_fm import status_lines

        print("")
        for line in status_lines():
            print(line.replace("\t", "\t", 1))
    except ImportError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka model setup")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    sub.add_parser("status")
    setup_parser = sub.add_parser("setup")
    setup_parser.add_argument("host", choices=sorted(OPTIONS))
    setup_parser.add_argument("--model", default="")
    setup_parser.add_argument("--url", default="")
    setup_parser.add_argument("--json", action="store_true")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("host", nargs="?", choices=sorted(OPTIONS))
    args = parser.parse_args(argv)
    if args.action == "list":
        for option in OPTIONS.values():
            print(f"{option.name}\t{option.kind}\t{option.notes}")
        return 0
    if args.action == "status":
        return cmd_status(json_output=getattr(args, "json", False))
    if args.action == "setup":
        result = setup(args.host, model=args.model, url=args.url)
        print(json.dumps(result, indent=2) if args.json else f"Configured {args.host}. Next: {result['command']}\n{result['notes']}")
        return 0
    targets = [OPTIONS[args.host]] if args.host else list(OPTIONS.values())
    try:
        from arka.core.api_security import doctor_lines as api_security_doctor_lines

        for line in api_security_doctor_lines():
            print(line)
        print("")
    except ImportError:
        pass
    for option in targets:
        binary = option.name if option.name != "openai-compatible" else ""
        print(f"{option.name}\t{'installed' if not binary or shutil.which(binary) else 'missing'}\t{option.command}")
    return 0
