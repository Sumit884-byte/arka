"""Small, inspectable multi-agent society: propose, debate, vote."""

from __future__ import annotations
import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Agent:
    name: str
    role: str
    weight: int


AGENTS = (
    Agent("architect", "architecture and tradeoffs", 3),
    Agent("builder", "implementation feasibility", 2),
    Agent("skeptic", "risks and failure modes", 3),
    Agent("user_advocate", "user value and clarity", 2),
)


def simulate(topic: str) -> dict:
    proposals = [
        {
            "agent": a.name,
            "role": a.role,
            "proposal": f"Evaluate {topic} through {a.role}.",
        }
        for a in AGENTS
    ]
    debate = [
        {
            "agent": "skeptic",
            "challenge": "What is the smallest reversible experiment, and what could fail?",
        },
        {
            "agent": "architect",
            "response": "Prefer explicit boundaries, observable decisions, and a rollback path.",
        },
    ]
    votes = [
        {"agent": a.name, "weight": a.weight, "choice": "proceed_with_guardrails"}
        for a in AGENTS
    ]
    return {
        "topic": topic,
        "agents": [a.__dict__ for a in AGENTS],
        "proposals": proposals,
        "debate": debate,
        "votes": votes,
        "decision": "proceed_with_guardrails",
        "confidence": 0.75,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="arka society",
        description="Run a propose/debate/vote multi-agent simulation",
    )
    p.add_argument("topic", nargs="+")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--generate",
        action="store_true",
        help="generate implementation code from the decision",
    )
    p.add_argument("--output", help="write generated code to a new file")
    args = p.parse_args(argv)
    result = simulate(" ".join(args.topic))
    if args.generate:
        from arka.llm.hybrid import complete

        prompt = f"Implement this reviewed decision: {result['decision']} for {result['topic']}. Return only production-quality code."
        code = complete(
            "You are the builder agent in a reviewed multi-agent society.",
            prompt,
            task="coding",
            skill="society",
            policy="local-first",
        )
        if args.output:
            target = Path(args.output).expanduser()
            if target.exists():
                print(f"Refusing to overwrite existing file: {target}")
                return 1
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code + "\n", encoding="utf-8")
            print(f"Generated code: {target}")
        else:
            print(code)
    elif args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"topic\t{result['topic']}\ndecision\t{result['decision']}\nconfidence\t{result['confidence']}"
        )
        for vote in result["votes"]:
            print(f"vote\t{vote['agent']}\t{vote['choice']}\tweight={vote['weight']}")
    return 0
