#!/usr/bin/env python3
"""Lightweight user habitat — infer domain/persona from chat for contextual answers."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def load_env_file() -> None:
        pass


VALID_DOMAINS = frozenset({"developer", "student", "ops", "general"})

DOMAIN_LABELS: dict[str, str] = {
    "developer": "software developer",
    "student": "student",
    "ops": "operations / SRE",
    "general": "general",
}

# Tech-context disambiguation for homographs in definitional queries.
_TECH_DISAMBIGUATION: dict[str, dict[str, str]] = {
    "developer": {
        "rust": "Rust programming language",
        "go": "Go Golang programming language",
        "swift": "Swift programming language",
        "d": "D programming language",
        "r": "R programming language",
        "c": "C programming language",
        "c++": "C++ programming language",
        "c#": "C# programming language",
        "python": "Python programming language",
        "java": "Java programming language",
    },
    "ops": {
        "rust": "Rust programming language",
        "go": "Go Golang programming language",
        "kubernetes": "Kubernetes container orchestration",
        "docker": "Docker containers",
        "terraform": "Terraform infrastructure as code",
    },
}

# Signal weights for inferring habitat from text.
_DOMAIN_SIGNALS: dict[str, tuple[tuple[re.Pattern[str], float], ...]] = {
    "developer": (
        (re.compile(r"\b(?:python|javascript|typescript|rust|golang|react|vue|angular)\b", re.I), 2.0),
        (re.compile(r"\b(?:git|github|gitlab|commit|pull request|pr|merge|branch)\b", re.I), 1.5),
        (re.compile(r"\b(?:api|sdk|library|framework|npm|pip|cargo|compile|debug|refactor)\b", re.I), 1.5),
        (re.compile(r"\b(?:software engineer|programmer|developer|coding|codebase|unit test)\b", re.I), 2.5),
        (re.compile(r"\b(?:typescript|sql|database schema|orm|frontend|backend|full[- ]?stack)\b", re.I), 1.5),
    ),
    "student": (
        (re.compile(r"\b(?:homework|assignment|exam|midterm|finals|thesis|dissertation)\b", re.I), 2.0),
        (re.compile(r"\b(?:professor|lecture|coursework|semester|campus|tuition|gpa)\b", re.I), 2.0),
        (re.compile(r"\b(?:study guide|textbook|quiz|lab report|research paper)\b", re.I), 1.5),
        (re.compile(r"\b(?:student|undergrad|graduate student|phd|college|university)\b", re.I), 2.0),
    ),
    "ops": (
        (re.compile(r"\b(?:kubernetes|k8s|terraform|ansible|pulumi|helm)\b", re.I), 2.5),
        (re.compile(r"\b(?:aws|gcp|azure|cloudflare|datadog|prometheus|grafana)\b", re.I), 2.0),
        (re.compile(r"\b(?:on[- ]?call|incident|outage|sre|devops|deploy(?:ment)?|ci/cd)\b", re.I), 2.0),
        (re.compile(r"\b(?:docker|container|kubectl|nginx|load balancer|uptime)\b", re.I), 1.5),
    ),
}

_EXPLICIT_HABITAT_RE = re.compile(
    r"(?i)^(?:my\s+habitat\s+is|set\s+habitat\s+to|i\s+work\s+in)\s+(?P<domain>\w+)\s*$"
)
_EXPLICIT_DOMAIN_RE = re.compile(
    r"(?i)^i\s*'?m\s+a(?:n)?\s+"
    r"(?P<role>software engineer|developer|programmer|devops engineer|sre|site reliability engineer|"
    r"student|teacher|professor|data scientist|sysadmin|operations engineer)\b"
)
_HABITAT_TRIGGERS = re.compile(
    r"(?i)\b(?:"
    r"my\s+habitat|"
    r"habitat\s+(?:status|show|set|reset|infer)|"
    r"what(?:'s|\s+is)\s+my\s+habitat|"
    r"what\s+context\s+am\s+i\s+in|"
    r"user\s+context|"
    r"set\s+habitat"
    r")\b"
)
_DEFINITIONAL_QUERY_RE = re.compile(
    r"(?i)^(?:what|who|where|when|why|how|explain|describe|tell\s+me\s+about)\s+"
    r"(?:is|are|was|were|does|do|did|me|us)?\s*(?:a|an|the)?\s*(.+?)\??$"
)


@dataclass
class HabitatState:
    domain: str = "general"
    confidence: float = 0.0
    signals: list[str] = field(default_factory=list)
    updated_at: float = 0.0
    manual: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "confidence": round(self.confidence, 3),
            "signals": self.signals[-12:],
            "updated_at": self.updated_at,
            "manual": self.manual,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HabitatState:
        if not data:
            return cls()
        domain = str(data.get("domain") or "general").lower()
        if domain not in VALID_DOMAINS:
            domain = "general"
        signals = data.get("signals")
        if not isinstance(signals, list):
            signals = []
        return cls(
            domain=domain,
            confidence=float(data.get("confidence") or 0.0),
            signals=[str(s) for s in signals[-12:]],
            updated_at=float(data.get("updated_at") or 0.0),
            manual=bool(data.get("manual")),
        )


def habitat_path() -> Path:
    return config_dir() / "habitat.json"


def load_habitat() -> HabitatState:
    path = habitat_path()
    if not path.is_file():
        seeded = _seed_from_personalize()
        if seeded.domain != "general":
            save_habitat(seeded)
        return seeded
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return HabitatState()
    if not isinstance(data, dict):
        return HabitatState()
    return HabitatState.from_dict(data)


def save_habitat(state: HabitatState) -> None:
    path = habitat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = time.time()
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")


def reset_habitat() -> None:
    path = habitat_path()
    if path.is_file():
        path.unlink()


def _seed_from_personalize() -> HabitatState:
    try:
        from arka.core.personalize import load_profile
    except ImportError:
        return HabitatState()
    profile = load_profile()
    interests = profile.get("interests") or []
    if "dev" in interests:
        return HabitatState(
            domain="developer",
            confidence=0.55,
            signals=["profile:dev"],
            manual=False,
        )
    if "research" in interests and "dev" not in interests:
        return HabitatState(domain="student", confidence=0.35, signals=["profile:research"])
    return HabitatState()


def score_text(text: str) -> dict[str, float]:
    """Return domain scores for a single message."""
    scores = {d: 0.0 for d in VALID_DOMAINS if d != "general"}
    blob = (text or "").strip()
    if not blob:
        return scores
    for domain, patterns in _DOMAIN_SIGNALS.items():
        for pat, weight in patterns:
            if pat.search(blob):
                scores[domain] += weight
    explicit = _EXPLICIT_DOMAIN_RE.search(blob)
    if explicit:
        role = explicit.group("role").lower()
        if role in {"software engineer", "developer", "programmer", "data scientist"}:
            scores["developer"] += 4.0
        elif role in {"devops engineer", "sre", "site reliability engineer", "sysadmin", "operations engineer"}:
            scores["ops"] += 4.0
        elif role in {"student", "teacher", "professor"}:
            scores["student"] += 4.0
    habitat_explicit = _EXPLICIT_HABITAT_RE.match(blob.strip())
    if habitat_explicit:
        dom = habitat_explicit.group("domain").lower()
        if dom in VALID_DOMAINS and dom != "general":
            scores[dom] = scores.get(dom, 0.0) + 5.0
    return scores


def infer_from_messages(messages: list[str]) -> tuple[str, float, list[str]]:
    """Aggregate habitat from recent user messages."""
    totals = {d: 0.0 for d in VALID_DOMAINS if d != "general"}
    hit_signals: list[str] = []
    for msg in messages[-20:]:
        for domain, score in score_text(msg).items():
            totals[domain] += score
            if score >= 1.5:
                hit_signals.append(f"chat:{domain}")
    if not any(totals.values()):
        return "general", 0.0, []
    best = max(totals, key=lambda d: totals[d])
    total = sum(totals.values()) or 1.0
    confidence = min(0.95, totals[best] / total)
    if totals[best] < 1.5:
        return "general", 0.0, []
    return best, confidence, hit_signals[-8:]


def update_from_message(text: str, *, quiet: bool = True) -> HabitatState:
    """Update habitat from a user turn (background inference)."""
    blob = (text or "").strip()
    if not blob:
        return load_habitat()
    state = load_habitat()
    if state.manual:
        return state
    explicit = _EXPLICIT_HABITAT_RE.match(blob)
    if explicit:
        dom = explicit.group("domain").lower()
        if dom in VALID_DOMAINS:
            state.domain = dom
            state.confidence = 0.95
            state.signals = [f"explicit:{dom}"]
            state.manual = dom != "general"
            save_habitat(state)
            return state
    role_m = _EXPLICIT_DOMAIN_RE.search(blob)
    if role_m:
        role = role_m.group("role").lower()
        dom = "general"
        if role in {"software engineer", "developer", "programmer", "data scientist"}:
            dom = "developer"
        elif role in {"devops engineer", "sre", "site reliability engineer", "sysadmin", "operations engineer"}:
            dom = "ops"
        elif role in {"student", "teacher", "professor"}:
            dom = "student"
        if dom != "general":
            state.domain = dom
            state.confidence = 0.9
            state.signals = [f"role:{role}"]
            save_habitat(state)
            return state
    scores = score_text(blob)
    if not any(scores.values()):
        return state
    best = max(scores, key=lambda k: scores[k])
    if scores[best] < 1.5:
        return state
    # Blend with existing state — recent strong signals can shift habitat.
    if state.domain == best:
        state.confidence = min(0.95, state.confidence + 0.08)
    elif scores[best] >= state.confidence * 2 or state.confidence < 0.4:
        state.domain = best
        state.confidence = min(0.85, 0.35 + scores[best] * 0.1)
    state.signals = (state.signals + [f"msg:{best}"])[-12:]
    save_habitat(state)
    if not quiet:
        print(f"Habitat: {state.domain} ({state.confidence:.0%})")
    return state


def update_from_session(*, quiet: bool = True) -> HabitatState:
    """Re-infer habitat from stored chat session."""
    try:
        from arka.agent.chat import load_session
    except ImportError:
        return load_habitat()
    msgs = load_session()
    user_texts = [
        (m.get("content") or "").strip()
        for m in msgs
        if m.get("role") == "user" and (m.get("content") or "").strip()
    ]
    state = load_habitat()
    if state.manual:
        return state
    domain, confidence, signals = infer_from_messages(user_texts)
    if domain == "general" and confidence < 0.2:
        return state
    state.domain = domain
    state.confidence = max(state.confidence, confidence)
    if signals:
        state.signals = list(dict.fromkeys(state.signals + signals))[-12:]
    save_habitat(state)
    if not quiet:
        print(f"Habitat inferred: {state.domain} ({state.confidence:.0%})")
    return state


def effective_domain() -> str:
    return load_habitat().domain


def uses_tech_context(domain: str | None = None) -> bool:
    dom = (domain or effective_domain()).lower()
    return dom in {"developer", "ops"}


def context_for(goal: str = "") -> str:
    """Return habitat block for LLM / session context."""
    state = load_habitat()
    if state.domain == "general" and state.confidence < 0.25:
        return ""
    label = DOMAIN_LABELS.get(state.domain, state.domain)
    lines = [f"User habitat: {label} (confidence {state.confidence:.0%})"]
    if uses_tech_context(state.domain):
        lines.append(
            "Prefer programming, software, and tech meanings for ambiguous terms "
            "(e.g. Rust = programming language, Go = Golang)."
        )
    elif state.domain == "student":
        lines.append(
            "Prefer academic/educational context unless the question clearly targets another domain."
        )
    if state.signals:
        lines.append("Signals: " + ", ".join(state.signals[-4:]))
    return "\n".join(lines)


def recall_query_terms(query: str) -> list[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    subject = _DEFINITIONAL_QUERY_RE.match(q)
    if subject:
        q = subject.group(1).strip().rstrip("?")
    stop = {
        "a", "an", "the", "is", "are", "was", "were", "what", "who", "how",
        "when", "where", "why", "tell", "about", "explain", "describe",
    }
    return [w for w in re.findall(r"[a-z0-9+#]+(?:'[a-z0-9]+)?", q) if w not in stop]


def is_definitional_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if _DEFINITIONAL_QUERY_RE.match(q):
        return True
    return bool(re.match(r"(?i)^tell\s+me\s+about\s+.+\??$", q))


def is_ambiguous_definitional_query(query: str, *, domain: str | None = None) -> bool:
    if not is_definitional_query(query):
        return False
    if not uses_tech_context(domain):
        return False
    terms = recall_query_terms(query)
    if len(terms) != 1:
        return False
    dom = (domain or effective_domain()).lower()
    hints = _TECH_DISAMBIGUATION.get(dom, {})
    return terms[0] in hints


def should_skip_memory_recall(query: str) -> bool:
    return is_ambiguous_definitional_query(query)


def enhance_definitional_search_query(query: str, *, domain: str | None = None) -> str:
    """Disambiguate homographs using habitat (developer → Rust = programming language)."""
    q = (query or "").strip()
    if not q:
        return q
    dom = (domain or effective_domain()).lower()
    if not uses_tech_context(dom):
        return q
    m = re.match(r"(?i)what\s+is\s+(?:a|an|the)?\s*(.+?)\??$", q)
    if not m:
        return q
    subject = m.group(1).strip().rstrip("?")
    hints = _TECH_DISAMBIGUATION.get(dom, _TECH_DISAMBIGUATION["developer"])
    hint = hints.get(subject.lower())
    if hint:
        return f"what is {hint}"
    return q


def set_domain(domain: str, *, manual: bool = True) -> HabitatState:
    dom = domain.strip().lower()
    if dom not in VALID_DOMAINS:
        raise ValueError(f"Unknown habitat domain: {domain}")
    state = HabitatState(
        domain=dom,
        confidence=0.95 if dom != "general" else 0.0,
        signals=[f"manual:{dom}"] if manual else [f"set:{dom}"],
        manual=manual and dom != "general",
    )
    save_habitat(state)
    return state


def status_payload() -> dict[str, Any]:
    state = load_habitat()
    return {
        "domain": state.domain,
        "label": DOMAIN_LABELS.get(state.domain, state.domain),
        "confidence": state.confidence,
        "manual": state.manual,
        "signals": state.signals,
        "updated_at": state.updated_at,
        "uses_tech_context": uses_tech_context(state.domain),
    }


def format_status() -> str:
    state = load_habitat()
    lines = [
        f"Domain:     {state.domain} ({DOMAIN_LABELS.get(state.domain, state.domain)})",
        f"Confidence: {state.confidence:.0%}",
        f"Manual:     {'yes' if state.manual else 'no'}",
    ]
    if state.signals:
        lines.append(f"Signals:    {', '.join(state.signals[-6:])}")
    if state.updated_at:
        lines.append(f"Updated:    {time.strftime('%Y-%m-%d %H:%M', time.localtime(state.updated_at))}")
    return "\n".join(lines)


def is_habitat_query(cmd: str) -> bool:
    return bool(_HABITAT_TRIGGERS.search((cmd or "").strip()))


def nl_to_argv(cmd: str) -> list[str] | None:
    clean = (cmd or "").strip()
    if not is_habitat_query(clean) and not _EXPLICIT_HABITAT_RE.match(clean):
        return None
    low = clean.lower()
    if re.search(r"\b(?:reset|clear)\b", low):
        return ["reset"]
    if re.search(r"\b(?:infer|refresh|update)\b", low):
        return ["infer"]
    m = re.search(r"\b(?:set|to)\s+(developer|student|ops|general)\b", low)
    if m:
        return ["set", m.group(1)]
    m = _EXPLICIT_HABITAT_RE.match(clean)
    if m:
        return ["set", m.group("domain").lower()]
    if re.search(r"\b(?:status|show|what)\b", low):
        return ["status"]
    return ["status"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Arka habitat — lightweight user domain/context inference"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show current habitat")
    p_set = sub.add_parser("set", help="Set habitat domain")
    p_set.add_argument("domain", choices=sorted(VALID_DOMAINS))
    sub.add_parser("reset", help="Clear saved habitat")
    sub.add_parser("infer", help="Re-infer from chat session")
    p_ctx = sub.add_parser("context", help="Print habitat context block")
    p_ctx.add_argument("goal", nargs="?", default="")
    p_parse = sub.add_parser("parse", help="Parse NL into habitat argv (internal)")
    p_parse.add_argument("text")

    args = parser.parse_args(argv if argv is not None else [])
    cmd = args.cmd

    if cmd is None:
        print(format_status())
        print()
        print("Usage: arka habitat status | set developer | infer | reset")
        return 0

    if cmd == "parse":
        out = nl_to_argv(args.text)
        if out:
            print(" ".join(out))
        return 0

    if cmd == "status":
        print(format_status())
        return 0

    if cmd == "set":
        set_domain(args.domain)
        print(format_status())
        return 0

    if cmd == "reset":
        reset_habitat()
        print("Habitat cleared.")
        return 0

    if cmd == "infer":
        update_from_session(quiet=False)
        print(format_status())
        return 0

    if cmd == "context":
        block = context_for(args.goal or "")
        if block:
            print(block)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
