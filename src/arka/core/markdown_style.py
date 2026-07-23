#!/usr/bin/env python3
"""Detect markdown-like text and render it with terminal styling."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_BLUE = "\033[34m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"

_MD_EXT = frozenset({".md", ".mdx", ".markdown"})

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"markdown_style|style_markdown|markdown-style|style-markdown|"
    r"style\s+(?:this|it|the\s+\S+)\s+as\s+markdown|"
    r"(?:render|pretty|format|style|display)\s+markdown|"
    r"markdown\s+(?:style|render|format|pretty|display)"
    r")\b"
)

_FILE_RE = re.compile(
    r"(?i)(?:['\"]([^'\"]+\.(?:md|mdx|markdown))['\"]"
    r"|((?:[\w.-]+/)+[\w.-]+\.(?:md|mdx|markdown))"
    r"|([~./][^\s'\"]+\.(?:md|mdx|markdown))"
    r"|([^\s'\"/\\]+\.(?:md|mdx|markdown))\b)"
)

_MD_SIGNAL_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^#{1,6}\s+\S"),
    re.compile(r"(?m)^\s*[-*+]\s+\S"),
    re.compile(r"(?m)^\s*\d+\.\s+\S"),
    re.compile(r"\*\*[^*\n]+\*\*"),
    re.compile(r"(?<![`])`[^`\n]+`"),
    re.compile(r"(?m)^```"),
    re.compile(r"(?m)^>\s+\S"),
    re.compile(r"(?m)^\|[^|\n]+\|"),
)


def markdown_style_enabled() -> bool:
    raw = os.environ.get("ARKA_MARKDOWN_STYLE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def looks_like_markdown(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if re.search(r"(?m)^```", raw):
        return True
    if re.search(r"(?m)^#{1,6}\s+\S", raw):
        return True
    hits = sum(1 for pat in _MD_SIGNAL_RES if pat.search(raw))
    return hits >= 2


def _terminal_width(default: int = 100) -> int:
    try:
        if sys.stdout.isatty():
            return max(40, min(os.get_terminal_size().columns, 120))
    except OSError:
        pass
    return default


def _inline_ansi(line: str) -> str:
    line = re.sub(r"\*\*(.+?)\*\*", rf"{_BOLD}\1{_RESET}", line)
    line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", rf"{_DIM}\1{_RESET}", line)
    line = re.sub(r"`([^`]+)`", rf"{_YELLOW}\1{_RESET}", line)
    return line


def _ansi_style_simple(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            out.append(f"{_DIM}{line}{_RESET}")
            continue
        if in_code:
            out.append(f"{_DIM}{line}{_RESET}")
            continue
        header = re.match(r"^(#{1,6})\s+(.*)$", line)
        if header:
            level = len(header.group(1))
            color = _BOLD + (_CYAN if level <= 2 else _BLUE)
            out.append(f"{color}{header.group(2)}{_RESET}")
            continue
        if line.lstrip().startswith(">"):
            out.append(f"{_DIM}{line}{_RESET}")
            continue
        bullet = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if bullet:
            indent, marker, content = bullet.groups()
            out.append(f"{indent}{_GREEN}{marker}{_RESET} {_inline_ansi(content)}")
            continue
        out.append(_inline_ansi(line))
    return "\n".join(out)


def _style_with_glow(text: str) -> str | None:
    glow = shutil.which("glow")
    if not glow:
        return None
    try:
        proc = subprocess.run(
            [glow, "-s", "dark", "-"],
            input=text,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0 and (proc.stdout or "").strip():
        return proc.stdout.rstrip("\n")
    return None


def _style_with_rich(text: str) -> str:
    from io import StringIO

    from rich.console import Console
    from rich.markdown import Markdown

    buf = StringIO()
    console = Console(
        file=buf,
        force_terminal=True,
        width=_terminal_width(),
        highlight=False,
    )
    console.print(Markdown(text))
    return buf.getvalue().rstrip("\n")


def style_markdown(
    text: str,
    *,
    plain: bool = False,
    backend: str | None = None,
) -> str:
    raw = text if text is not None else ""
    if plain or not raw.strip():
        return raw
    mode = (backend or os.environ.get("ARKA_MARKDOWN_BACKEND", "auto")).strip().lower()
    if mode == "plain":
        return raw
    if mode == "glow":
        styled = _style_with_glow(raw)
        return styled if styled is not None else _ansi_style_simple(raw)
    if mode == "rich":
        try:
            return _style_with_rich(raw)
        except Exception:
            return _ansi_style_simple(raw)
    if mode == "ansi":
        return _ansi_style_simple(raw)
    styled = _style_with_glow(raw)
    if styled is not None:
        return styled
    try:
        return _style_with_rich(raw)
    except Exception:
        return _ansi_style_simple(raw)


def maybe_style_markdown(text: str, *, plain: bool = False) -> str:
    raw = text if text is not None else ""
    if plain or not markdown_style_enabled() or not looks_like_markdown(raw):
        return raw
    return style_markdown(raw, plain=plain)


def wants_markdown_style(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def extract_md_path(text: str) -> str | None:
    match = _FILE_RE.search(text or "")
    if not match:
        return None
    for group in match.groups():
        if group:
            return group.strip().strip("'\"")
    return None


def route_command(text: str) -> str:
    if not wants_markdown_style(text):
        return ""
    clean = (text or "").strip()
    path = extract_md_path(clean)
    if path:
        return f"markdown_style style {path}"
    return "markdown_style style -"


def _read_input(path: str) -> str:
    raw = (path or "").strip()
    if raw in {"-", "stdin"}:
        return sys.stdin.read()
    p = Path(raw).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Markdown file not found: {p}")
    if p.suffix.lower() not in _MD_EXT:
        raise ValueError(f"Not a markdown file: {p}")
    return p.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arka markdown terminal styling")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to markdown_style command")
    p_route.add_argument("text", nargs="+")

    p_detect = sub.add_parser("detect", help="True if text looks like markdown")
    p_detect.add_argument("text", nargs="*")

    p_style = sub.add_parser("style", help="Style markdown text or file")
    p_style.add_argument("source", nargs="?", default="-", help="File path or - for stdin")
    p_style.add_argument("--plain", action="store_true", help="Disable styling")
    p_style.add_argument(
        "--backend",
        choices=["auto", "rich", "glow", "ansi", "plain"],
        default=None,
        help="Rendering backend (default: ARKA_MARKDOWN_BACKEND or auto)",
    )

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if args.cmd == "detect":
        text = " ".join(args.text)
        print("yes" if looks_like_markdown(text) else "no")
        return 0
    if not args.cmd:
        parser.print_help()
        return 1

    try:
        text = _read_input(args.source)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    styled = style_markdown(text, plain=args.plain, backend=args.backend)
    print(styled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
