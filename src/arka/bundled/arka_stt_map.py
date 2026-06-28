#!/usr/bin/env python3
"""Quick fixes for common STT mis-hearings (Sarvam translit, Vosk, etc.)."""

from __future__ import annotations

import os
import re
import sys


def _agent_name() -> str:
    return (os.environ.get("AGENT_NAME") or "arka").strip().lower() or "arka"


def _enabled() -> bool:
    return os.environ.get("ARKA_STT_QUICK_MAP", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def quick_map_rules(agent_name: str | None = None) -> list[tuple[str, str]]:
    name = (agent_name or _agent_name()).strip().lower() or "arka"
    wake = re.escape(name)
    return [
        # Wake mis-hearings → hey <agent>
        (rf"(?i)^he\s+rk\b", f"hey {name}"),
        (rf"(?i)^hey\s+rk\b", f"hey {name}"),
        (rf"(?i)^he\s+{wake}\b", f"hey {name}"),
        (rf"(?i)^hey\s+{wake}\b", f"hey {name}"),
        (rf"(?i)^he\s+arca\b", f"hey {name}"),
        (rf"(?i)^hey\s+arca\b", f"hey {name}"),
        (rf"(?i)^he\s+archer\b", f"hey {name}"),
        (rf"(?i)^hey\s+archer\b", f"hey {name}"),
        (rf"(?i)^he\s+marker\b", f"hey {name}"),
        (rf"(?i)^a\s+car\b", f"hey {name}"),
        (rf"(?i)^our\s+car\b", f"hey {name}"),
        (rf"(?i)^he\s+ah\s+cup\b", f"hey {name}"),
        (rf"(?i)^hey\s+ah\s+cup\b", f"hey {name}"),
        (rf"(?i)^he\s+can'?t\b", f"hey {name}"),
        (rf"(?i)^here\s+are\b", f"hey {name}"),
        (rf"(?i)^hey\s+you\s+can'?t\b", f"hey {name}"),
        (rf"(?i)^yeah\s+your\s+calf\b", f"hey {name}"),
        (rf"(?i)^your\s+calf\b", f"hey {name}"),
        (rf"(?i)^hey\s+{wake}\s+play\b", f"hey {name} play"),
        # Command phrasing
        (r"(?i)\bplay\s+and\s+music\b", "play an music"),
        (r"(?i)\bplay\s+a\s+music\b", "play music"),
        (r"(?i)\bplay\s+the\s+music\b", "play music"),
        (r"(?i)\bplay\s+some\s+music\b", "play music"),
        (r"(?i)\bplay\s+me\s+music\b", "play music"),
        (r"(?i)\bplay\s+me\s+a\s+song\b", "play a song"),
        (r"(?i)\bplay\s+me\s+an?\s+song\b", "play a song"),
        (r"(?i)\bplayer\s+song\b", "play a song"),
        (r"(?i)\bplayers?\s+from\b", "play a song"),
        (r"(?i)\bstop\s+playing\b", "stop the song"),
        (r"(?i)\bstop\s+this\s+song\b", "stop the song"),
        (r"(?i)\bpause\s+the\s+song\b", "stop the song"),
        (r"(?i)\bpause\s+music\b", "stop music"),
    ]


def strip_wake(text: str, agent_name: str | None = None) -> str:
    name = (agent_name or _agent_name()).strip().lower() or "arka"
    t = normalize_stt(text, agent_name)
    if not t:
        return ""
    low = t.lower()
    prefixes = [
        f"hey {name},",
        f"hey {name} ",
        f"ok {name},",
        f"ok {name} ",
        f"please {name},",
        f"please {name} ",
        f"{name},",
        f"{name} ",
        "hey rk ",
        "he rk ",
        "hey arca ",
        "he arca ",
    ]
    for _ in range(5):
        before = t
        for prefix in sorted(prefixes, key=len, reverse=True):
            if low.startswith(prefix):
                t = t[len(prefix) :].strip()
                low = t.lower()
        if t == before:
            break
    return t.strip()


def looks_like_direct_command(text: str) -> bool:
    t = normalize_stt(text)
    if not t or len(t.split()) < 2:
        return False
    return bool(
        re.search(
            r"(?i)^(play\s+(?:a\s+|an\s+|the\s+|some\s+|me\s+)?(?:song|songs|music|movie|video|spotify|youtube)\b|"
            r"play\s+\S|open\s+\S|weather\b|timer\b|screenshot\b|listen\b|debug\b|status\b|"
            r"stop\s+(?:the\s+|this\s+|playing\s+)?(?:song|songs|music|audio|playback|spotify|it)\b|"
            r"pause\s+(?:the\s+)?(?:song|songs|music|audio|playback)\b|"
            r"stop\s+listen|start\s+listen|resume\b)",
            t,
        )
    )


def classify_phrase(text: str, agent_name: str | None = None) -> tuple[str, str]:
    """Return (kind, phrase): wake_cmd | direct | wake_only | none."""
    norm = normalize_stt(text, agent_name)
    if not norm:
        return "none", ""
    rest = strip_wake(norm, agent_name)
    wake_prefixes = (
        r"(?i)^(hey\s+)?(arka|rk|arca|archer|marker|a\s+car|our\s+car|"
        r"he\s+rk|hey\s+rk|he\s+ah\s+cup|hey\s+you\s+can'?t|your\s+calf)\b"
    )
    has_wake = bool(re.search(wake_prefixes, norm)) or rest != norm
    if has_wake and rest:
        return "wake_cmd", norm
    if has_wake:
        return "wake_only", norm
    if looks_like_direct_command(norm):
        return "direct", norm
    return "none", norm


def normalize_stt(text: str, agent_name: str | None = None) -> str:
    text = " ".join((text or "").split()).strip(" \t\n\r.,!?;:")
    if not text or not _enabled():
        return text
    for pattern, repl in quick_map_rules(agent_name):
        text = re.sub(pattern, repl, text)
    return " ".join(text.split()).strip()


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "normalize":
        phrase = " ".join(sys.argv[2:]).strip()
        if not phrase and not sys.stdin.isatty():
            phrase = sys.stdin.read().strip()
        print(normalize_stt(phrase))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "rules":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        for pat, repl in quick_map_rules(name):
            print(f"{pat}\t->\t{repl}")
        return 0
    print("Usage: arka_stt_map.py normalize <phrase>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
