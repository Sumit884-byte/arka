#!/usr/bin/env python3
"""Prefix Arka doc command examples with `arka` inside shell code blocks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"

SHELL_FENCE_OPEN = re.compile(r"^```(?:bash|fish|sh|shell|zsh)\b", re.I)
ANY_FENCE = re.compile(r"^```")

EXEMPT_STARTS = (
    "#",
    "pip ",
    "pip install",
    "uv ",
    "uvx ",
    "npm ",
    "yarn ",
    "pnpm ",
    "brew ",
    "apt ",
    "apt-get ",
    "git ",
    "docker ",
    "cd ",
    "export ",
    "set ",
    "unset ",
    "echo ",
    "mkdir ",
    "cp ",
    "mv ",
    "rm ",
    "chmod ",
    "curl ",
    "wget ",
    "foundryctl ",
    "python3 ",
    "python ",
    "node ",
    "npx ",
    "fish ",
    "source ",
    "./",
    "$",
    "cat ",
    "grep ",
    "open ",
    "xargs ",
    "tee ",
    "which ",
    "test ",
    "kaggle ",
    "mint ",
    "gh ",
    "railway ",
    "vercel ",
    "netlify ",
    "open http",
)

ENV_ASSIGN = re.compile(r"^[A-Z][A-Z0-9_]*=")

ARKA_PREFIX_COMMANDS = re.compile(
    r"^(?:"
    r"route_learn\b|select_model\b|data_ask\b|query_data\b|analyze_data\b|"
    r"view_data\b|view_csv\b|kalshi\b|youtube_\w+\b|compose_3d\b|compose_slides\b|"
    r"generate_music\b|post_x\b|ascii_art\b|gemini_cli\b|subagent\b|heartbeat\b|"
    r"demo_echo\b|free_credits\b|agent_route\b|agent_trace\b|agent_why\b|"
    r"pdf_ingest\b|pdf_ask\b|pdf_tools\b|routines\b|find_videos\b|"
    r"team\b|workflow\b|compose\b|generate\b|skill\b|review\b|route\b|"
    r"babysit\b|check\b|ci\b|deliberate\b|ask\b|quiz\b|practice\b|improve\b|"
    r"self\b|show\b|plot\b|visualize\b|make\b|graph\b|chart\b|elon\b|talk\b|"
    r"remember\b|learn\b|list\b|teach\b|deploy\b|download\b|summarize\b|"
    r"how\b|agent\b|chat_reset\b|map_download\b|yt_download\b|yt_bulk\b|"
    r"playlist_summarize\b|talk_to_elon\b|profession\b|predictions\b|"
    r"integration\b|speak\b|meme\b|capture\b|benchmark\b|predict\b|"
    r"backend\b|session\b|site_summary\b|orchestrate\b|coding-tui\b"
    r")"
)

# Table backtick examples that should include arka (skills/catalog pages).
TABLE_CMD = re.compile(
    r"(\|\s*`)([^`|]{3,})(`\s*\|)"
)
TABLE_SKILL = re.compile(
    r"^(?:route_learn|select_model|data_ask|query_data|analyze_data|view_data|"
    r"view_csv|kalshi|youtube_|compose_3d|compose_slides|generate_music|post_x|"
    r"ascii_art|gemini_cli|pdf_ingest|pdf_ask|pdf_tools|routines|find_videos|"
    r"make 3d|generate stl|compose 3d|talk to|elon |youtube_download|youtube_bulk|"
    r"youtube_transcript|youtube_research|subagent|heartbeat|free_credits|"
    r"demo_echo|agent_route|agent_trace|agent_why|chat_reset|map_download|"
    r"yt_download|yt_bulk|playlist_summarize|talk_to_elon|predictions|"
    r"profession setup)",
    re.I,
)


def _exempt(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.startswith(("arka ", "arka\t", 'arka "')) or s == "arka":
        return True
    low = s.lower()
    for p in EXEMPT_STARTS:
        if low.startswith(p):
            return True
    if ENV_ASSIGN.match(s):
        return True
    return False


def _fix_agent(line: str) -> str | None:
    if line.startswith('agent "') and not line.startswith('arka '):
        return 'arka "' + line.split('"', 1)[1]
    if line.startswith('agent_route "') and not line.startswith('arka '):
        return 'arka route "' + line.split('"', 1)[1]
    if line.startswith("agent_route ") and not line.startswith("arka "):
        return "arka route " + line[len("agent_route ") :]
    if line.startswith("agent_trace") and not line.startswith("arka "):
        rest = line[len("agent_trace") :].lstrip()
        return ("arka route " + rest) if rest else "arka route"
    if line.startswith("agent_why") and not line.startswith("arka "):
        rest = line[len("agent_why") :].lstrip()
        return ("arka route " + rest) if rest else "arka route"
    return None


def _looks_like_nl(line: str) -> bool:
    if line.startswith("-") or line.startswith('"'):
        return False
    if ARKA_PREFIX_COMMANDS.match(line):
        return False
    if re.match(r"^[a-z_]+(?:\s+[a-z_]+)*\s+-", line):
        return False
    return bool(re.match(r'^[\w\s",./\-\'():+$]+$', line, re.I))


def fix_shell_line(line: str) -> str:
    indent = line[: len(line) - len(line.lstrip())]
    body = line.strip()
    if body.startswith("|") and body.count("|") >= 2:
        return line
    if _exempt(body):
        return line

    agent = _fix_agent(body)
    if agent:
        return indent + agent

    if "|" in body:
        parts = body.split("|")
        out = []
        for i, part in enumerate(parts):
            piece = part.strip()
            if i == 0 and (_exempt(piece) or piece.startswith("cat ")):
                out.append(part if i == 0 else piece)
            else:
                fixed = fix_shell_line(indent + piece).strip()
                out.append(fixed)
        joiner = " | " if " | " in body else "|"
        return indent + joiner.join(out)

    if ARKA_PREFIX_COMMANDS.match(body):
        # Multi-word natural language → quote for copy-paste clarity.
        parts = body.split()
        if len(parts) > 1 and not any(p.startswith("-") for p in parts[1:]):
            first = parts[0]
            rest = " ".join(parts[1:])
            if first in {
                "babysit", "check", "review", "how", "learn", "remember", "teach",
                "deliberate", "quiz", "practice", "improve", "make", "show", "plot",
                "visualize", "graph", "talk", "summarize", "list",
            }:
                return indent + f'arka "{body}"'
        return indent + "arka " + body

    if _looks_like_nl(body):
        if body.startswith('"') and body.endswith('"'):
            return indent + "arka " + body
        return indent + f'arka "{body}"'

    return line


def fix_table_example_line(line: str) -> str:
    if not line.strip().startswith("|") or "`" not in line:
        return line
    # Skip header/separator rows
    if re.match(r"^\|\s*[-—]", line) or "Description" in line or "描述" in line or "Command" in line and "Description" in line:
        return line

    def repl(m: re.Match[str]) -> str:
        inner = m.group(2).strip()
        if inner.startswith("arka ") or _exempt(inner):
            return m.group(0)
        if not TABLE_SKILL.match(inner):
            return m.group(0)
        fixed = fix_shell_line(inner).strip()
        return m.group(1) + fixed + m.group(3)

    return TABLE_CMD.sub(repl, line)


def process_file(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    in_fence = False
    in_shell = False
    changes = 0

    for line in lines:
        stripped = line.rstrip("\n")
        if ANY_FENCE.match(stripped.strip()):
            if not in_fence:
                in_fence = True
                in_shell = bool(SHELL_FENCE_OPEN.match(stripped.strip()))
            else:
                in_fence = False
                in_shell = False
            out.append(line)
            continue

        if in_shell:
            fixed = fix_shell_line(stripped)
        else:
            fixed = fix_table_example_line(stripped)

        if fixed != stripped:
            changes += 1
        out.append(fixed + ("\n" if line.endswith("\n") else ""))

    if changes:
        path.write_text("".join(out), encoding="utf-8")
    return changes


def main() -> int:
    total = 0
    for path in sorted(DOCS_ROOT.rglob("*.mdx")) + sorted(DOCS_ROOT.rglob("*.md")):
        n = process_file(path)
        if n:
            print(f"{path.relative_to(DOCS_ROOT.parent)}: {n}")
            total += n
    print(f"Total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
