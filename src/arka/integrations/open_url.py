#!/usr/bin/env python3
"""Open URLs in the system default browser (cross-platform via webbrowser)."""

from __future__ import annotations

import argparse
import platform
import re
import shlex
import subprocess
import sys
import shutil
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

# Browser/desktop app names — `open brave` launches the app, not brave.com.
BROWSER_APPS: dict[str, str] = {
    "brave": "Brave Browser",
    "chrome": "Google Chrome",
    "googlechrome": "Google Chrome",
    "chromium": "Chromium",
    "firefox": "Firefox",
    "safari": "Safari",
    "edge": "Microsoft Edge",
    "microsoftedge": "Microsoft Edge",
    "arc": "Arc",
    "vivaldi": "Vivaldi",
    "opera": "Opera",
}

LINUX_BROWSER_COMMANDS: dict[str, tuple[str, ...]] = {
    "brave": ("brave-browser", "brave"),
    "chrome": ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"),
    "chromium": ("chromium-browser", "chromium", "google-chrome"),
    "firefox": ("firefox",),
    "edge": ("microsoft-edge", "microsoft-edge-stable"),
    "vivaldi": ("vivaldi", "vivaldi-stable"),
    "opera": ("opera",),
}

WINDOWS_BROWSER_COMMANDS: dict[str, tuple[str, ...]] = {
    "brave": ("brave", "brave.exe"),
    "chrome": ("chrome", "chrome.exe"),
    "firefox": ("firefox", "firefox.exe"),
    "edge": ("msedge", "msedge.exe"),
}

_OPEN_PREFIX = re.compile(
    r"(?i)^(?:please\s+)?(?:arka\s+)?"
    r"(?:open_url|open_urls|browse|open|launch)\s+"
    r"(?:the\s+)?(?:url\s+)?"
)
_BROWSER_SUFFIX = re.compile(r"(?i)\s+in\s+(?:the\s+|my\s+)?(?:default\s+)?browser\s*$")
_KNOWN_CMDS = frozenset({"parse", "open"})

# Bare tokens that are CLI/meta commands, not site names (avoid help.com).
_RESERVED_OPEN_TARGETS = frozenset(
    {
        "help",
        "skills",
        "?",
        "hi",
        "hello",
        "hey",
        "yo",
        "namaste",
        "thanks",
        "thankyou",
    }
)
_GREETING_RE = re.compile(
    r"(?i)^(?:hi|hello|hey|yo|namaste|thanks|thank\s+you|good\s+(?:morning|afternoon|evening|night))[!.\\s]*$"
)

# Reserved for other skills — not browser URL opens (first token after open only).
_RESERVED_OPEN_FIRST = re.compile(
    r"(?i)^(?:open|browse|launch)\s+(?:the\s+)?(?:project|news|finance|file|app)\b"
)
_OPEN_URL_PREFIX = re.compile(
    r"(?i)^(?:open|browse|launch)\s+(?:the\s+)?(?:url\s+)?https?://"
)
_NON_URL_OPEN = re.compile(
    r"(?i)\b(?:project|news|finance|file|app|folder|directory|terminal|editor|vscode|cursor)\b"
)
_PLAY_WEBSITE_GAME_PREFIX = re.compile(
    r"(?i)^(?:arka\s+)?(?:play[_-]?website[_-]?game|website[_-]?game|browser[_-]?game)\b"
)
_PATH_LIKE_OPEN = re.compile(r"^(?:\.{1,2}|~|/|\./|\.\./)")


def _strip_wrapping_quotes(text: str) -> str:
    t = (text or "").strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1].strip()
    return t


def _normalize_token(token: str) -> str:
    return re.sub(r"[^a-z0-9.-]", "", (token or "").strip().lower())


def is_browser_app_name(raw: str) -> bool:
    """True when the token names a browser app (e.g. brave), not a website."""
    if _looks_like_urlish_target(raw):
        return False
    token = _normalize_token(raw)
    if not token:
        return False
    return token in BROWSER_APPS or token in LINUX_BROWSER_COMMANDS or token in WINDOWS_BROWSER_COMMANDS


def _browser_app_label(token: str) -> str:
    key = _normalize_token(token)
    return BROWSER_APPS.get(key, key.title())


def launch_application(name: str) -> bool:
    """Launch a desktop browser app by friendly name (cross-platform)."""
    token = _normalize_token(name)
    if not token:
        return False

    system = platform.system()
    if system == "Darwin":
        app = BROWSER_APPS.get(token)
        if not app:
            return False
        proc = subprocess.run(["open", "-a", app], check=False, capture_output=True, text=True)
        return proc.returncode == 0

    if system == "Windows":
        for cmd in WINDOWS_BROWSER_COMMANDS.get(token, (token,)):
            proc = subprocess.run(["cmd", "/c", "start", "", cmd], check=False, capture_output=True, text=True)
            if proc.returncode == 0:
                return True
        return False

    for cmd in LINUX_BROWSER_COMMANDS.get(token, (token,)):
        exe = shutil.which(cmd)
        if not exe:
            continue
        proc = subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc.poll() is None or proc.returncode in (None, 0)
    return False


def _looks_like_urlish_target(raw: str) -> bool:
    t = (raw or "").strip()
    return bool(
        re.match(r"(?i)^https?://", t)
        or re.match(r"(?i)^www\.[^\s/]+(?:/.*)?$", t)
        or re.match(r"(?i)^[^\s/]+\.[a-z]{2,}(?:/.*)?$", t)
    )


def _looks_like_filesystem_path(raw: str) -> bool:
    t = (raw or "").strip()
    if not t or _looks_like_urlish_target(t):
        return False
    if _PATH_LIKE_OPEN.match(t):
        return True
    return "/" in t


def _looks_like_macos_open(argv: list[str]) -> bool:
    """True when argv resembles macOS open(1), not a browser URL request."""
    parts = [p for p in argv if p and p != "--"]
    if not parts:
        return False
    if any(p.startswith("-") for p in parts):
        return True
    return any(_looks_like_filesystem_path(p) for p in parts)


def _passthrough_macos_open(argv: list[str]) -> int:
    proc = subprocess.run(["/usr/bin/open", *argv], check=False)
    return proc.returncode


def _fallback_open_urls(argv: list[str]) -> list[str]:
    if _looks_like_macos_open(argv):
        return []
    urls: list[str] = []
    for part in argv:
        if not part.strip() or part.startswith("-") or _looks_like_filesystem_path(part):
            continue
        url = build_url(part)
        if url:
            urls.append(url)
    return urls


def build_url(target: str) -> str | None:
    """Turn a site name, domain, or full URL into a normalized https URL."""
    raw = _strip_wrapping_quotes(target)
    if not raw:
        return None

    if re.match(r"(?i)^https?://", raw):
        return raw.rstrip(".,)")

    if _looks_like_urlish_target(raw):
        if raw.lower().startswith("www."):
            return f"https://{raw.rstrip('.,)')}"
        return f"https://{raw.rstrip('.,)')}"

    token = _normalize_token(raw)
    if not token or token in _RESERVED_OPEN_TARGETS:
        return None
    if is_browser_app_name(raw):
        return None

    if token in SITE_ALIASES:
        return f"https://{SITE_ALIASES[token]}"

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

    if _looks_like_urlish_target(t):
        return t.rstrip(".,)")

    # "open youtube.com" / "open YouTube"
    return t.strip()


def parse_open_app(text: str) -> str | None:
    """Parse NL/argv into a browser app token (e.g. brave), not a URL."""
    t = _strip_wrapping_quotes(text)
    if not t:
        return None
    if is_browser_app_name(t):
        return _normalize_token(t)

    m = re.search(
        r"(?i)(?:^|\b)(?:open|browse|launch|start)\s+(?:the\s+)?(?:app\s+)?(.+?)(?:\s+app)?\s*$",
        t,
    )
    if m:
        target = _extract_open_target(m.group(0)) or m.group(1).strip()
        if target and is_browser_app_name(target) and not _NON_URL_OPEN.search(target):
            return _normalize_token(target)
    return None


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
    if _looks_like_macos_open(shlex.split(clean, posix=True)):
        return False
    if parse_open_app(clean):
        return True
    if _PLAY_WEBSITE_GAME_PREFIX.search(clean):
        return False
    if _GREETING_RE.match(clean):
        return False
    if is_play_youtube_intent(clean):
        return False
    if _OPEN_URL_PREFIX.search(clean):
        return parse_open(clean) is not None
    if _RESERVED_OPEN_FIRST.search(clean):
        return False
    if re.search(r"(?i)^open\s+kaggle\b", clean):
        return False
    if clean.lower() in _RESERVED_OPEN_TARGETS:
        return False
    if _NON_URL_OPEN.search(clean) and not re.search(r"(?i)^(?:open|browse|launch)\s+", clean):
        return False
    return parse_open(clean) is not None or parse_open_app(clean) is not None


def parse_open(text: str) -> str | None:
    """Parse natural language or argv into a browser URL."""
    t = _strip_wrapping_quotes(text)
    if not t:
        return None

    lower = t.lower()
    if _GREETING_RE.match(t):
        return None
    if is_play_youtube_intent(t):
        return None

    if _OPEN_URL_PREFIX.search(t):
        target = _extract_open_target(t)
        if target:
            return build_url(target)
    if _RESERVED_OPEN_FIRST.search(t):
        return None
    if re.search(r"(?i)^open\s+kaggle\b", lower):
        return None
    if lower in _RESERVED_OPEN_TARGETS:
        return None
    if _NON_URL_OPEN.search(t) and not re.search(r"(?i)^(?:open|browse|launch)\s+", lower):
        return None

    # Explicit browser-open phrasing.
    m = re.search(
        r"(?i)(?:^|\b)(?:open|browse|launch)\s+(?:the\s+)?(?:url\s+)?(.+?)(?:\s+in\s+(?:the\s+|my\s+)?(?:default\s+)?browser)?\s*$",
        t,
    )
    if m:
        target = _extract_open_target(m.group(0))
        if target and not _NON_URL_OPEN.search(target):
            if is_browser_app_name(target):
                return None
            return build_url(target)

    # Bare URL or domain.
    if re.match(r"(?i)^https?://", t):
        return t.rstrip(".,)")
    if re.match(r"^[\w.-]+\.[a-z]{2,}(?:/[^\s]*)?$", t, re.I):
        return build_url(t)

    # Positional after open_url/open/browse command.
    parts = shlex.split(t, posix=True)
    had_open_command = False
    while parts and parts[0].lower() in _KNOWN_CMDS | {"open_url", "open_urls", "browse"}:
        had_open_command = True
        parts = parts[1:]
    if len(parts) == 1:
        target = parts[0]
        if _looks_like_urlish_target(target):
            return build_url(target)
        if had_open_command and _normalize_token(target) in SITE_ALIASES:
            return build_url(target)

    return None


def nl_to_argv(text: str) -> list[str]:
    app = parse_open_app(text)
    if app:
        return [app]
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


def format_app_result(name: str) -> str:
    label = _browser_app_label(name)
    return "\n".join(
        [
            "━━━ Launch Application ━━━",
            "",
            f"  ▶ {label}",
            "",
            "  Opened on your system.",
        ]
    )


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
    argv = [part for part in argv if part != "--"]
    if platform.system() == "Darwin" and _looks_like_macos_open(argv):
        return _passthrough_macos_open(argv)
    text = " ".join(argv).strip()
    if not text:
        print(
            "Usage: open_url <url-or-site>\n"
            "       open_url open youtube\n"
            "       arka open github.com\n"
            "       arka open brave\n"
            "       arka 'open google in browser'",
            file=sys.stderr,
        )
        return 1

    app = parse_open_app(text)
    if not app and not re.search(r"(?i)\b(?:open|browse|launch|start)\b", text):
        app = parse_open_app(f"open {text}")
    if app:
        if launch_application(app):
            print(format_app_result(app))
            return 0
        print(f"✗ Could not launch {_browser_app_label(app)!r}", file=sys.stderr)
        return 1

    url = parse_open(text)
    if not url and not re.search(r"(?i)\b(?:open|browse|launch)\b", text):
        url = parse_open(f"open {text}")
    if not url:
        # Allow direct multi-arg URLs/domains.
        urls = _fallback_open_urls(argv)
        if not urls:
            print(
                f"Could not parse URL or app to open: {text!r}\n"
                "Examples:\n"
                "  open youtube\n"
                "  open brave\n"
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
