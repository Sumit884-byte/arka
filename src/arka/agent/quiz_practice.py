#!/usr/bin/env python3
"""Infinite quiz practice with per-topic memory to avoid repeating questions."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

GENERATE_SYSTEM_PROMPT = """You are a quiz tutor. Generate exactly ONE clear quiz question on the given topic.

Rules:
- Question should test understanding, not trivia unless the topic warrants it
- Vary difficulty and subtopics across sessions
- Do NOT repeat or closely paraphrase any question listed under "Previously asked"
- Output ONLY these two lines (no markdown, no extra text):
QUESTION: <the question>
HINT: <optional one-line hint, or "none">
"""

SCORE_SYSTEM_PROMPT = """You grade a quiz answer fairly and concisely.

Output ONLY these lines (no markdown):
SCORE: <integer 0-100>
CORRECT: <yes|no|partial>
FEEDBACK: <1-2 sentences on the user's answer>
ANSWER: <the correct or model answer>
EXPLANATION: <brief explanation>
"""

_QUIZ_PREFIXES = (
    r"(?i)^(?:please\s+)?(?:arka\s+)?(?:quiz\s+practice|practice\s+quiz)\s+",
    r"(?i)^(?:please\s+)?arka\s+quiz\s+",
    r"(?i)^quiz\s+me\s+(?:on\s+)?",
    r"(?i)^(?:practice|study)\s+quiz\s+(?:on\s+)?",
    r"(?i)^quiz_practice\s+",
    r"(?i)^quiz\s+",
)

_QUIZ_EXCLUDE = re.compile(
    r"(?i)\b(?:"
    r"quizlet|quiz\s+show|pub\s+quiz|buzzfeed|personality\s+quiz|"
    r"download|install|setup|configure"
    r")\b"
)


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def memory_root() -> Path:
    return _config_dir() / "quiz-memory"


def topic_slug(topic: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", (topic or "").strip().lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:80] or "topic"


def _memory_path(topic: str) -> Path:
    return memory_root() / f"{topic_slug(topic)}.json"


def load_memory(topic: str) -> dict:
    path = _memory_path(topic)
    if not path.is_file():
        return {
            "topic": topic.strip(),
            "asked": [],
            "scores": [],
            "last_at": None,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "topic": topic.strip(),
            "asked": [],
            "scores": [],
            "last_at": None,
        }
    data.setdefault("topic", topic.strip())
    data.setdefault("asked", [])
    data.setdefault("scores", [])
    data.setdefault("last_at", None)
    return data


def save_memory(data: dict) -> None:
    root = memory_root()
    root.mkdir(parents=True, exist_ok=True)
    topic = str(data.get("topic") or "topic").strip()
    data["topic"] = topic
    data["last_at"] = datetime.now(timezone.utc).isoformat()
    path = _memory_path(topic)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def reset_memory(topic: str) -> bool:
    path = _memory_path(topic)
    if path.is_file():
        path.unlink()
        return True
    return False


def list_topics() -> list[tuple[str, int, str | None]]:
    root = memory_root()
    if not root.is_dir():
        return []
    out: list[tuple[str, int, str | None]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        topic = str(data.get("topic") or path.stem)
        asked = data.get("asked") or []
        last_at = data.get("last_at")
        out.append((topic, len(asked), last_at))
    return out


def normalize_question(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    t = re.sub(r"[^\w\s]", "", t)
    return t


def is_duplicate(question: str, asked: list[str]) -> bool:
    norm = normalize_question(question)
    if not norm:
        return True
    for prev in asked:
        if normalize_question(prev) == norm:
            return True
    return False


def _strip_topic_prefix(text: str) -> str:
    t = text.strip()
    for pat in _QUIZ_PREFIXES:
        t = re.sub(pat, "", t).strip()
    return t.strip("'\"")


def _is_quiz_request(text: str) -> bool:
    t = text.strip()
    if not t or _QUIZ_EXCLUDE.search(t):
        return False
    if re.match(r"(?i)^quiz_practice\b", t):
        rest = re.sub(r"(?i)^quiz_practice\s+", "", t).strip()
        return rest.lower() in {"list", "help"} or bool(rest)
    if re.match(r"(?i)^(?:quiz|quiz\s+practice|practice\s+quiz)\s+\S", t):
        return True
    if re.match(r"(?i)^(?:please\s+)?arka\s+quiz\s+\S", t):
        return True
    if re.search(r"(?i)\bquiz\s+me\s+(?:on\s+)?\S", t):
        return True
    if re.search(r"(?i)\bpractice\s+quiz\s+\S", t):
        return True
    if re.search(r"(?i)\b(?:arka\s+)?quiz\s+practice\s+\S", t):
        return True
    return False


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_quiz_request(t):
        return []
    if re.match(r"(?i)^quiz_practice\s+list\b", t):
        return ["list"]
    topic = _strip_topic_prefix(t)
    if not topic or topic.lower() == "list":
        return ["list"] if topic.lower() == "list" else []
    return [topic]


def _parse_llm_field(text: str, key: str) -> str:
    m = re.search(rf"(?im)^{re.escape(key)}:\s*(.+)$", text)
    return (m.group(1).strip() if m else "")


def _llm_complete(system_prompt: str, user: str, *, skill: str = "quiz_practice") -> str:
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system_prompt,
            user,
            temperature=0.5,
            task="chat",
            skill=skill,
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system_prompt, user, temperature=0.5, task="chat").strip()


def generate_question(topic: str, asked: list[str]) -> tuple[str, str]:
    """Return (question, hint). Raises RuntimeError on failure."""
    prev = "\n".join(f"- {q}" for q in asked[-50:]) or "(none yet)"
    user = f"Topic: {topic}\n\nPreviously asked:\n{prev}"
    raw = _llm_complete(GENERATE_SYSTEM_PROMPT, user)
    if not raw:
        raise RuntimeError("LLM returned empty response")
    question = _parse_llm_field(raw, "QUESTION") or raw.strip().splitlines()[0].strip()
    hint = _parse_llm_field(raw, "HINT")
    if hint.lower() == "none":
        hint = ""
    question = question.strip()
    if not question:
        raise RuntimeError("Could not parse question from LLM output")
    return question, hint


def score_answer(topic: str, question: str, user_answer: str) -> dict[str, str]:
    user = (
        f"Topic: {topic}\n"
        f"Question: {question}\n"
        f"User answer: {user_answer or '(no answer)'}"
    )
    raw = _llm_complete(SCORE_SYSTEM_PROMPT, user, skill="quiz_practice")
    if not raw:
        raise RuntimeError("LLM returned empty score")
    return {
        "score": _parse_llm_field(raw, "SCORE") or "?",
        "correct": _parse_llm_field(raw, "CORRECT") or "?",
        "feedback": _parse_llm_field(raw, "FEEDBACK"),
        "answer": _parse_llm_field(raw, "ANSWER"),
        "explanation": _parse_llm_field(raw, "EXPLANATION"),
    }


def _read_answer() -> str:
    if not sys.stdin.isatty():
        return ""
    try:
        print("\nYour answer (Ctrl+C or empty to stop): ", end="", flush=True)
        line = sys.stdin.readline()
        if not line:
            return ""
        return line.rstrip("\n")
    except (EOFError, KeyboardInterrupt):
        print()
        raise KeyboardInterrupt from None


def _print_question(topic: str, question: str, hint: str, *, index: int) -> None:
    print("━━━ Quiz Practice ━━━")
    print(f"Topic: {topic}")
    print(f"Question #{index}")
    print()
    print(question)
    if hint:
        print(f"\nHint: {hint}")


def _print_score(result: dict[str, str]) -> None:
    print()
    print("─── Result ───")
    print(f"Score:   {result.get('score', '?')}/100 ({result.get('correct', '?')})")
    if result.get("feedback"):
        print(f"Feedback: {result['feedback']}")
    if result.get("answer"):
        print(f"Answer:   {result['answer']}")
    if result.get("explanation"):
        print(f"Explain:  {result['explanation']}")


def _unique_question(topic: str, asked: list[str], *, max_tries: int = 3) -> tuple[str, str]:
    last_err: Exception | None = None
    for _ in range(max_tries):
        try:
            question, hint = generate_question(topic, asked)
        except RuntimeError as exc:
            last_err = exc
            continue
        if not is_duplicate(question, asked):
            return question, hint
    if last_err:
        raise last_err
    raise RuntimeError("Could not generate a unique question (try --reset)")


def quiz_practice(
    topic: str,
    *,
    reset: bool = False,
    count: int | None = None,
) -> int:
    topic = " ".join((topic or "").split()).strip()
    if not topic:
        print(
            "Usage: quiz_practice <topic> [--reset] [--count N]\n"
            "       quiz_practice list\n"
            "Examples:\n"
            "  quiz_practice python\n"
            "  quiz_practice rust loops --count 1\n"
            "  arka quiz me on world history",
            file=sys.stderr,
        )
        return 1

    if reset:
        reset_memory(topic)
        print(f"Reset quiz memory for: {topic}")

    memory = load_memory(topic)
    memory["topic"] = topic
    asked: list[str] = list(memory.get("asked") or [])
    scores: list[dict] = list(memory.get("scores") or [])

    remaining = count if count is not None else None
    interactive = count is None or sys.stdin.isatty()

    try:
        while True:
            if remaining is not None and remaining <= 0:
                break

            try:
                question, hint = _unique_question(topic, asked)
            except RuntimeError as exc:
                print(f"✗ {exc}", file=sys.stderr)
                print("Check GEMINI_API_KEY or GROQ_API_KEY.", file=sys.stderr)
                return 1

            index = len(asked) + 1
            _print_question(topic, question, hint, index=index)

            user_answer = ""
            result: dict[str, str] | None = None
            if interactive:
                try:
                    user_answer = _read_answer()
                except KeyboardInterrupt:
                    print("\nStopped.")
                    break
                if not user_answer.strip():
                    print("Skipped.")
                    if count is None:
                        break

            if user_answer.strip():
                try:
                    result = score_answer(topic, question, user_answer)
                    _print_score(result)
                except RuntimeError as exc:
                    print(f"✗ Could not score answer: {exc}", file=sys.stderr)

            asked.append(question)
            entry: dict = {"question": question, "at": datetime.now(timezone.utc).isoformat()}
            if user_answer.strip():
                entry["user_answer"] = user_answer.strip()
            if result:
                entry.update(result)
            scores.append(entry)
            memory["asked"] = asked
            memory["scores"] = scores
            save_memory(memory)

            if count is not None:
                remaining = (remaining or 1) - 1
                if remaining <= 0:
                    break
                if interactive and sys.stdin.isatty():
                    print("\n--- Next question ---\n")
                continue

            if not interactive or not sys.stdin.isatty():
                break

            print("\n--- Next question (Ctrl+C to stop) ---\n")

    except KeyboardInterrupt:
        print("\nStopped.")
        return 0

    return 0


def cmd_list() -> int:
    topics = list_topics()
    if not topics:
        print("No quiz topics yet. Start one: arka quiz python")
        return 0
    print("━━━ Quiz Topics ━━━")
    for topic, n, last_at in topics:
        last = last_at[:10] if last_at else "—"
        print(f"  {topic}: {n} question(s)  (last: {last})")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Infinite quiz practice with topic memory")
    sub = p.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse natural language → quiz_practice args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "parse":
        args = build_parser().parse_args(argv)
        return args.func(args)

    if argv and argv[0] in {"-h", "--help", "help"}:
        build_parser().print_help()
        print("\nExamples:", file=sys.stderr)
        print("  quiz_practice python", file=sys.stderr)
        print("  quiz_practice biology mitosis --count 1", file=sys.stderr)
        print("  quiz_practice list", file=sys.stderr)
        return 0

    if argv and argv[0].lower() == "list":
        return cmd_list()

    reset = False
    count: int | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--reset":
            reset = True
            i += 1
            continue
        if tok == "--count" and i + 1 < len(argv):
            try:
                count = max(1, int(argv[i + 1]))
            except ValueError:
                print("Invalid --count value", file=sys.stderr)
                return 1
            i += 2
            continue
        rest.append(tok)
        i += 1

    topic = " ".join(rest).strip()
    nl = nl_to_argv(topic) if topic else []
    if nl:
        if nl[0] == "list":
            return cmd_list()
        topic = nl[0]

    return quiz_practice(topic, reset=reset, count=count)


if __name__ == "__main__":
    raise SystemExit(main())
