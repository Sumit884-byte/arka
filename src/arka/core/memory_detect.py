#!/usr/bin/env python3
"""Symbolic-logic autodetection of long-term memories from natural language."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir():
        return __import__("pathlib").Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass

MEMORY_FILE = cache_dir() / "memory.json"

FIRST_PERSON_RE = re.compile(r"\b(i|i'm|i am|my|me|mine|myself)\b", re.I)
QUESTION_START_RE = re.compile(
    r"^(?:what|who|where|when|why|how|which|can you|could you|would you|"
    r"do you|does|did|is|are|was|were|tell me about|explain)\b",
    re.I,
)
COMMAND_START_RE = re.compile(
    r"^(?:play|open|run|install|download|search|find|show|list|set|start|stop|"
    r"timer|translate|generate|create|make|summarize|ingest|fix|help|clear|reset|"
    r"remember|recall|memorize|forget|agent)\b",
    re.I,
)
HYPOTHETICAL_RE = re.compile(r"\b(if i|what if|suppose i|imagine i|would i)\b", re.I)
EPHEMERAL_RE = re.compile(
    r"\b(right now|at the moment|today|tonight|this morning|this evening|"
    r"just now|currently looking|for now)\b",
    re.I,
)
PASSWORD_RE = re.compile(r"\b(password|passcode|pin)\b", re.I)
RECALL_RE = re.compile(
    r"(?i)^(recall|what do you remember|do you remember|what did i tell you)",
)
EXPLICIT_REMEMBER_RE = re.compile(
    r"(?i)^(?:remember|memorize|store|don't forget|dont forget|keep in mind)\s+(?:that\s+)?",
)


@dataclass(frozen=True)
class MemoryRule:
    """Symbolic rule: predicate(name) + pattern → normalized fact."""

    name: str
    predicate: str
    pattern: re.Pattern[str]
    template: str
    tags: tuple[str, ...] = ()
    min_len: int = 3


@dataclass
class DetectedMemory:
    text: str
    predicate: str
    rule: str
    tags: list[str]
    confidence: float


RULES: tuple[MemoryRule, ...] = (
    MemoryRule(
        "explicit_remember",
        "remember(user, fact)",
        EXPLICIT_REMEMBER_RE,
        "{rest}",
        ("explicit",),
    ),
    MemoryRule(
        "preference",
        "prefer(user, object)",
        re.compile(
            r"(?i)^(?:please\s+)?(?:i\s+)?(?:always\s+|usually\s+)?"
            r"(?:prefer|like(?:\s+to\s+use)?|love(?:\s+to\s+use)?|"
            r"hate(?:\s+using)?|dislike(?:\s+using)?|want(?:\s+to\s+use)?)\s+"
            r"(?:to\s+use\s+)?(?P<obj>.+)$"
        ),
        "User prefers {obj}",
        ("preference",),
    ),
    MemoryRule(
        "favorite",
        "favorite(user, category, value)",
        re.compile(
            r"(?i)^my\s+favorite\s+(?P<cat>\w+(?:\s+\w+)?)\s+is\s+(?P<val>.+)$"
        ),
        "User's favorite {cat} is {val}",
        ("preference", "favorite"),
    ),
    MemoryRule(
        "name_self",
        "named(user, name)",
        re.compile(r"(?i)^(?:i\s*'?m|i am)\s+(?:called|named)\s+(?P<name>.+)$"),
        "User's name is {name}",
        ("identity",),
    ),
    MemoryRule(
        "name_self_alt",
        "named(user, name)",
        re.compile(r"(?i)^my\s+name\s+is\s+(?P<name>.+)$"),
        "User's name is {name}",
        ("identity",),
    ),
    MemoryRule(
        "named_entity",
        "named(user.entity, name)",
        re.compile(
            r"(?i)^my\s+(?P<entity>dog|cat|pet|car|wife|husband|partner|son|daughter|"
            r"child|kid|friend|boss|company|team|project|laptop|phone)\s+"
            r"(?:is\s+(?:named|called)|'?s\s+name\s+is)\s+(?P<name>.+)$"
        ),
        "User's {entity} is named {name}",
        ("identity", "relation"),
    ),
    MemoryRule(
        "location_live",
        "live_in(user, place)",
        re.compile(
            r"(?i)^i\s+(?:live|stay|am based|work remotely)\s+in\s+(?P<place>.+)$"
        ),
        "User lives in {place}",
        ("location",),
    ),
    MemoryRule(
        "location_from",
        "from(user, place)",
        re.compile(r"(?i)^i\s*'?m\s+from\s+(?P<place>.+)$"),
        "User is from {place}",
        ("location",),
    ),
    MemoryRule(
        "location_city",
        "city(user, place)",
        re.compile(
            r"(?i)^my\s+(?:city|hometown|home town|office|workplace)\s+is\s+"
            r"(?:in\s+)?(?P<place>.+)$"
        ),
        "User's city is {place}",
        ("location",),
    ),
    MemoryRule(
        "work_at",
        "work_at(user, org)",
        re.compile(r"(?i)^i\s+work\s+(?:at|for)\s+(?P<org>.+)$"),
        "User works at {org}",
        ("work",),
    ),
    MemoryRule(
        "profession",
        "is_a(user, role)",
        re.compile(
            r"(?i)^i\s*'?m\s+a(?:n)?\s+(?P<role>developer|engineer|designer|student|"
            r"teacher|doctor|lawyer|manager|founder|freelancer|researcher|writer|"
            r"artist|musician|chef|nurse|accountant|consultant|programmer|data scientist)\b"
            r"(?:\s+(?:at|for|in)\s+(?P<org>.+))?$"
        ),
        "User is a {role}" + "{org_suffix}",
        ("work", "identity"),
    ),
    MemoryRule(
        "diet",
        "constraint(user, diet)",
        re.compile(r"(?i)^i\s*'?m\s+(?P<diet>a vegan|vegetarian|pescatarian|gluten[- ]free)\b.*$"),
        "User is {diet}",
        ("preference", "diet"),
    ),
    MemoryRule(
        "allergy",
        "allergic(user, substance)",
        re.compile(
            r"(?i)^i\s*'?m\s+allergic\s+to\s+(?P<substance>.+)$"
        ),
        "User is allergic to {substance}",
        ("health", "constraint"),
    ),
    MemoryRule(
        "language_pref",
        "speak_lang(user, lang)",
        re.compile(
            r"(?i)^(?:please\s+)?(?:speak|talk|reply|respond)\s+(?:to me\s+)?"
            r"(?:in|using)\s+(?P<lang>.+)$"
        ),
        "User prefers responses in {lang}",
        ("preference", "language"),
    ),
    MemoryRule(
        "model_pref",
        "prefer_model(user, model)",
        re.compile(
            r"(?i)^(?:please\s+)?(?:use|switch to|default to)\s+"
            r"(?P<model>gemini|groq|ollama|claude|gpt(?:-[\w.]+)?|llama[\w.-]*)\b"
            r"(?:\s+for\s+(?P<task>.+))?$"
        ),
        "User prefers {model}{task_suffix}",
        ("preference", "llm"),
    ),
    MemoryRule(
        "schedule",
        "event_at(user, event, time)",
        re.compile(
            r"(?i)^my\s+(?P<event>birthday|anniversary|meeting|appointment|interview|"
            r"flight|doctor\s+appointment)\s+is\s+(?:on|at)\s+(?P<when>.+)$"
        ),
        "User's {event} is {when}",
        ("schedule",),
    ),
    MemoryRule(
        "contact_email",
        "email(user, address)",
        re.compile(r"(?i)^my\s+email\s+(?:is|address is)\s+(?P<email>\S+@\S+)$"),
        "User's email is {email}",
        ("contact",),
    ),
    MemoryRule(
        "contact_phone",
        "phone(user, number)",
        re.compile(
            r"(?i)^my\s+(?:phone|mobile|cell)(?:\s+number)?\s+is\s+(?P<number>.+)$"
        ),
        "User's phone number is {number}",
        ("contact",),
    ),
    MemoryRule(
        "have_condition",
        "has(user, condition)",
        re.compile(
            r"(?i)^i\s+(?:have|deal with|suffer from|am dealing with)\s+"
            r"(?P<condition>.+)$"
        ),
        "User has {condition}",
        ("health",),
        min_len=8,
    ),
    MemoryRule(
        "birthday",
        "birthday(user, date)",
        re.compile(r"(?i)^my\s+birthday\s+is\s+(?P<date>.+)$"),
        "User's birthday is {date}",
        ("schedule", "identity"),
    ),
)


def autodetect_enabled() -> bool:
    raw = (os.environ.get("ARKA_MEMORY_AUTODETECT") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _load_existing() -> list[str]:
    try:
        if MEMORY_FILE.is_file():
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(r.get("text") or "").strip() for r in data if r.get("text")]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _word_set(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def is_duplicate(fact: str, existing: list[str] | None = None) -> bool:
    fact_n = fact.lower().strip()
    if not fact_n:
        return True
    pool = existing if existing is not None else _load_existing()
    for old in pool:
        old_n = old.lower().strip()
        if not old_n:
            continue
        if fact_n in old_n or old_n in fact_n:
            if min(len(fact_n), len(old_n)) >= 12:
                return True
        overlap = _word_set(fact) & _word_set(old)
        union = _word_set(fact) | _word_set(old)
        if union and len(overlap) / len(union) >= 0.85:
            return True
    return False


def _excluded(text: str) -> str | None:
    t = _normalize(text)
    if not t:
        return "empty"
    if RECALL_RE.search(t):
        return "recall"
    if PASSWORD_RE.search(t):
        return "password"
    if HYPOTHETICAL_RE.search(t):
        return "hypothetical"
    if t.endswith("?"):
        return "question"
    if QUESTION_START_RE.search(t) and not FIRST_PERSON_RE.search(t):
        return "question"
    if COMMAND_START_RE.search(t) and not FIRST_PERSON_RE.search(t):
        return "command"
    if EPHEMERAL_RE.search(t) and not re.search(
        r"\b(birthday|anniversary|meeting|appointment|allergic|live in|from)\b", t, re.I
    ):
        return "ephemeral"
    return None


def _format_fact(rule: MemoryRule, match: re.Match[str]) -> str:
    groups = {k: (v or "").strip().rstrip(".") for k, v in match.groupdict().items()}
    if rule.name == "explicit_remember":
        rest = EXPLICIT_REMEMBER_RE.sub("", _normalize(match.string)).strip()
        return _normalize_explicit(rest)
    if rule.name == "profession":
        role = groups.get("role", "")
        org = groups.get("org", "")
        groups["org_suffix"] = f" at {org}" if org else ""
        fact = f"User is a {role}{groups['org_suffix']}"
        return fact.strip()
    if rule.name == "model_pref":
        model = groups.get("model", "")
        task = groups.get("task", "")
        groups["task_suffix"] = f" for {task}" if task else ""
        return rule.template.format(model=model, task_suffix=groups["task_suffix"]).strip()
    try:
        return rule.template.format(**groups).strip()
    except KeyError:
        return ""


def _should_block(text: str) -> bool:
    """Exclusion predicates — reject questions, commands, hypotheticals, etc."""
    reason = _excluded(text)
    if not reason:
        return False
    if reason in ("question", "command") and FIRST_PERSON_RE.search(text):
        if re.match(r"(?i)^(?:i|my)\b", text) and not text.endswith("?"):
            return False
    return True


def _normalize_explicit(rest: str) -> str:
    """Re-run symbolic rules on explicit-remember payload for canonical facts."""
    for rule in RULES:
        if rule.name == "explicit_remember":
            continue
        m = rule.pattern.search(rest)
        if m:
            fact = _format_fact(rule, m)
            if fact and len(fact) >= rule.min_len:
                return fact
    return rest.strip()


def detect_memories(text: str, *, existing: list[str] | None = None) -> list[DetectedMemory]:
    """Apply symbolic rules; return facts worth storing (not yet deduped against store)."""
    raw = _normalize(text)
    if not raw or not autodetect_enabled():
        return []
    if _should_block(raw):
        return []

    hits: list[DetectedMemory] = []
    for rule in RULES:
        m = rule.pattern.search(raw)
        if not m:
            continue
        fact = _format_fact(rule, m)
        if len(fact) < rule.min_len:
            continue
        if is_duplicate(fact, existing):
            continue
        tags = list(rule.tags)
        conf = 0.95 if rule.name == "explicit_remember" else 0.85
        hits.append(
            DetectedMemory(
                text=fact,
                predicate=rule.predicate,
                rule=rule.name,
                tags=tags,
                confidence=conf,
            )
        )
        break  # highest-priority matching rule wins
    return hits


def auto_remember(text: str, *, quiet: bool = True) -> list[str]:
    """Detect and store memories. Returns list of stored fact strings."""
    if not autodetect_enabled():
        return []
    existing = _load_existing()
    stored: list[str] = []
    for hit in detect_memories(text, existing=existing + stored):
        try:
            from arka.agent.core import memory_remember_silent

            if memory_remember_silent(hit.text, tags=hit.tags):
                stored.append(hit.text)
                existing.append(hit.text)
                if not quiet:
                    print(f"Auto-remembered [{hit.rule}]: {hit.text}")
        except ImportError:
            break
    return stored


def extract_fact(text: str) -> str:
    """Return first detected fact for routing, or empty string."""
    hits = detect_memories(text)
    return hits[0].text if hits else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Symbolic memory autodetection")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_detect = sub.add_parser("detect", help="List detected facts (JSON lines)")
    p_detect.add_argument("text")

    p_extract = sub.add_parser("extract", help="Print first fact for shell routing")
    p_extract.add_argument("text")
    p_extract.add_argument("--quiet", action="store_true")

    p_auto = sub.add_parser("auto", help="Detect and store silently")
    p_auto.add_argument("text")
    p_auto.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    if args.cmd == "detect":
        for hit in detect_memories(args.text, existing=[]):
            print(json.dumps({"text": hit.text, "predicate": hit.predicate, "rule": hit.rule}))
        return 0
    if args.cmd == "extract":
        fact = extract_fact(args.text)
        if fact:
            print(fact)
        return 0
    if args.cmd == "auto":
        for fact in auto_remember(args.text, quiet=not args.verbose):
            if args.verbose:
                pass  # printed inside
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
