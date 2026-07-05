#!/usr/bin/env python3
"""Travel survival phrases — translate basics from your language to another."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

LANG_CODES: dict[str, str] = {
    "afrikaans": "af",
    "arabic": "ar",
    "bengali": "bn",
    "burmese": "my",
    "chinese": "zh-CN",
    "mandarin": "zh-CN",
    "cantonese": "zh-TW",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "filipino": "tl",
    "tagalog": "tl",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "gujarati": "gu",
    "hebrew": "he",
    "hindi": "hi",
    "hungarian": "hu",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "kannada": "kn",
    "korean": "ko",
    "malay": "ms",
    "marathi": "mr",
    "nepali": "ne",
    "norwegian": "no",
    "persian": "fa",
    "farsi": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "punjabi": "pa",
    "romanian": "ro",
    "russian": "ru",
    "spanish": "es",
    "swahili": "sw",
    "swedish": "sv",
    "tamil": "ta",
    "telugu": "te",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "urdu": "ur",
    "vietnamese": "vi",
}

SURVIVAL_SECTIONS: list[tuple[str, list[str]]] = [
    (
        "Greetings & introductions",
        [
            "Hello",
            "Good morning",
            "Good evening",
            "Good night",
            "Nice to meet you",
            "Pleased to meet you",
            "My name is …",
            "What is your name?",
            "How are you?",
            "I'm fine, thank you",
            "Goodbye",
            "See you later",
            "Take care",
        ],
    ),
    (
        "Politeness",
        [
            "Please",
            "Thank you",
            "Thank you very much",
            "You're welcome",
            "Excuse me",
            "Sorry",
            "No problem",
            "Yes",
            "No",
        ],
    ),
    (
        "Communication",
        [
            "I don't understand",
            "Do you speak English?",
            "I speak a little …",
            "Could you speak more slowly?",
            "Could you repeat that?",
            "Can you help me?",
        ],
    ),
    (
        "Shopping",
        [
            "How much does this cost?",
            "Too expensive",
            "Do you have a discount?",
            "I like it",
            "I don't like it",
            "I want to buy this",
            "I don't want it",
            "I'll take it",
            "Can I pay by card?",
            "Do you accept cash?",
            "Can I try it on?",
            "Do you have this in another size?",
        ],
    ),
    (
        "Food & drink",
        [
            "A table for two, please",
            "The menu, please",
            "Water, please",
            "Coffee, please",
            "The bill, please",
            "Vegetarian food, please",
            "No meat, please",
            "Not too spicy, please",
            "I'm allergic to …",
            "Delicious!",
        ],
    ),
    (
        "Directions & travel",
        [
            "Where is …?",
            "Where is the bathroom?",
            "Where is the train station?",
            "Where is the hotel?",
            "I'm lost",
            "Is it far?",
            "How do I get to …?",
            "Turn left",
            "Turn right",
            "Go straight",
        ],
    ),
    (
        "Emergency & health",
        [
            "I need help",
            "Call the police",
            "Call an ambulance",
            "I need a doctor",
            "I don't feel well",
            "I lost my passport",
            "Help!",
        ],
    ),
]


def all_survival_phrases() -> list[str]:
    out: list[str] = []
    for _title, items in SURVIVAL_SECTIONS:
        for phrase in items:
            if phrase not in out:
                out.append(phrase)
    return out


# Backward-compatible flat list
SURVIVAL_PHRASES = all_survival_phrases()

LANGUAGE_ALIASES: dict[str, str] = {
    "jp": "japanese",
    "ja": "japanese",
    "cn": "chinese",
    "zh": "chinese",
    "kr": "korean",
    "ko": "korean",
    "es": "spanish",
    "fr": "french",
    "de": "german",
    "it": "italian",
    "pt": "portuguese",
    "ru": "russian",
    "ar": "arabic",
    "hi": "hindi",
    "bn": "bengali",
    "th": "thai",
    "vi": "vietnamese",
    "tr": "turkish",
    "nl": "dutch",
    "pl": "polish",
}


def resolve_lang_code(name: str) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        return ""
    if raw in LANGUAGE_ALIASES:
        raw = LANGUAGE_ALIASES[raw]
    if raw in LANG_CODES:
        return LANG_CODES[raw]
    if re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", raw):
        return raw
    return ""


def native_lang_code() -> str:
    explicit = resolve_lang_code(os.environ.get("ARKA_NATIVE_LANG", ""))
    if explicit:
        return explicit
    speak = (os.environ.get("ARKA_SPEAK_LANG") or os.environ.get("SPEAK_LANG") or "").strip()
    if speak:
        base = speak.split("-")[0].lower()
        code = resolve_lang_code(base)
        if code:
            return code
    return "en"


def google_translate(text: str, *, target: str, source: str = "auto") -> str:
    text = (text or "").strip()
    if not text:
        return ""
    params = urllib.parse.urlencode(
        {"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text}
    )
    url = f"https://translate.googleapis.com/translate_a/single?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "arka-survival-lang/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    parts = data[0] if isinstance(data, list) and data else []
    return "".join(str(chunk[0]) for chunk in parts if chunk and chunk[0]).strip()


def lang_label(code: str) -> str:
    for name, cid in LANG_CODES.items():
        if cid == code:
            return name.title()
    return code


def format_phrase_block(english: str, translated: str) -> str:
    return f"• {english}\n  {translated}"


def translate_one_phrase(en_text: str, *, source: str, target: str) -> tuple[str, str]:
    """Return (left_label, target_translation)."""
    en_text = en_text.strip()
    translated = google_translate(en_text, target=target, source="en")
    if source != "en":
        native_text = google_translate(en_text, target=source, source="en")
    else:
        native_text = en_text
    if not translated:
        translated = "(translation unavailable)"
    left = native_text if native_text else en_text
    if source != "en" and left != en_text:
        left = f"{left} ({en_text})"
    return left, translated


def run_survival(
    target_lang: str,
    *,
    native: str | None = None,
    phrase: str | None = None,
    list_langs: bool = False,
    quiet: bool = False,
) -> int:
    if list_langs:
        names = sorted({n.title() for n in LANG_CODES})
        print("Supported languages (examples):")
        print(", ".join(names))
        return 0

    target = resolve_lang_code(target_lang)
    if not target:
        print(f"Unknown language: {target_lang}", file=sys.stderr)
        print("Try: survive_lang list", file=sys.stderr)
        return 1

    source = resolve_lang_code(native or "") or native_lang_code()
    if source == target:
        print("Native and target language are the same.", file=sys.stderr)
        return 1

    src_label = lang_label(source)
    tgt_label = lang_label(target)

    single = phrase.strip() if phrase and phrase.strip() else ""

    lines = [
        f"Survival phrases: {src_label} → {tgt_label}",
        "(Your language on the left — use the translation when speaking abroad.)",
        "",
    ]

    if single:
        if not quiet:
            print(f"Translating 1 phrase to {tgt_label}…", file=sys.stderr)
        try:
            left, translated = translate_one_phrase(single, source=source, target=target)
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Translation failed: {exc}", file=sys.stderr)
            return 1
        lines.append(format_phrase_block(left, translated))
        if quiet:
            print(translated)
        else:
            print("\n".join(lines))
        return 0

    total = sum(len(items) for _t, items in SURVIVAL_SECTIONS)
    print(f"Translating {total} phrases to {tgt_label}…", file=sys.stderr)

    for section_title, items in SURVIVAL_SECTIONS:
        lines.append(f"— {section_title} —")
        lines.append("")
        for item in items:
            try:
                left, translated = translate_one_phrase(item, source=source, target=target)
            except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"Translation failed: {exc}", file=sys.stderr)
                return 1
            lines.append(format_phrase_block(left, translated))
        lines.append("")

    print("\n".join(lines).rstrip())
    return 0


def main(argv: list[str] | None = None) -> int:
    from arka.paths import load_env_file

    load_env_file()

    parser = argparse.ArgumentParser(
        description="Travel survival phrases — translate basics to another language",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="",
        help="Target language (e.g. japanese, french, thai)",
    )
    parser.add_argument("phrase", nargs="?", default="", help="Optional single phrase to translate")
    parser.add_argument("--native", "-n", default="", help="Source language (default: ARKA_NATIVE_LANG or English)")
    parser.add_argument("--list", "-l", action="store_true", dest="list_langs", help="List supported languages")
    parser.add_argument("--quiet", "-q", action="store_true", help="Print translated text only (single phrase)")
    args = parser.parse_args(argv)

    if args.list_langs:
        return run_survival("", list_langs=True)

    if not args.target:
        print(
            "Usage: survive_lang <language> [phrase]\n"
            "Example: survive_lang japanese\n"
            "Example: survive_lang spanish \"I want to buy this\"",
            file=sys.stderr,
        )
        return 1

    return run_survival(
        args.target,
        native=args.native or None,
        phrase=args.phrase or None,
        quiet=bool(args.quiet),
    )


if __name__ == "__main__":
    raise SystemExit(main())
