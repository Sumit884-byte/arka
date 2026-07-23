#!/usr/bin/env python3
"""Read and ask questions about any local markdown file (no ingest required)."""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

_MD_EXT = frozenset({".md", ".mdx", ".markdown"})
_DEFAULT_MAX_CHARS = 120_000
_ASK_MAX_CHARS = 60_000

_MD_PATH_RE = re.compile(
    r"(?i)(?:['\"]([^'\"]+\.(?:md|mdx|markdown))['\"]"
    r"|((?:[\w.-]+/)+[\w.-]+\.(?:md|mdx|markdown))"
    r"|([~./][^\s'\"]+\.(?:md|mdx|markdown))"
    r"|([^\s'\"/\\]+\.(?:md|mdx|markdown))\b)"
)

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"md_doc|use_md|read_md|markdown_doc|"
    r"(?:read|open|show|use|load|follow)\s+(?:the\s+)?(?:markdown|md)\s+file|"
    r"(?:read|open|show|use|load|follow)\s+[\w./~-]+\.(?:md|mdx|markdown)\b|"
    r"[\w./~-]+\.(?:md|mdx|markdown)\s+(?:summarize|summary|explain|ask)"
    r")\b"
)

_ASK_RE = re.compile(
    r"(?i)\b(?:ask|explain|summarize|summary|what|how|tell me about|describe)\b"
)


def resolve_md(path: str | Path, *, cwd: Path | None = None) -> Path:
    raw = Path(str(path).strip().strip("'\"")).expanduser()
    if not raw.is_absolute() and not raw.is_file():
        try:
            from arka.core.design_guides import resolve_markdown_alias

            alias = resolve_markdown_alias(str(path), cwd=cwd)
            if alias:
                raw = Path(alias)
        except ImportError:
            pass
    if not raw.is_absolute():
        base = cwd or Path.cwd()
        raw = (base / raw).resolve()
    else:
        raw = raw.resolve()
    if not raw.is_file():
        raise FileNotFoundError(f"Markdown file not found: {raw}")
    if raw.suffix.lower() not in _MD_EXT:
        raise ValueError(f"Not a markdown file: {raw}")
    return raw


def extract_md_path(text: str) -> str | None:
    match = _MD_PATH_RE.search(text or "")
    if not match:
        return None
    for group in match.groups():
        if group:
            return group.strip().strip("'\"")
    return None


def read_markdown(path: str | Path, *, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    resolved = resolve_md(path)
    text = resolved.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        from arka.core.security import sanitize_llm_context

        cleaned, _ = sanitize_llm_context(text)
        text = (cleaned or text).strip()
    except ImportError:
        pass
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…"
    return text


def context_block(path: str | Path, *, limit_chars: int = 8000) -> str:
    resolved = resolve_md(path)
    body = read_markdown(resolved, max_chars=min(limit_chars, _DEFAULT_MAX_CHARS))
    if not body:
        return ""
    return f"Markdown ({resolved.name}):\n{body}"


def ask_markdown(path: str | Path, question: str, *, max_chars: int = _ASK_MAX_CHARS) -> str:
    resolved = resolve_md(path)
    question = " ".join((question or "").split()).strip()
    if not question:
        raise ValueError("question is required")
    content = read_markdown(resolved, max_chars=max_chars)
    if not content:
        return f"(empty markdown file: {resolved})"

    system = (
        "You answer questions using only the markdown document provided. "
        "Be concise and accurate. If the document does not contain the answer, say so."
    )
    user = f"Document path: {resolved}\n\n{content}\n\nQuestion: {question}"
    try:
        from arka.core.security import apply_llm_security

        blocked, system, user = apply_llm_security(system, user, task="pdf")
        if blocked:
            return blocked
    except ImportError:
        pass
    from arka.llm.cli import llm_complete

    return llm_complete(system, user, task="pdf", skill="md_doc").strip()


def wants_md_doc(text: str) -> bool:
    if not (text or "").strip():
        return False
    if not extract_md_path(text):
        return False
    if _TRIGGER_RE.search(text):
        return True
    if _ASK_RE.search(text):
        return True
    return bool(re.search(r"(?i)\b(?:read|open|show|use|load|follow)\b", text))


_GOOGLE_DESIGN_RE = re.compile(
    r"(?i)\b(?:follow|use|read|open|load)\s+(?:google\s+)?design(?:\.md)?\b"
)


def route_command(text: str) -> str:
    clean = " ".join((text or "").split())
    if _GOOGLE_DESIGN_RE.search(clean) and not _ASK_RE.search(clean):
        return "md_doc read google-design"
    path = extract_md_path(clean)
    if not path:
        return ""
    if not wants_md_doc(clean) and not _MD_PATH_RE.search(clean):
        return ""

    quoted = shlex.quote(path)
    if re.search(r"(?i)\b(?:read|open|show|cat|load|use|follow)\b", clean) and not _ASK_RE.search(clean):
        return f"md_doc read {quoted}"
    if re.search(r"(?i)\b(?:summarize|summary)\b", clean):
        return f'md_doc ask {quoted} "Summarize this document."'
    if _ASK_RE.search(clean):
        question = clean
        for pattern in (
            r"(?i)^(?:please\s+)?(?:ask|explain|summarize|describe)\s+(?:about\s+)?",
            r"(?i)^(?:what|how)\s+(?:does|is|are)\s+",
            r"(?i)[\"']?[^\s\"']+\.(?:md|mdx|markdown)[\"']?\s*",
            r"(?i)\b(?:about|from|in)\s+",
        ):
            question = re.sub(pattern, " ", question).strip()
        question = re.sub(r"\s+", " ", question).strip(" ,.?")
        if not question:
            question = "Summarize this document."
        return f"md_doc ask {quoted} {shlex.quote(question)}"
    return f"md_doc context {quoted}"


def cmd_read(args: argparse.Namespace) -> int:
    print(read_markdown(args.path, max_chars=args.max_chars))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    text = context_block(args.path, limit_chars=args.max_chars)
    if not text:
        print("(empty markdown file)", file=sys.stderr)
        return 1
    print(text)
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    try:
        print(ask_markdown(args.path, " ".join(args.question)))
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    route = route_command(" ".join(args.text))
    print(route)
    return 0 if route else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read or ask about any local .md/.mdx file without document ingest",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_read = sub.add_parser("read", help="Print markdown file contents")
    p_read.add_argument("path")
    p_read.add_argument("--max-chars", type=int, default=_DEFAULT_MAX_CHARS)
    p_read.set_defaults(func=cmd_read)

    p_ctx = sub.add_parser("context", help="Print a context block for agents")
    p_ctx.add_argument("path")
    p_ctx.add_argument("--max-chars", type=int, default=8000)
    p_ctx.set_defaults(func=cmd_context)

    p_ask = sub.add_parser("ask", help="Ask a question with the markdown as context")
    p_ask.add_argument("path")
    p_ask.add_argument("question", nargs="+")
    p_ask.set_defaults(func=cmd_ask)

    p_route = sub.add_parser("route", help="Map natural language to md_doc command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=cmd_route)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
