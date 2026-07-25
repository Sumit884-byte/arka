"""Write human-sounding README and markdown docs to files, not chat."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def route_command(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""
    if not re.search(
        r"(?i)\b(?:write|draft|create|update|rewrite|generate|compose)\b.*"
        r"\b(?:readme|changelog|contributing|markdown|\.md|docs?|release notes)\b",
        clean,
    ) and not re.search(
        r"(?i)\b(?:readme|changelog|contributing)\b.*"
        r"\b(?:write|draft|create|update|rewrite|human|sound)\b",
        clean,
    ):
        return ""
    if not re.search(
        r"(?i)\b(?:human|natural|sound|readme|changelog|contributing|markdown|docs?)\b",
        clean,
    ):
        return ""
    import shlex

    return "human_docs write " + shlex.quote(clean)


def _llm_write(system: str, user: str) -> str:
    try:
        from arka.llm.complete import llm_complete

        return llm_complete(system, user, temperature=0.55, task="chat").strip()
    except ImportError:
        from arka.agent.core import _llm

        return _llm(system, user, temperature=0.55, task="chat")


def _system_prompt() -> str:
    try:
        from arka.core.human_docs import read_guide

        guide = read_guide(max_chars=4000)
    except ImportError:
        guide = ""
    base = (
        "You write markdown documentation for humans. Output ONLY the markdown file body—"
        "no preamble, no 'Here is your README', no code fences around the whole document. "
        "Sound like a developer wrote it: direct, concrete, varied sentences, no AI filler."
    )
    if guide:
        return base + "\n\nFollow this guide:\n" + guide
    return base


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$", stripped)
    if m:
        return m.group(1).strip()
    return stripped


def write_doc(
    prompt: str,
    *,
    out: str | None = None,
    apply: bool = False,
    context_path: str | None = None,
) -> dict[str, object]:
    target = Path(out or suggest_output(prompt)).expanduser()
    user_parts = [f"Task: {prompt}", f"Target file: {target.name}"]
    if context_path:
        ctx = Path(context_path).expanduser()
        if ctx.is_file():
            user_parts.append(f"Existing file to revise (preserve accurate facts):\n{ctx.read_text(encoding='utf-8')[:12000]}")
    elif target.is_file():
        user_parts.append(
            "An existing file is at this path; improve it in place unless the task says replace."
        )
    body = _strip_code_fence(_llm_write(_system_prompt(), "\n\n".join(user_parts)))
    if not body:
        raise ValueError("LLM returned empty document")
    result: dict[str, object] = {
        "path": str(target),
        "bytes": len(body.encode("utf-8")),
        "applied": False,
        "preview_lines": len(body.splitlines()),
    }
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            result["overwrote"] = True
        target.write_text(body.rstrip() + "\n", encoding="utf-8")
        result["applied"] = True
    else:
        result["body"] = body
    return result


def suggest_output(prompt: str) -> str:
    from arka.core.human_docs import suggest_output_path

    return suggest_output_path(prompt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka human_docs",
        description="Write human-sounding README/markdown to files instead of chat",
    )
    sub = parser.add_subparsers(dest="cmd")

    write_p = sub.add_parser("write", help="Generate markdown and optionally write to disk")
    write_p.add_argument("prompt", nargs="+")
    write_p.add_argument("--out", "-o", help="Output path (default: inferred from prompt)")
    write_p.add_argument("--apply", action="store_true", help="Write the file (default: print JSON preview)")
    write_p.add_argument("--context", help="Existing markdown file to revise")

    sub.add_parser("guide", help="Print the human-docs writing guide")
    sub.add_parser("status", help="Show bias configuration")

    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))

    if args.cmd == "guide":
        from arka.core.human_docs import read_guide

        print(read_guide())
        return 0
    if args.cmd == "status":
        from arka.core.human_docs import status

        print(json.dumps(status(), indent=2))
        return 0
    if args.cmd == "write":
        prompt = " ".join(args.prompt)
        try:
            result = write_doc(
                prompt,
                out=args.out,
                apply=args.apply,
                context_path=args.context,
            )
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if args.apply:
            print(f"Wrote {result['path']} ({result['bytes']} bytes)")
            return 0
        print(json.dumps(result, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
