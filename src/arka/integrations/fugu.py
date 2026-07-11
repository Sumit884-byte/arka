#!/usr/bin/env python3
"""Sakana Fugu orchestrator integration — OpenAI-compatible multi-agent API."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys

PROVIDER = "sakana"
DEFAULT_MODEL = "fugu"
ULTRA_MODEL = "fugu-ultra"
DEFAULT_BASE_URL = "https://api.sakana.ai/v1"

SETUP_HINT = (
    "Sakana Fugu is not configured.\n"
    "  1. Create an API key at https://console.sakana.ai\n"
    "  2. Add SAKANA_API_KEY to ~/.config/arka/.env\n"
    "  3. Run: arka fugu status"
)


def sakana_configured() -> bool:
    try:
        from arka.llm.api_keys import provider_has_keys

        return provider_has_keys(PROVIDER)
    except ImportError:
        return bool(os.environ.get("SAKANA_API_KEY", "").strip())


def wants_fugu(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if re.match(r"(?i)^(?:arka\s+)?fugu(?:_cli)?(?:\s+status|\s+sync|\s+help|\s+--help)?$", clean):
        return True
    if re.match(r"(?i)^fugu(?:_cli)?\b", clean):
        return True
    if re.match(r"(?i)^(?:arka\s+)?fugu\s+\S", clean):
        return True
    if re.search(r"(?i)\b(?:ask|use|run)\s+fugu\b", clean):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_fugu(text):
        return ""
    clean = (text or "").strip()
    if re.match(r"(?i)^(?:arka\s+)?fugu(?:_cli)?\s+status$", clean):
        return "fugu status"
    if re.match(r"(?i)^(?:arka\s+)?fugu(?:_cli)?\s+sync$", clean):
        return "fugu sync"
    m = re.match(r"(?i)^(?:arka\s+)?(?:fugu_cli|fugu)\s+(.+)$", clean)
    if m:
        rest = m.group(1).strip()
        if rest:
            return "fugu " + shlex.quote(rest)
    m = re.search(r"(?i)\b(?:ask|use|run)\s+fugu\s+(?:to\s+)?(.+)$", clean)
    if m:
        return "fugu " + shlex.quote(m.group(1).strip())
    return "fugu " + shlex.quote(clean)


def nl_to_argv(text: str) -> list[str] | None:
    route = route_command(text)
    if not route:
        return None
    return shlex.split(route)[1:]


def _resolve_model(argv: list[str]) -> tuple[str, list[str]]:
    if not argv:
        return DEFAULT_MODEL, []
    if argv[0].lower() in {"ultra", "fugu-ultra"}:
        rest = argv[1:]
        return ULTRA_MODEL, rest
    if argv[0].lower() == "fugu" and len(argv) > 1:
        return DEFAULT_MODEL, argv[1:]
    return DEFAULT_MODEL, argv


def _fugu_chain(model: str) -> str:
    return f"{PROVIDER}:{model}"


def fugu_complete(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    system: str = "You are a helpful assistant.",
    task: str = "fugu",
) -> str:
    """Run a one-shot prompt through Sakana Fugu via Arka's LLM stack."""
    prev = os.environ.get("LLM_FALLBACK")
    os.environ["LLM_FALLBACK"] = _fugu_chain(model)
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(system, prompt, task=task, skill="fugu")
    finally:
        if prev is None:
            os.environ.pop("LLM_FALLBACK", None)
        else:
            os.environ["LLM_FALLBACK"] = prev


def cmd_status(_args: argparse.Namespace) -> int:
    from arka.llm.providers import get_provider, provider_base_url

    spec = get_provider(PROVIDER)
    configured = sakana_configured()
    print(f"fugu\t{'configured' if configured else 'not_configured'}")
    if spec:
        print(f"provider\t{spec.slug}")
        print(f"display_name\t{spec.display_name}")
        print(f"base_url\t{provider_base_url(spec) or DEFAULT_BASE_URL}")
        print(f"default_model\t{spec.default_model}")
        print(f"models\t{','.join(spec.default_models)}")
    if configured:
        print("auth\tSAKANA_API_KEY set")
    else:
        print(f"hint\t{SETUP_HINT.replace(chr(10), ' ')}")
    print("codex\tSAKANA_API_KEY={key} codex -p fugu")
    print("hub_sync\tarka fugu sync  # export Arka MCP/memory/skills for Codex")
    return 0 if configured else 1


def cmd_sync(args: argparse.Namespace) -> int:
    from arka.integrations.agent_hub import sync_all

    result = sync_all(unify=args.unify, replace=args.replace)
    print(f"sync\tok")
    print(f"synced_at\t{result.get('synced_at')}")
    if args.unify:
        for row in result.get("unify_mcp") or []:
            if row.get("agent") == "fugu":
                print(
                    f"unify_mcp\t{row.get('path')}\t"
                    f"added={','.join(row.get('added') or [])}"
                )
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])

    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    if raw and raw[0] == "status":
        return cmd_status(argparse.Namespace())

    if raw and raw[0] == "sync":
        unify = "--unify" in raw[1:]
        replace = "--replace" in raw[1:]
        return cmd_sync(argparse.Namespace(unify=unify, replace=replace))

    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    if not sakana_configured():
        print(SETUP_HINT, file=sys.stderr)
        return 1

    model, rest = _resolve_model(raw)
    prompt = " ".join(rest).strip()
    if not prompt:
        print("Usage: arka fugu <prompt>", file=sys.stderr)
        print("       arka fugu ultra <prompt>", file=sys.stderr)
        return 2

    text = fugu_complete(prompt, model=model)
    if text.startswith("[LLM error:"):
        print(text, file=sys.stderr)
        return 1
    print(text)
    return 0


def _print_help() -> None:
    print(
        """Sakana Fugu orchestrator for Arka

Usage:
  arka fugu <prompt>                Query Fugu (fast multi-agent orchestration)
  arka fugu ultra <prompt>          Query Fugu Ultra (deeper orchestration)
  arka fugu status                  Check API key + provider config
  arka fugu sync [--unify]          Export Arka hub for Codex/Fugu MCP bridge

Setup:
  1. Create API key: https://console.sakana.ai
  2. Add SAKANA_API_KEY to ~/.config/arka/.env
  3. Point Codex at Fugu: curl -fsSL https://sakana.ai/fugu/install | bash
  4. Share Arka tools: arka fugu sync --unify

Teams:
  kind: model, id: fugu, provider: sakana
  kind: provider, id: sakana

MCP:
  External orchestrators can call Arka via: arka mcp serve
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
