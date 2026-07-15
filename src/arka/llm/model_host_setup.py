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
    "ollama": HostOption("ollama", "local", ("OLLAMA_HOST", "OLLAMA_CHAT_MODEL"), "ollama serve", "Install Ollama, then pull a model with `ollama pull qwen3:8b`"),
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
    if model:
        values["AI_PREFERRED_MODEL"] = model
        if name == "ollama":
            values["OLLAMA_CHAT_MODEL"] = model
        elif name == "vllm":
            values["VLLM_MODEL"] = model
        elif name == "lmstudio":
            values["LMSTUDIO_MODELS"] = model
        elif name == "exo":
            values["EXO_MODEL"] = model
    if url:
        values["OPENAI_API_BASE" if name == "openai-compatible" else f"{name.upper().replace('-', '_')}_API_BASE"] = url.rstrip("/")
    path = set_env_vars(values)
    return {"host": name, "kind": option.kind, "config": str(path), "command": option.command, "notes": option.notes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka model setup")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
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
    if args.action == "setup":
        result = setup(args.host, model=args.model, url=args.url)
        print(json.dumps(result, indent=2) if args.json else f"Configured {args.host}. Next: {result['command']}\n{result['notes']}")
        return 0
    targets = [OPTIONS[args.host]] if args.host else list(OPTIONS.values())
    for option in targets:
        binary = option.name if option.name != "openai-compatible" else ""
        print(f"{option.name}\t{'installed' if not binary or shutil.which(binary) else 'missing'}\t{option.command}")
    return 0
