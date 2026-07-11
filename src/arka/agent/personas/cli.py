#!/usr/bin/env python3
"""CLI for creating and chatting with simulated personas."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys

from arka.agent.personas.base import chat_once, chat_repl, sanitize_prompt
from arka.agent.personas.io import (
    ensure_layout,
    format_persona_list,
    format_persona_show,
    load_template,
    persona_exists,
    resolve_persona,
    save_persona,
)
from arka.agent.personas.schema import DEFAULT_DISCLAIMER, Persona, parse_persona, slugify


def _prompt(label: str, *, default: str = "", multiline: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    if multiline:
        print(f"{label}{suffix} (end with blank line):")
        lines: list[str] = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line.strip() and lines:
                break
            lines.append(line)
        text = "\n".join(lines).strip()
        return text or default
    try:
        value = input(f"{label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return value or default


def _generate_persona_draft(subject: str) -> Persona:
    from arka.agent.personas.base import _llm_reply

    slug = slugify(subject)
    display = subject.strip().title()
    system = (
        "You draft YAML-ready fields for a simulated entertainment/education persona. "
        "Output ONLY valid JSON with keys: display_name, description, voice, system_prompt, disclaimer. "
        "The persona must never claim to be the real person. "
        "disclaimer must say it is simulated, not the real person."
    )
    user = (
        f"Create a simulated persona inspired by public knowledge of {subject!r}. "
        f"Slug name is {slug!r}. Keep system_prompt under 400 words."
    )
    raw = _llm_reply(system, user, skill="persona:create")
    import json

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if "{" in raw and "}" in raw:
            data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        else:
            raise ValueError("LLM did not return JSON for persona draft") from None
    data["name"] = slug
    return parse_persona(data)


def cmd_create(name: str, *, template: str | None = None, yes: bool = False) -> int:
    ensure_layout()
    slug = slugify(name)
    if persona_exists(slug) and not yes:
        print(f"Persona already exists: {slug}", file=sys.stderr)
        print(f"Edit with: arka persona edit {slug}", file=sys.stderr)
        return 1

    if template:
        src = load_template(template)
        persona = Persona(
            name=slug,
            display_name=src.display_name if slug == template else slug.replace("-", " ").title(),
            description=src.description,
            system_prompt=src.system_prompt,
            disclaimer=src.disclaimer,
            voice=src.voice,
        )
    elif yes:
        persona = _generate_persona_draft(name)
        persona.name = slug
    else:
        print(f"Creating persona: {slug}\n")
        use_llm = _prompt("Generate draft with LLM? (y/N)", default="n").lower() in {
            "y",
            "yes",
        }
        if use_llm:
            try:
                persona = _generate_persona_draft(name)
                persona.name = slug
                print(f"\nDraft generated for {persona.display_name}.\n")
            except Exception as exc:
                print(f"LLM draft failed ({exc}); falling back to manual entry.\n")
                persona = Persona(name=slug, display_name="", system_prompt="")
        else:
            tmpl = "blank"
            src = load_template(tmpl)
            persona = Persona(
                name=slug,
                display_name=slug.replace("-", " ").title(),
                description=src.description,
                system_prompt=src.system_prompt,
                disclaimer=src.disclaimer,
                voice=src.voice,
            )

        persona.display_name = _prompt("Display name", default=persona.display_name)
        persona.description = _prompt("Description", default=persona.description)
        persona.voice = _prompt("Voice hints (optional)", default=persona.voice)
        persona.disclaimer = _prompt("Disclaimer", default=persona.disclaimer or DEFAULT_DISCLAIMER)
        persona.system_prompt = _prompt(
            "System prompt",
            default=persona.system_prompt,
            multiline=True,
        )

    if not persona.system_prompt.strip():
        print("System prompt is required.", file=sys.stderr)
        return 1

    path = save_persona(persona)
    print(f"Saved persona {persona.name} → {path}")
    print(f"Try: arka persona chat {persona.name}")
    return 0


def cmd_edit(name: str) -> int:
    slug = slugify(name)
    persona = resolve_persona(slug)
    editor = os.environ.get("EDITOR", "nano")
    from arka.agent.personas.io import _config_path, personas_dir

    path = _config_path(personas_dir(), slug)
    if not path:
        print(f"Persona not found: {slug}", file=sys.stderr)
        return 1
    print(f"Opening {path} …")
    try:
        subprocess.run([editor, str(path)], check=False)
    except FileNotFoundError:
        print(format_persona_show(slug))
        print(f"\nSet EDITOR or edit: {path}")
    return 0


def cmd_chat(name: str, question: str | None = None) -> int:
    slug = slugify(name)
    try:
        persona = resolve_persona(slug)
    except FileNotFoundError:
        print(f"Persona not found: {slug}", file=sys.stderr)
        print(f"Create one: arka persona create {slug}", file=sys.stderr)
        return 1

    if not question or question.strip().lower() == "chat":
        return chat_repl(persona)

    print(persona.formatted_disclaimer, end="")
    answer = chat_once(persona, question)
    if not answer:
        print("Could not get a reply (check LLM API keys)", file=sys.stderr)
        return 1
    print(answer)
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])

    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    parser = argparse.ArgumentParser(prog="arka persona", description="Simulated persona chat")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List saved personas")

    show_p = sub.add_parser("show", help="Show persona details")
    show_p.add_argument("name")

    create_p = sub.add_parser("create", help="Create a persona")
    create_p.add_argument("name")
    create_p.add_argument("--template", "-t", help="Start from bundled template (elon, socrates, blank)")
    create_p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Non-interactive: LLM-generate draft from name",
    )

    edit_p = sub.add_parser("edit", help="Edit persona YAML in $EDITOR")
    edit_p.add_argument("name")

    chat_p = sub.add_parser("chat", help="Chat with a persona")
    chat_p.add_argument("name")
    chat_p.add_argument("question", nargs="?", default="")

    parse_p = sub.add_parser("parse", help="Parse NL into persona argv (internal)")
    parse_p.add_argument("text")

    if not raw:
        print(format_persona_list())
        return 0

    if raw[0] not in {"list", "show", "create", "chat", "edit", "parse", "-h", "--help"}:
        # Shorthand: persona chat NAME [question]
        if raw[0] == "chat":
            rest = raw[1:]
        else:
            rest = raw
        if not rest:
            print(format_persona_list())
            return 0
        name = rest[0]
        question = " ".join(rest[1:]).strip() if len(rest) > 1 else ""
        return cmd_chat(name, question or None)

    args = parser.parse_args(raw)

    if args.cmd == "list":
        print(format_persona_list())
        return 0
    if args.cmd == "show":
        print(format_persona_show(args.name))
        return 0
    if args.cmd == "create":
        return cmd_create(args.name, template=args.template, yes=args.yes)
    if args.cmd == "edit":
        return cmd_edit(args.name)
    if args.cmd == "chat":
        q = args.question.strip() if args.question else ""
        return cmd_chat(args.name, q or None)
    if args.cmd == "parse":
        from arka.agent.personas.base import nl_to_argv

        argv_out = nl_to_argv(args.text)
        if argv_out:
            print(" ".join(shlex.quote(a) for a in argv_out))
        return 0

    parser.print_help()
    return 1


def _print_help() -> None:
    print(
        """Simulated persona chat (entertainment/education only)

Usage:
  arka persona list
  arka persona show <name>
  arka persona create <name> [--template elon|socrates|blank] [-y]
  arka persona chat <name> ["question"]
  arka persona edit <name>

Shortcuts:
  elon [question]              Same as: arka persona chat elon
  talk to elon about rockets   Natural-language routing via arka

Examples:
  arka persona create steve-jobs -y
  arka talk to socrates about virtue
  arka create persona for marie curie
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
