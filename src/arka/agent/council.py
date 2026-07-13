#!/usr/bin/env python3
"""Arka Council — multi-persona deliberation chamber."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arka.agent.personas.io import resolve_persona
from arka.agent.personas.schema import AI_VERIFICATION_NOTE, Persona, effective_system_prompt
from arka.routing.council import extract_question, is_council_request

DEFAULT_COUNCIL_MEMBERS: tuple[str, ...] = ("socrates", "elon", "feynman")

COUNCIL_ANSWER_INSTRUCTION = (
    "You are deliberating in Arka Council on a shared question.\n"
    "Answer in exactly 2-3 short sentences, first person.\n"
    "Give your genuine perspective — no preamble, no disclaimers.\n"
    "Do not mention other council members."
)

SYNTHESIS_SYSTEM_PROMPT = f"""You synthesize an Arka Council deliberation.
Given a question and independent answers from simulated expert personas,
write a brief synthesis for the user.

Output ONLY these lines (no markdown, no extra text):
CONSENSUS: <1-2 sentences on where the voices agree>
TENSION: <1-2 sentences on the main disagreement or tradeoff>
VERDICT: <1 direct, actionable sentence for the user>

{AI_VERIFICATION_NOTE}
"""


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def memory_path() -> Path:
    return _config_dir() / "council-memory.json"


def load_memory() -> dict[str, Any]:
    path = memory_path()
    if not path.is_file():
        return {"sessions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sessions": []}
    if not isinstance(data, dict):
        return {"sessions": []}
    data.setdefault("sessions", [])
    return data


def save_memory(data: dict[str, Any]) -> None:
    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_question(question: str) -> str:
    text = " ".join((question or "").split()).strip().lower()
    return text.rstrip("?.!")


def is_duplicate(question: str, sessions: list[dict[str, Any]]) -> bool:
    norm = normalize_question(question)
    if not norm:
        return True
    for entry in sessions:
        prev = normalize_question(str(entry.get("question") or ""))
        if prev and prev == norm:
            return True
    return False


def record_session(question: str, members: list[str]) -> bool:
    """Append question to memory unless duplicate. Returns True if recorded."""
    data = load_memory()
    sessions: list[dict[str, Any]] = list(data.get("sessions") or [])
    if is_duplicate(question, sessions):
        return False
    sessions.append(
        {
            "question": question.strip(),
            "members": members,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    data["sessions"] = sessions[-200:]
    save_memory(data)
    return True


def list_sessions() -> list[dict[str, Any]]:
    sessions = load_memory().get("sessions") or []
    return list(reversed(sessions))


def format_session_list() -> str:
    sessions = list_sessions()
    if not sessions:
        return "Arka Council history\n(no past deliberations yet)"
    lines = ["Arka Council history", ""]
    for idx, entry in enumerate(sessions, start=1):
        q = str(entry.get("question") or "").strip()
        at = str(entry.get("at") or "")[:19].replace("T", " ")
        members = ", ".join(entry.get("members") or [])
        lines.append(f"{idx}. {q}")
        if at:
            lines.append(f"   {at}" + (f" · {members}" if members else ""))
    return "\n".join(lines)


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not is_council_request(t):
        return []
    if re.match(r"(?i)^council\s+list\b", t):
        return ["list"]
    question = extract_question(t)
    if not question:
        return []
    return [question]


def resolve_council_members(names: list[str] | None = None) -> list[Persona]:
    slugs = list(names or DEFAULT_COUNCIL_MEMBERS)
    personas: list[Persona] = []
    for slug in slugs:
        try:
            personas.append(resolve_persona(slug))
        except (FileNotFoundError, ValueError):
            continue
    return personas


def member_system_prompt(persona: Persona) -> str:
    base = effective_system_prompt(persona)
    return f"{base}\n\n{COUNCIL_ANSWER_INSTRUCTION}"


def member_user_prompt(question: str) -> str:
    return f"Council question:\n{question.strip()}"


def synthesis_user_prompt(question: str, answers: list[tuple[Persona, str]]) -> str:
    lines = [f"Question: {question.strip()}", "", "Council answers:"]
    for persona, answer in answers:
        label = persona.display_name or persona.name
        lines.append(f"\n{label}:\n{answer.strip()}")
    return "\n".join(lines)


def _llm_complete(system_prompt: str, user: str, *, skill: str, temperature: float = 0.7) -> str:
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system_prompt,
            user,
            temperature=temperature,
            task="chat",
            skill=skill,
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system_prompt, user, temperature=temperature, task="chat").strip()


def _parse_synthesis_field(text: str, key: str) -> str:
    match = re.search(rf"(?im)^{re.escape(key)}:\s*(.+)$", text)
    return (match.group(1).strip() if match else "")


def deliberate_member(persona: Persona, question: str) -> tuple[Persona, str]:
    reply = _llm_complete(
        member_system_prompt(persona),
        member_user_prompt(question),
        skill=f"council:{persona.name}",
        temperature=0.75,
    )
    return persona, reply


def synthesize_deliberation(question: str, answers: list[tuple[Persona, str]]) -> dict[str, str]:
    raw = _llm_complete(
        SYNTHESIS_SYSTEM_PROMPT,
        synthesis_user_prompt(question, answers),
        skill="council",
        temperature=0.4,
    )
    if not raw:
        raise RuntimeError("LLM returned empty synthesis")
    return {
        "consensus": _parse_synthesis_field(raw, "CONSENSUS"),
        "tension": _parse_synthesis_field(raw, "TENSION"),
        "verdict": _parse_synthesis_field(raw, "VERDICT"),
        "raw": raw.strip(),
    }


def format_chamber(
    question: str,
    answers: list[tuple[Persona, str]],
    synthesis: dict[str, str],
) -> str:
    lines = ["━━━ Arka Council ━━━", f"Question: {question.strip()}", ""]
    for persona, answer in answers:
        label = persona.display_name or persona.name
        lines.append(f"── {label} ──")
        body = " ".join(answer.split())
        lines.append(f"  {body}")
        lines.append("")
    lines.append("── Synthesis ──")
    consensus = synthesis.get("consensus") or synthesis.get("raw", "")
    tension = synthesis.get("tension") or ""
    verdict = synthesis.get("verdict") or ""
    if consensus:
        lines.append(f"  Consensus: {consensus}")
    if tension:
        lines.append(f"  Tension: {tension}")
    if verdict:
        lines.append(f"  Verdict: {verdict}")
    if not any((consensus, tension, verdict)):
        lines.append(f"  {synthesis.get('raw', '').strip()}")
    return "\n".join(lines).rstrip() + "\n"


def run_council(question: str, *, members: list[str] | None = None) -> str:
    question = " ".join((question or "").split()).strip()
    if not question:
        return ""

    personas = resolve_council_members(members)
    if not personas:
        raise RuntimeError("No council personas available (check persona templates)")

    answers: list[tuple[Persona, str]] = []
    with ThreadPoolExecutor(max_workers=len(personas)) as pool:
        futures = {pool.submit(deliberate_member, p, question): p for p in personas}
        for future in as_completed(futures):
            persona, reply = future.result()
            if reply:
                answers.append((persona, reply))

    order = {p.name: idx for idx, p in enumerate(personas)}
    answers.sort(key=lambda item: order.get(item[0].name, 999))

    if not answers:
        raise RuntimeError("Council returned no answers (check LLM API keys)")

    synthesis = synthesize_deliberation(question, answers)
    record_session(question, [p.name for p, _ in answers])
    return format_chamber(question, answers, synthesis)


def council_main(args: list[str]) -> int:
    if not args:
        print(
            "Usage: council <question>\n"
            "       council list\n"
            "Examples:\n"
            "  council should I learn Rust?\n"
            "  deliberate with arka on whether remote work is better",
            file=sys.stderr,
        )
        return 1

    if len(args) == 1 and args[0].lower() == "list":
        print(format_session_list())
        return 0

    question = " ".join(args).strip()
    if not question:
        print("Usage: council <question>", file=sys.stderr)
        return 1

    try:
        output = run_council(question)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not output:
        print("Could not run council (check LLM API keys)", file=sys.stderr)
        return 1

    print(output, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] == "parse":
        if len(args) < 2:
            return 0
        parsed = nl_to_argv(" ".join(args[1:]))
        if parsed:
            print(" ".join(shlex.quote(a) for a in parsed))
        return 0

    parser = argparse.ArgumentParser(prog="council", add_help=False)
    parser.add_argument("args", nargs="*", help="question or 'list'")
    ns, _unknown = parser.parse_known_args(args)
    return council_main(list(ns.args))


if __name__ == "__main__":
    raise SystemExit(main())
