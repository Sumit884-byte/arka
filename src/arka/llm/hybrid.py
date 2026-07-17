"""Coordinate local and hosted models through Arka's existing fallback engine."""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass

from arka.llm.fallback import llm_complete, ordered_model_candidates, provider_available

LOCAL = frozenset({"ollama", "vllm", "lmstudio", "exo"})
POLICIES = ("local-first", "hosted-first", "parallel", "local-only", "hosted-only")


@dataclass(frozen=True)
class HybridRoute:
    policy: str
    candidates: tuple[tuple[str, str], ...]
    local: tuple[tuple[str, str], ...]
    hosted: tuple[tuple[str, str], ...]


def _policy(value: str | None = None) -> str:
    raw = (value or os.environ.get("ARKA_MODEL_POLICY", "local-first")).strip().lower()
    aliases = {
        "local": "local-first",
        "offline": "local-only",
        "offline-only": "local-only",
        "run-only-local-llm": "local-only",
        "cloud": "hosted-first",
        "hosted": "hosted-first",
        "both": "parallel",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in POLICIES else "local-first"


def route(
    policy: str | None = None, *, task: str | None = None, skill: str | None = None
) -> HybridRoute:
    candidates = tuple(ordered_model_candidates(task=task, skill=skill))
    local = tuple(
        x for x in candidates if x[0].lower() in LOCAL and provider_available(x[0])
    )
    hosted = tuple(
        x for x in candidates if x[0].lower() not in LOCAL and provider_available(x[0])
    )
    selected = local + hosted if _policy(policy) == "local-first" else hosted + local
    if _policy(policy) == "local-only":
        selected = local
    elif _policy(policy) == "hosted-only":
        selected = hosted
    return HybridRoute(_policy(policy), tuple(selected), local, hosted)


def complete(
    system: str,
    user: str,
    *,
    policy: str | None = None,
    task: str | None = None,
    skill: str | None = None,
    temperature: float = 0.2,
) -> str:
    """Complete using local/hosted policy; parallel returns both independent answers."""
    from arka.llm.grounding import guard, instruction, minimize_data

    grounded, reason = guard(user)
    if not grounded:
        return f"[LLM blocked by grounding policy: {reason}]"
    user = minimize_data(user)
    system = f"{system}\n\n{instruction(user)}".strip()
    chosen = route(policy, task=task, skill=skill)
    from arka.llm.guardrails import preflight, record

    allowed, reason = preflight(
        user, hosted=any(p not in LOCAL for p, _ in chosen.candidates)
    )
    if not allowed:
        return f"[LLM blocked by guardrail: {reason}]"
    started = time.perf_counter()
    if not chosen.candidates:
        return "[LLM error: no configured local or hosted model]"
    if chosen.policy == "parallel":
        answers: list[str] = []
        for provider, model in chosen.local[:1] + chosen.hosted[:1]:
            text = llm_complete(
                system,
                user,
                temperature,
                task=task,
                skill=skill,
                chain=[(provider, model)],
            )
            if not text.startswith("[LLM error:"):
                answers.append(f"[{provider}/{model}]\n{text}")
        result = (
            "\n\n".join(answers)
            if answers
            else "[LLM error: local and hosted models failed]"
        )
    else:
        result = llm_complete(
            system,
            user,
            temperature,
            task=task,
            skill=skill,
            chain=list(chosen.candidates),
        )
    record(
        user,
        latency_ms=(time.perf_counter() - started) * 1000,
        hosted=any(p not in LOCAL for p, _ in chosen.candidates),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka hybrid", description="Use local and hosted models together"
    )
    sub = parser.add_subparsers(dest="command")
    status = sub.add_parser("status", help="show available local/hosted routes")
    status.add_argument("--policy", default=None)
    run = sub.add_parser("run", help="run a prompt through the hybrid policy")
    run.add_argument("prompt", nargs="+")
    run.add_argument("--policy", default=None, choices=POLICIES)
    run.add_argument("--task", default="chat")
    run.add_argument(
        "--local-only", action="store_true", help="never call hosted providers"
    )
    config = sub.add_parser("config", help="persist the default model policy")
    config.add_argument("policy", choices=POLICIES)
    args = parser.parse_args(argv or ["status"])
    if args.command in (None, "status"):
        chosen = route(getattr(args, "policy", None))
        print(f"policy: {chosen.policy}")
        print(f"local: {', '.join(f'{p}/{m}' for p, m in chosen.local) or 'none'}")
        print(f"hosted: {', '.join(f'{p}/{m}' for p, m in chosen.hosted) or 'none'}")
        return 0
    if args.command == "config":
        from arka.llm.provider_select import set_env_vars

        set_env_vars({"ARKA_MODEL_POLICY": args.policy})
        print(f"model policy set: {args.policy}")
        return 0
    policy = "local-only" if getattr(args, "local_only", False) else args.policy
    print(
        complete("You are Arka.", " ".join(args.prompt), policy=policy, task=args.task)
    )
    return 0
