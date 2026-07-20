"""Turn developer video recordings into docs, PR context, or bug tickets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from arka.media.convert_media import VIDEO_EXTS


VIDEO_EXT_RE = "|".join(ext.lstrip(".") for ext in sorted(VIDEO_EXTS))
KNOWN_KINDS = {"architecture", "pr", "bug"}


def _extract_video_source(text: str) -> str | None:
    url = re.search(r"https?://[^\s\"']+\.(?:" + VIDEO_EXT_RE + r")(?:\?[^\s\"']*)?", text, re.I)
    if url:
        return url.group(0).rstrip(".,)")
    path = re.search(
        rf"((?:~|\.|/|[\w.-]+/)[\w./ -]*\.(?:{VIDEO_EXT_RE})|[\w.-]+\.(?:{VIDEO_EXT_RE}))",
        text,
        re.I,
    )
    return path.group(1).strip("'\"") if path else None


def infer_kind(text: str) -> str:
    clean = text.lower()
    if re.search(r"\b(?:architecture|whiteboard|whiteboarding|system design|design review)\b", clean):
        return "architecture"
    if re.search(r"\b(?:pr|pull request|merge request|gitlab|github|repro|reproduction)\b", clean):
        return "pr"
    if re.search(r"\b(?:bug|jira|ticket|jam|loom|issue|defect|screen recording)\b", clean):
        return "bug"
    return "bug"


def route_command(text: str) -> str:
    source = _extract_video_source(text)
    if not source:
        return ""
    if not re.search(r"(?i)\b(?:architecture|whiteboard|docs?|documentation|code stubs?|pr|pull request|merge request|bug|jira|ticket|jam|loom|repro|reproduction|screen recording|video)\b", text):
        return ""
    if not re.search(r"(?i)\b(?:architecture|whiteboard|docs?|documentation|code stubs?|pr|pull request|merge request|bug|jira|ticket|jam|loom|repro|reproduction|screen recording)\b", text):
        return ""
    kind = infer_kind(text)
    return f"video_evidence {kind} {shlex.quote(source)}"


def _artifact_name(source: str, kind: str, fmt: str) -> str:
    stem = Path(source).stem if not source.startswith(("http://", "https://")) else "remote-video"
    safe = re.sub(r"[^a-z0-9._-]+", "-", stem.lower()).strip("-") or "video-evidence"
    return f"{safe}-{kind}.{fmt}"


def _describe(source: str, kind: str, *, frames: int) -> str:
    prompts = {
        "architecture": (
            "Analyze this architecture meeting or whiteboarding recording. Extract systems, services, data flows, "
            "integration points, decisions, open questions, and code stubs that should exist."
        ),
        "pr": (
            "Analyze this UI bug reproduction recording for pull-request context. Extract exact reproduction steps, "
            "expected vs actual behavior, visible logs/errors, screenshots worth attaching, and likely touched areas."
        ),
        "bug": (
            "Analyze this video bug report as a Jira-ready issue. Extract summary, environment clues, steps to reproduce, "
            "expected result, actual result, severity hints, logs/text visible on screen, and screenshots worth attaching."
        ),
    }
    try:
        from arka.vision.video import describe_video

        return describe_video(source, prompts[kind], frame_count=frames)
    except BaseException as exc:  # noqa: BLE001 - keep evidence generation useful when vision deps are missing.
        return f"Video analysis unavailable: {exc}"


def build_artifact(source: str, kind: str, *, frames: int = 5) -> dict[str, Any]:
    if kind not in KNOWN_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(KNOWN_KINDS))}")
    analysis = _describe(source, kind, frames=frames)
    if kind == "architecture":
        title = "Architecture recording notes"
        sections = {
            "System overview": "Summarize components, actors, boundaries, and major responsibilities from the recording.",
            "Data and control flow": "Document request/event/data movement, sync vs async behavior, and persistence points.",
            "Decisions": "List decisions explicitly stated or strongly evidenced by the recording.",
            "Open questions": "List unresolved tradeoffs or missing owner/API details.",
            "Code stubs": "Name likely modules, interfaces, routes, schemas, jobs, or tests to scaffold.",
        }
    elif kind == "pr":
        title = "PR video reproduction context"
        sections = {
            "Summary": "One-paragraph bug/reproduction summary for the pull request.",
            "Steps to reproduce": "Numbered steps observed in the recording.",
            "Expected behavior": "What the UI or system should have done.",
            "Actual behavior": "What the recording shows instead.",
            "Evidence to attach": "Screenshots, console text, timestamps, or logs worth attaching.",
            "Suggested verification": "Focused tests or manual checks for the engineer.",
        }
    else:
        title = "Video bug report ticket"
        sections = {
            "Summary": "Jira-ready issue title and short description.",
            "Environment clues": "Browser, viewport, route, account state, feature flags, or device clues visible in the recording.",
            "Steps to reproduce": "Numbered reproduction steps.",
            "Expected result": "Expected product behavior.",
            "Actual result": "Observed behavior from the recording.",
            "Attachments": "Screenshots, frame timestamps, logs, and the original video link/path.",
            "Acceptance criteria": "How the fix should be verified.",
        }
    return {
        "kind": kind,
        "source": source,
        "title": title,
        "analysis": analysis,
        "sections": sections,
    }


def render_markdown(artifact: dict[str, Any]) -> str:
    lines = [f"# {artifact['title']}", "", f"Source: `{artifact['source']}`", "", "## Raw video evidence", "", artifact["analysis"].strip(), ""]
    for heading, guidance in artifact["sections"].items():
        lines.extend([f"## {heading}", "", guidance, ""])
    return "\n".join(lines).strip() + "\n"


def write_artifact(artifact: dict[str, Any], output: Path | None = None, *, fmt: str = "md") -> Path:
    target = output or (Path.cwd() / _artifact_name(str(artifact["source"]), str(artifact["kind"]), fmt))
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        target.write_text(render_markdown(artifact), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka video-evidence", description="Convert developer recordings into docs, PR context, or bug tickets")
    sub = parser.add_subparsers(dest="kind")
    for kind in sorted(KNOWN_KINDS):
        p = sub.add_parser(kind)
        p.add_argument("source")
        p.add_argument("--frames", type=int, default=5)
        p.add_argument("--output")
        p.add_argument("--format", choices=("md", "json"), default="md")
    p_parse = sub.add_parser("parse", help="Parse natural language → video_evidence command")
    p_parse.add_argument("text", nargs="+")
    args = parser.parse_args(argv or ["--help"])
    if args.kind == "parse":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if args.kind not in KNOWN_KINDS:
        parser.print_help()
        return 1
    try:
        artifact = build_artifact(args.source, args.kind, frames=max(1, min(20, args.frames)))
        out = write_artifact(artifact, Path(args.output).expanduser() if args.output else None, fmt=args.format)
        print(f"video_evidence\t{args.kind}\t{out}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"video evidence error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
