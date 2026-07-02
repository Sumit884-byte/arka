"""NL routing for all platforms — bundled fish router when available, Python fallbacks otherwise."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass

from arka.paths import fish_config, script_path


@dataclass
class Route:
    skill: str
    source: str = "offline"
    kind: str = "skill"


def _route_mode() -> str:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass
    mode = os.environ.get("ARKA_ROUTE_MODE", "symbolic").lower().strip()
    aliases = {
        "llm": "ai",
        "ai-first": "ai",
        "ai_first": "ai",
        "offline_only": "symbolic_only",
        "offline-only": "symbolic_only",
        "offline": "symbolic_only",
        "only": "symbolic_only",
        "llm_only": "ai_only",
        "ai-only": "ai_only",
        "llm-only": "ai_only",
        "hybrid": "symbolic",
        "auto": "symbolic",
        "default": "symbolic",
        "": "symbolic",
    }
    mode = aliases.get(mode, mode)
    if mode not in ("symbolic", "ai", "symbolic_only", "ai_only"):
        return "symbolic"
    return mode


def route(text: str) -> Route | None:
    cmd = text.strip()
    if not cmd:
        return None

    mode = _route_mode()

    fish_route = _route_via_fish(cmd)
    if fish_route:
        return fish_route

    if fish_config() is not None and mode in ("ai_only", "symbolic_only"):
        return None

    if mode in ("ai", "ai_only"):
        llm = _route_llm(cmd)
        if llm:
            return llm
        if mode == "ai_only":
            return None

    if mode != "ai_only":
        offline = _route_offline(cmd)
        if offline:
            return offline

    if mode == "symbolic":
        return _route_llm(cmd)

    return None


def _route_via_fish(cmd: str) -> Route | None:
    try:
        from arka.fish_bridge import fish_route_preview
    except ImportError:
        return None

    preview = fish_route_preview(cmd)
    if preview is None or not preview.action:
        return None

    source = preview.kind if preview.kind not in ("skill", "") else "fish"
    if preview.kind == "llm":
        source = "llm"
    elif preview.kind == "none":
        return None
    return Route(preview.action, source=source, kind=preview.kind or "skill")


def _route_llm(cmd: str) -> Route | None:
    path = script_path("arka_llm.py")
    if not path.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(path), "route", cmd],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = proc.stdout.strip()
    if not line or line == cmd:
        return None
    return Route(line, source="llm", kind="llm")


def _route_offline(cmd: str) -> Route | None:
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

    if re.search(
        r"(live\s+(sports?\s+)?scores?|sports?\s+scores?|ipl\s+(live|score)|cricket\s+(live|score)|nfl\s+scores?|nba\s+scores?|match\s+score)",
        clean,
    ):
        return Route(f"sports_score {cmd}")

    if re.search(r"(^calc\s|integrate|derivative|solve\s|=\s*\d)", clean):
        return Route(f"calc {cmd}")

    third_party = _match_third_party(cmd)
    if third_party:
        return Route(third_party, source="plugin")

    if re.search(r"(?i)\b(download|save|fetch|grab)\b", clean):
        url_m = re.search(r"https?://[^\s]+", cmd)
        if url_m:
            url = url_m.group(0)
            qurl = shlex.quote(url)
            if re.search(r"(?i)(playlist\?list=|/playlist)", url):
                return Route(f"youtube_bulk download {qurl} --wait", source="offline")
            if re.search(r"(?i)(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", url):
                return Route(f"youtube_download {qurl}", source="offline")
            return Route(f"download_file {qurl}", source="offline")

    if re.search(r"(find|search|list|show).*\bfiles?\b", clean) and re.search(
        r"(less|more|greater|larger|smaller|lesser|under|over|above|below|bigger)|\d+\s*(kb|mb|gb)\b",
        clean,
    ):
        return Route(f"find_files_by_size {cmd}", source="offline")

    chat_route = _route_chat_intent(cmd)
    if chat_route:
        return chat_route

    if _is_knowledge_question(clean):
        return Route(f"web_answer {cmd}")

    return None


def _match_third_party(cmd: str) -> str | None:
    try:
        import subprocess
        import sys

        from arka.paths import script_path

        path = script_path("arka_skills.py")
        if not path.is_file():
            return None
        proc = subprocess.run(
            [sys.executable, str(path), "match", cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        line = proc.stdout.strip()
        return line or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _route_chat_intent(cmd: str) -> Route | None:
    try:
        import subprocess
        import sys

        from arka.paths import script_path

        path = script_path("arka_chat.py")
        if not path.is_file():
            return None
        proc = subprocess.run(
            [sys.executable, str(path), "intent", cmd],
            capture_output=True,
            text=True,
            timeout=45,
        )
        line = proc.stdout.strip()
        if not line or "\t" not in line:
            return None
        action, _data = line.split("\t", 1)
        action = action.strip().upper()
        if action == "SEARCH":
            return Route(f"web_answer {cmd}", source="intent")
        if action == "CALC":
            return Route(f"calc {cmd}", source="intent")
        if action == "WEATHER":
            return Route(f"hyperlocal_weather {cmd}", source="intent")
        if action == "ERROR":
            return Route(f"error_helper {cmd}", source="intent")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _is_knowledge_question(clean: str) -> bool:
    if re.search(r"\b(my|this pc|my computer|my mac|my macbook|my machine|should i)\b", clean):
        return False
    return bool(
        re.match(
            r"^(why |where |when |who |what |tell me |explain |describe |how old |how many |how much )",
            clean,
        )
    )
