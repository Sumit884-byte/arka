"""Terminal formatting for persona chat output."""

from __future__ import annotations

import re
import sys
import textwrap

from arka.agent.personas.schema import Persona, effective_disclaimer

_WRAP_WIDTH = 88
_INDENT = "  "

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_MD_UNDERSCORE_RE = re.compile(r"_(.+?)_")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def _tty() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _dim(text: str) -> str:
    if not _tty():
        return text
    return f"\033[2m{text}\033[0m"


def persona_header(persona: Persona) -> str:
    label = (persona.display_name or persona.name).strip()
    return f"── {label} ──"


def repl_prompt(persona: Persona) -> str:
    return f"{persona.name}> "


def _disclaimer_text(persona: Persona) -> str:
    return effective_disclaimer(persona).strip()


def format_disclaimer(persona: Persona) -> str:
    """Muted disclaimer block shown once per session."""
    note = f"Note: {_disclaimer_text(persona)}"
    wrapped = textwrap.fill(note, width=_WRAP_WIDTH, initial_indent=_INDENT, subsequent_indent=_INDENT)
    return _dim(wrapped) + "\n\n"


def _clean_markdown(text: str) -> str:
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_UNDERSCORE_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    return text


def format_body(text: str, *, width: int = _WRAP_WIDTH) -> str:
    """Wrap long lines, preserve paragraph breaks, strip light markdown."""
    clean = _clean_markdown((text or "").strip())
    if not clean:
        return ""

    out_lines: list[str] = []
    paragraphs = re.split(r"\n\s*\n", clean)
    for idx, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        if re.match(r"^[\*\-•]\s", para) or re.match(r"^\d+\.\s", para):
            for line in para.splitlines():
                line = line.strip()
                if not line:
                    continue
                wrapped = textwrap.fill(
                    line,
                    width=width,
                    initial_indent=_INDENT,
                    subsequent_indent=_INDENT + "  ",
                )
                out_lines.append(wrapped)
        else:
            for line in para.splitlines():
                line = line.strip()
                if not line:
                    continue
                wrapped = textwrap.fill(
                    line,
                    width=width,
                    initial_indent=_INDENT,
                    subsequent_indent=_INDENT,
                )
                out_lines.append(wrapped)
        if idx < len(paragraphs) - 1:
            out_lines.append("")
    return "\n".join(out_lines).rstrip()


def format_reply(persona: Persona, reply: str) -> str:
    """Persona header plus wrapped response body (no disclaimer)."""
    header = persona_header(persona)
    body = format_body(reply)
    if body:
        return f"{header}\n\n{body}"
    return header


def format_chat(persona: Persona, reply: str, *, show_disclaimer: bool = True) -> str:
    """Full formatted one-shot output as a string."""
    parts: list[str] = []
    if show_disclaimer:
        parts.append(format_disclaimer(persona).rstrip())
    parts.append(format_reply(persona, reply))
    return "\n\n".join(p for p in parts if p)


def print_disclaimer(persona: Persona) -> None:
    print(format_disclaimer(persona), end="")


def print_reply(persona: Persona, reply: str) -> None:
    formatted = format_reply(persona, reply)
    header, _, body = formatted.partition("\n\n")
    print(header)
    if body:
        print()
        print(body)


def print_chat(persona: Persona, reply: str, *, show_disclaimer: bool = True) -> None:
    if show_disclaimer:
        print_disclaimer(persona)
    print_reply(persona, reply)
    print()


def print_repl_reply(persona: Persona, reply: str) -> None:
    print(_dim(repl_prompt(persona)), end="")
    print()
    print_reply(persona, reply)


def print_repl_banner(persona: Persona) -> None:
    print_disclaimer(persona)
    label = persona.display_name or persona.name
    print(f"{_INDENT}{label} persona chat (type 'quit' or Ctrl-D to exit)\n")
