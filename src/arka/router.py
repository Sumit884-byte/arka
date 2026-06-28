"""Portable NL routing (macOS, Windows, Linux without fish)."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass
class Route:
    skill: str
    source: str = "offline"


def route(text: str) -> Route | None:
    cmd = text.strip()
    if not cmd:
        return None
    clean = cmd.lower()

    if clean in ("help", "skills", "?"):
        return Route("help")

    if re.match(r"^(generate|create|make)\s+(?:a |an |the |me )?(?:new )?(password|passcode)\b", clean):
        return Route("generate_password")

    if re.match(r"(save|store|remember)\s+(?:password|pass)\s+\S+\s+(?:for|as|named)\s+[a-zA-Z0-9._-]+", clean):
        m = re.match(
            r"(?:save|store|remember)\s+(?:password|pass)\s+(\S+)\s+(?:for|as|named)\s+([a-zA-Z0-9._-]+)",
            cmd,
            re.I,
        )
        if m:
            pwd, name = m.group(1), m.group(2)
            return Route(f"generate_password set {name} {shlex.quote(pwd)}")

    if re.search(r"(save|store|remember).*(password|pass).*(for|as|named)", clean) or re.search(
        r"generate.*password.*(for|named)\s+\w+", clean
    ):
        m = re.search(r"(?:for|as|named)\s+([a-zA-Z0-9._-]+)", cmd, re.I)
        if not m:
            m = re.search(r"password\s+(?:for\s+)?([a-zA-Z0-9._-]+)", cmd, re.I)
        name = m.group(1) if m else ""
        return Route(f"generate_password save {name}".strip())

    if re.search(r"(get|show|retrieve).*(password|pass).*(for|named)", clean) or re.search(
        r"what.*password.*(for|to)\s+\w+", clean
    ):
        m = re.search(r"(?:for|to|named)\s+([a-zA-Z0-9._-]+)", cmd, re.I)
        if m:
            return Route(f"generate_password get {m.group(1)}")

    if re.search(r"\b(list|show)\s+(?:my\s+|saved\s+|stored\s+)?(?:passwords?|passcodes?)\b", clean):
        return Route("generate_password list")

    if re.search(r"\b(password|passcode)\b", clean) and not re.search(r"(decrypt|protected|pdf)", clean):
        return Route("generate_password")

    if re.match(r"^/", cmd):
        forced = cmd.lstrip("/").strip() or cmd
        return Route(f"deep_web_answer {forced}")

    if re.search(r"(weather|forecast|temp|rain|will it rain)", clean):
        return Route(f"hyperlocal_weather {cmd}")

    if re.search(r"(^calc\s|integrate|derivative|solve\s|=\s*\d)", clean):
        return Route(f"calc {cmd}")

    if _is_knowledge_question(clean):
        return Route(f"web_answer {cmd}")

    return None


def _is_knowledge_question(clean: str) -> bool:
    if re.search(r"\b(my|this pc|my computer|should i)\b", clean):
        return False
    return bool(
        re.match(
            r"^(why |where |when |who |what |tell me |explain |describe |how old |how many |how much )",
            clean,
        )
    )
