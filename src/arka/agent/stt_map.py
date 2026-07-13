#!/usr/bin/env python3
"""Quick fixes for common STT mis-hearings (Sarvam translit, Vosk, etc.)."""

from __future__ import annotations

import os
import re
import sys

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Hinglish STT often writes spoken English in Devanagari when lang=hi-IN.
# Map wake + common command words to Latin so routing/wake detection works.
DEVANAGARI_PHRASES: list[tuple[str, str]] = [
    (r"हे\s+अरका", "hey arka"),
    (r"है\s+अरका", "hey arka"),
    (r"हाय\s+अरका", "hey arka"),
    (r"ओके\s+अरका", "ok arka"),
    (r"अरका\s+टेल\s+मी", "arka tell me"),
    (r"अरका\s+बताओ", "arka tell me"),
    (r"टेल\s+मी\s+ऑल", "tell me all"),
    (r"टेल\s+मी\s+आल", "tell me all"),
]

DEVANAGARI_WORDS: dict[str, str] = {
    "अरका": "arka",
    "आर्का": "arka",
    "अर्का": "arka",
    "हे": "hey",
    "हाय": "hey",
    "ओके": "ok",
    "टेल": "tell",
    "मी": "me",
    "ऑल": "all",
    "आल": "all",
    "योर": "your",
    "यूर": "your",
    "स्किल्स": "skills",
    "स्किल": "skills",
    "स्किल्स्": "skills",
    "वेदर": "weather",
    "मौसम": "weather",
    "प्ले": "play",
    "गाना": "song",
    "संगीत": "music",
    "खोल": "open",
    "बंद": "stop",
    "स्कोर": "score",
    "स्कोर्स": "scores",
    "मैच": "match",
    "खेल": "sports",
    "आईपीएल": "ipl",
    "आइपीएल": "ipl",
}


def has_devanagari(text: str) -> bool:
    return bool(DEVANAGARI_RE.search(text or ""))


def normalize_indic_script(text: str) -> str:
    """Devanagari Hinglish → Latin for wake word + skill routing."""
    if not has_devanagari(text):
        return text
    t = text
    for pattern, repl in DEVANAGARI_PHRASES:
        t = re.sub(pattern, repl, t, flags=re.IGNORECASE)
    for dev, lat in sorted(DEVANAGARI_WORDS.items(), key=lambda kv: -len(kv[0])):
        t = t.replace(dev, lat)
    # Drop stray Devanagari punctuation / leftovers
    t = DEVANAGARI_RE.sub(" ", t)
    return " ".join(t.split()).strip()


def _agent_name() -> str:
    return (os.environ.get("AGENT_NAME") or "arka").strip().lower() or "arka"


def _enabled() -> bool:
    return os.environ.get("STT_QUICK_MAP", "1").strip().lower() not in (
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
        (r"(?i)^he\s+rk\b", f"hey {name}"),
        (r"(?i)^hey\s+rk\b", f"hey {name}"),
        (rf"(?i)^he\s+{wake}\b", f"hey {name}"),
        (rf"(?i)^hi\s+{wake}\b", f"hey {name}"),
        (rf"(?i)^hay\s+{wake}\b", f"hey {name}"),
        (r"(?i)^hey\s+irka\b", f"hey {name}"),
        (r"(?i)^hey\s+erka\b", f"hey {name}"),
        (r"(?i)^hey\s+ir\b", f"hey {name}"),
        (r"(?i)^he\s+irka\b", f"hey {name}"),
        (r"(?i)^he\s+arca\b", f"hey {name}"),
        (r"(?i)^hey\s+arca\b", f"hey {name}"),
        (r"(?i)^he\s+archer\b", f"hey {name}"),
        (r"(?i)^hey\s+archer\b", f"hey {name}"),
        (r"(?i)^he\s+marker\b", f"hey {name}"),
        (r"(?i)^a\s+car\b", f"hey {name}"),
        (r"(?i)^our\s+car\b", f"hey {name}"),
        (r"(?i)^he\s+ah\s+cup\b", f"hey {name}"),
        (r"(?i)^hey\s+ah\s+cup\b", f"hey {name}"),
        (r"(?i)^he\s+can'?t\b", f"hey {name}"),
        (r"(?i)^here\s+are\b", f"hey {name}"),
        (r"(?i)^hey\s+you\s+can'?t\b", f"hey {name}"),
        (r"(?i)^yeah\s+your\s+calf\b", f"hey {name}"),
        (r"(?i)^your\s+calf\b", f"hey {name}"),
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
        "hey arka ",
        "he arka ",
        "hi arka ",
        "hay arka ",
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
            r"stop\s+listen|start\s+listen|resume\b|"
            r"sports?\s+score|ipl\s+score|cricket\s+score|live\s+score)",
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
    if re.search(
        r"(?i)\b("
        r"tell\s+(?:me\s+)?(?:about\s+)?(?:all\s+)?(?:your\s+)?skills?|"
        r"tell\s+your\s+skills?|"
        r"(?:all|list|show)\s+(?:me\s+)?(?:all\s+)?(?:your\s+)?skills?|"
        r"what\s+(?:are\s+)?(?:all\s+)?your\s+skills?"
        r")\b",
        norm,
    ):
        return "wake_cmd" if has_wake else "direct", norm
    return "none", norm


def normalize_stt(text: str, agent_name: str | None = None) -> str:
    text = " ".join((text or "").split()).strip(" \t\n\r.,!?;:")
    if not text:
        return text
    text = normalize_indic_script(text)
    if not _enabled():
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
