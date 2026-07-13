#!/usr/bin/env python3
"""Open URLs in the system default browser (cross-platform via webbrowser)."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
import webbrowser
from urllib.parse import urlparse

SITE_ALIASES: dict[str, str] = {
    "youtube": "youtube.com",
    "google": "google.com",
    "github": "github.com",
    "reddit": "reddit.com",
    "twitter": "twitter.com",
    "x": "x.com",
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "linkedin": "linkedin.com",
    "hackernews": "news.ycombinator.com",
    "hn": "news.ycombinator.com",
    "ycombinator": "news.ycombinator.com",
    "stackoverflow": "stackoverflow.com",
    "so": "stackoverflow.com",
    "amazon": "amazon.com",
    "netflix": "netflix.com",
    "spotify": "open.spotify.com",
    "wikipedia": "wikipedia.org",
    "wiki": "wikipedia.org",
    "gmail": "mail.google.com",
    "outlook": "outlook.com",
    "notion": "notion.so",
    "chatgpt": "chatgpt.com",
}

_OPEN_PREFIX = re.compile(
    r"(?i)^(?:please\s+)?(?:arka\s+)?"
    r"(?:open_url|open_urls|browse|open|launch)\s+"
    r"(?:the\s+)?(?:url\s+)?"
)
_BROWSER_SUFFIX = re.compile(r"(?i)\s+in\s+(?:the\s+|my\s+)?(?:default\s+)?browser\s*$")
_KNOWN_CMDS = frozenset({"parse", "open"})

# Reserved for other skills — not browser URL opens.
_NON_URL_OPEN = re.compile(
    r"(?i)\b(?:project|news|finance|file|app|folder|directory|terminal|editor|vscode|cursor)\b"
)


def _strip_wrapping_quotes(text: str) -> str:
    t = (text or "").strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1].strip()
    return t


def _normalize_token(token: str) -> str:
    return re.sub(r"[^a-z0-9.-]", "", (token or "").strip().lower())


def build_url(target: str) -> str | None:
    """Turn a site name, domain, or full URL into a normalized https URL."""
    raw = _strip_wrapping_quotes(target)
    if not raw:
        return None

    if re.match(r"(?i)^https?://", raw):
        return raw

    token = _normalize_token(raw)
    if not token:
        return None

    if token in SITE_ALIASES:
        return f"https://{SITE_ALIASES[token]}"

    if "." in token:
        host = token
        if token.startswith("www."):
            host = token
        return f"https://{host}"

    return f"https://{token}.com"


def _extract_open_target(text: str) -> str | None:
    t = _strip_wrapping_quotes(text)
    if not t:
        return None

    t = _BROWSER_SUFFIX.sub("", t).strip()
    t = _OPEN_PREFIX.sub("", t).strip()
    if not t:
        return None

    # Direct URL passed after stripping command words.
    url_m = re.search(r"https?://[^\s\"']+", t)
    if url_m:
        return url_m.group(0).rstrip(".,)")

    # "open youtube.com" / "open YouTube"
    return t.strip()


def is_play_youtube_intent(text: str) -> bool:
    """True when the user wants playback, not a browser open."""
    clean = (text or "").strip()
    if not clean:
        return False
    if re.search(r"(?i)\b(?:open|browse|launch)\s+(?:the\s+)?(?:url\s+)?[\w.-]+(?:\s+in\s+(?:the\s+|my\s+)?(?:default\s+)?browser)?\s*$", clean):
        if not re.search(r"(?i)\b(?:play|watch|listen|stream)\b", clean):
            return False
    return bool(
        re.search(
            r"(?i)(?:\bplay\b.*\byoutube\b|\bplay\b.*\b(?:video|episode|anime)\b|"
            r"\bwatch\b.*\byoutube\b|\bwatch\b\s+(?:a\s+|an\s+)?(?:video|episode|anime)\b)",
            clean,
        )
    )


def wants_open_url(text: str) -> bool:
    """True when NL should open a URL in the default browser."""
    clean = (text or "").strip()
    if not clean:
        return False
    if is_play_youtube_intent(clean):
        return False
    if _NON_URL_OPEN.search(clean):
        return False
    if re.search(r"(?i)\bopen\s+(?:project|news|finance|file|app)\b", clean):
        return False
    if re.search(r"(?i)\bopen\s+kaggle\b", clean):
        return False
    return parse_open(clean) is not None


def parse_open(text: str) -> str | None:
    """Parse natural language or argv into a browser URL."""
    t = _strip_wrapping_quotes(text)
    if not t:
        return None

    lower = t.lower()
    if is_play_youtube_intent(t):
        return None

    if re.search(r"(?i)\bopen\s+(?:project|news|finance|file|app)\b", lower):
        return None
    if re.search(r"(?i)\bopen\s+kaggle\b", lower):
        return None
    if _NON_URL_OPEN.search(t) and not re.search(r"(?i)^(?:open|browse)\s+", lower):
        return None

    # Explicit browser-open phrasing.
    m = re.search(
        r"(?i)(?:^|\b)(?:open|browse|launch)\s+(?:the\s+)?(?:url\s+)?(.+?)(?:\s+in\s+(?:the\s+|my\s+)?(?:default\s+)?browser)?\s*$",
        t,
    )
    if m:
        target = _extract_open_target(m.group(0))
        if target and not _NON_URL_OPEN.search(target):
            return build_url(target)

    # Bare URL or domain.
    if re.match(r"(?i)^https?://", t):
        return t.rstrip(".,)")
    if re.match(r"^[\w.-]+\.[a-z]{2,}(?:/[^\s]*)?$", t, re.I):
        return build_url(t)

    # Positional after open_url/open/browse command.
    parts = shlex.split(t, posix=True)
    while parts and parts[0].lower() in _KNOWN_CMDS | {"open_url", "open_urls", "browse"}:
        parts = parts[1:]
    if len(parts) == 1:
        return build_url(parts[0])

    return None


def nl_to_argv(text: str) -> list[str]:
    url = parse_open(text)
    if not url:
        return []
    return [url]


def route_command(text: str) -> str:
    if not wants_open_url(text):
        return ""
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "open_url " + " ".join(shlex.quote(a) for a in argv)


def open_in_browser(url: str) -> bool:
    """Open URL with the system default browser."""
    normalized = build_url(url) if not re.match(r"(?i)^https?://", url) else url
    if not normalized:
        raise ValueError(f"Invalid URL: {url!r}")
    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid URL: {normalized!r}")
    return webbrowser.open(normalized, new=2)


def format_result(url: str) -> str:
    return "\n".join(
        [
            "━━━ Open in Browser ━━━",
            "",
            f"  ▶ {url}",
            "",
            "  Opened in your default browser.",
        ]
    )


def cmd_open(argv: list[str]) -> int:
    text = " ".join(argv).strip()
    if not text:
        print(
            "Usage: open_url <url-or-site>\n"
            "       open_url open youtube\n"
            "       arka open github.com\n"
            "       arka 'open google in browser'",
            file=sys.stderr,
        )
        return 1

    url = parse_open(text)
    if not url and not re.search(r"(?i)\b(?:open|browse|launch)\b", text):
        url = parse_open(f"open {text}")
    if not url:
        # Allow direct multi-arg URLs/domains.
        urls = [build_url(part) for part in argv if part.strip()]
        urls = [u for u in urls if u]
        if not urls:
            print(
                f"Could not parse URL to open: {text!r}\n"
                "Examples:\n"
                "  open youtube\n"
                "  open https://news.ycombinator.com\n"
                "  open google in browser",
                file=sys.stderr,
            )
            return 1
    else:
        urls = [url]

    opened = 0
    for item in urls:
        try:
            if open_in_browser(item):
                opened += 1
                print(format_result(item))
            else:
                print(f"✗ Could not open browser for {item!r}", file=sys.stderr)
        except ValueError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1

    return 0 if opened else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: arka_open_url.py [open] <url-or-site>\n"
            "       arka_open_url.py parse <natural language>",
            file=sys.stderr,
        )
        return 0 if not argv else 1

    if argv[0] == "parse":
        return cmd_parse(argparse.Namespace(text=argv[1:]))

    if argv[0] in ("open", "open_url", "browse"):
        return cmd_open(argv[1:])

    if argv[0] not in _KNOWN_CMDS:
        return cmd_open(argv)

    parser = argparse.ArgumentParser(description="Open URLs in the default browser.")
    sub = parser.add_subparsers(dest="cmd")
    p_parse = sub.add_parser("parse", help="Parse natural language → URL (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)
    sub.add_parser("open", help="Open URL or site name").set_defaults(
        func=lambda a: cmd_open(getattr(a, "rest", []))
    )
    args = parser.parse_args()
    if args.cmd is None:
        return cmd_open(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
