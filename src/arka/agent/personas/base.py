"""Persona chat, routing, and REPL."""

from __future__ import annotations

import re
import shlex
import sys

from arka.agent.personas.format import format_chat, print_repl_banner, print_repl_reply
from arka.agent.personas.io import list_personas, resolve_persona
from arka.agent.personas.schema import Persona, slugify

# Backward-compat aliases for the bundled Elon persona.
ELON_ALIASES = frozenset({"elon", "talk_to_elon", "elon_chat", "talk_elon"})

_CREATE_RE = re.compile(
    r"(?i)^(?:"
    r"(?:arka\s+)?(?:create|make|add)\s+persona\s+(?:for\s+)?(.+)"
    r"|persona\s+create\s+(.+)"
    r")$"
)

_PERSONA_CHAT_RE = re.compile(
    r"(?i)^(?:"
    r"(?:arka\s+)?persona\s+(?:chat\s+)?([a-z0-9_-]+)(?:\s+about\s+|\s+)(.*)"
    r"|(?:talk|chat)\s+(?:to|with)\s+(.+?)(?:\s+about\s+(.+))?$"
    r")$"
)

_ELON_PREFIX_RE = re.compile(
    r"(?i)^(?:"
    r"(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)(?:\s+chat)?\s*"
    r"|(?:talk|chat)\s+(?:to|with)\s+elon(?:\s+musk)?\s*"
    r"|(?:what\s+would\s+)?elon(?:\s+musk)?\s+(?:say|think)\s+(?:about\s+)?"
    r"|elon\s+persona\s*"
    r")"
)


def _known_names() -> list[str]:
    try:
        return list_personas(include_templates=True)
    except Exception:
        return sorted(ELON_ALIASES)


def _match_persona_name(text: str) -> tuple[str, str]:
    """Return (persona_slug, remainder_prompt) from NL tail after talk/chat."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return "", ""

    lower = clean.lower()
    if lower.startswith("elon musk"):
        rest = clean[len("elon musk") :].strip()
        rest = re.sub(r"(?i)^about\s+", "", rest).strip()
        return "elon", rest
    if lower.startswith("elon"):
        rest = clean[4:].strip()
        rest = re.sub(r"(?i)^about\s+", "", rest).strip()
        return "elon", rest

    names = _known_names()
    by_len = sorted({slugify(n) for n in names}, key=len, reverse=True)
    for slug in by_len:
        display_variants = {slug, slug.replace("-", " "), slug.replace("_", " ")}
        for variant in sorted(display_variants, key=len, reverse=True):
            if lower == variant:
                return slug, ""
            if lower.startswith(variant + " "):
                rest = clean[len(variant) :].strip()
                rest = re.sub(r"(?i)^about\s+", "", rest).strip()
                return slug, rest

    # Fallback: first token as slug, rest as prompt
    parts = clean.split(None, 1)
    if not parts:
        return "", ""
    name = slugify(parts[0])
    rest = parts[1].strip() if len(parts) > 1 else ""
    rest = re.sub(r"(?i)^about\s+", "", rest).strip()
    return name, rest


def sanitize_prompt(text: str, *, persona_name: str | None = None) -> str:
    """Strip routing prefixes and return the user's question."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""

    clean = _ELON_PREFIX_RE.sub("", clean).strip()

    if persona_name:
        slug = slugify(persona_name)
        for prefix in (
            rf"(?i)^(?:arka\s+)?persona\s+(?:chat\s+)?{re.escape(slug)}\s*",
            rf"(?i)^(?:talk|chat)\s+(?:to|with)\s+{re.escape(slug)}\s*",
        ):
            clean = re.sub(prefix, "", clean).strip()

    clean = re.sub(r"(?i)^about\s+", "", clean).strip()
    clean = re.sub(r'^["\']|["\']$', "", clean).strip()
    return clean


def wants_persona(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False

    if _CREATE_RE.match(clean):
        return True

    if re.match(r"(?i)^(?:arka\s+)?persona\b", clean):
        return True

    if re.match(
        r"(?i)^(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)(?:\s|$|\s+chat\b)",
        clean,
    ):
        return True
    if re.search(r"(?i)\b(?:talk|chat)\s+(?:to|with)\s+\w", clean):
        return True
    if re.search(r"(?i)\belon\s+(?:persona|mode|chat)\b", clean):
        return True
    if re.search(r"(?i)\bwhat\s+would\s+elon\s+(?:say|think)\b", clean):
        return True
    if re.search(r"(?i)\belon\s+musk\b", clean) and re.search(
        r"(?i)\b(?:say|think|about|persona)\b", clean
    ):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_persona(text):
        return ""

    clean = (text or "").strip()

    create_m = _CREATE_RE.match(clean)
    if create_m:
        raw = (create_m.group(1) or create_m.group(2) or "").strip()
        if raw:
            try:
                name = slugify(raw)
            except ValueError:
                return ""
            return f"persona create {name}"

    if re.match(r"(?i)^(?:arka\s+)?persona\s*$", clean):
        return "persona list"

    sub_m = re.match(
        r"(?i)^(?:arka\s+)?persona\s+(list|show|create|chat|edit)\b(?:\s+(.*))?$",
        clean,
    )
    if sub_m:
        sub = sub_m.group(1).lower()
        rest = (sub_m.group(2) or "").strip()
        if sub == "list":
            return "persona list"
        if sub in {"show", "edit", "create", "chat"} and rest:
            parts = shlex.split(rest)
            if parts:
                if sub == "chat":
                    name = parts[0]
                    prompt = " ".join(parts[1:])
                    prompt = re.sub(r"(?i)^about\s+", "", prompt).strip()
                    if prompt:
                        return f"persona chat {name} {prompt}"
                    return f"persona chat {name}"
                return f"persona {sub} {parts[0]}"
        if sub == "chat" and rest:
            return f"persona chat {rest}"
        return f"persona {sub}"

    if re.match(
        r"(?i)^(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)\s*$",
        clean,
    ) or re.match(
        r"(?i)^(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)\s+chat\s*$",
        clean,
    ):
        return "persona chat elon"

    if re.match(r"(?i)^(?:talk|chat)\s+(?:to|with)\s+elon(?:\s+musk)?\s*$", clean):
        return "persona chat elon"

    if _ELON_PREFIX_RE.search(clean):
        prompt = sanitize_prompt(clean, persona_name="elon")
        if not prompt or prompt.lower() == "chat":
            return "persona chat elon"
        return f"persona chat elon {prompt}"

    talk_m = re.match(
        r"(?i)^(?:talk|chat)\s+(?:to|with)\s+(.+?)(?:\s+about\s+(.+))?$",
        clean,
    )
    if talk_m:
        name_part = (talk_m.group(1) or "").strip()
        about = (talk_m.group(2) or "").strip()
        try:
            name, extra = _match_persona_name(name_part)
        except ValueError:
            return ""
        prompt = about or extra
        if not prompt:
            return f"persona chat {name}"
        return f"persona chat {name} {prompt}"

    persona_m = re.match(
        r"(?i)^(?:arka\s+)?persona\s+(?:chat\s+)?([a-z0-9_-]+)(?:\s+about\s+|\s+)(.*)$",
        clean,
    )
    if persona_m:
        name = persona_m.group(1)
        prompt = (persona_m.group(2) or "").strip()
        prompt = sanitize_prompt(prompt, persona_name=name) if prompt else ""
        if not prompt or prompt.lower() == "chat":
            return f"persona chat {name}"
        return f"persona chat {name} {prompt}"

    return ""


def nl_to_argv(text: str) -> list[str] | None:
    route = route_command(text)
    if not route:
        return None
    return shlex.split(route)[1:]


def _format_user(question: str, history: list[tuple[str, str]] | None = None) -> str:
    if not history:
        return question
    lines = ["Conversation so far:"]
    for user, assistant in history[-6:]:
        lines.append(f"User: {user}")
        lines.append(f"Persona: {assistant}")
    lines.append(f"User: {question}")
    return "\n".join(lines)


def _llm_reply(system: str, user: str, *, skill: str) -> str:
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system,
            user,
            temperature=0.7,
            task="chat",
            skill=skill,
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system, user, temperature=0.7, task="chat").strip()


def chat_once(
    persona: Persona | str,
    question: str,
    *,
    history: list[tuple[str, str]] | None = None,
    show_disclaimer: bool = False,
) -> str:
    if isinstance(persona, str):
        name = persona
        question = sanitize_prompt(question, persona_name=name) or question.strip()
        if not question:
            return ""
        p = resolve_persona(persona)
    else:
        p = persona
        name = p.name
        question = sanitize_prompt(question, persona_name=name) or question.strip()
        if not question:
            return ""

    user = _format_user(question, history)
    reply = _llm_reply(p.system_prompt, user, skill=f"persona:{p.name}")
    if show_disclaimer and reply:
        return format_chat(p, reply, show_disclaimer=True)
    return reply


def chat_repl(persona: Persona | str, *, show_disclaimer: bool = True) -> int:
    if isinstance(persona, str):
        p = resolve_persona(persona)
    else:
        p = persona

    if show_disclaimer:
        print_repl_banner(p)
    else:
        label = p.display_name or p.name
        print(f"{label} persona chat (type 'quit' or Ctrl-D to exit)\n")
    history: list[tuple[str, str]] = []

    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line.lower() in {"quit", "exit", "q"}:
            break
        answer = chat_once(p, line, history=history)
        if not answer:
            print("Could not get a reply (check LLM API keys)", file=sys.stderr)
            continue
        print()
        print_repl_reply(p, answer)
        print()
        history.append((line, answer))
    return 0
