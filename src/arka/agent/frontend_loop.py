#!/usr/bin/env python3
"""Review frontend screenshots and retry a build loop when polish is not good enough."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from arka.vision.describe import describe_source

_KNOWN_CMDS = frozenset({"review", "parse", "help"})

FRONTEND_REVIEW_PROMPT = (
    "Review this frontend screenshot as a senior product designer and frontend engineer. "
    "Return ONLY JSON with keys: verdict ('good' or 'retry'), score (0-10), "
    "reasons (array of short strings), fixes (array of short strings), and summary (one short sentence). "
    "Be strict about hierarchy, spacing, typography, alignment, contrast, visual balance, "
    "spacing consistency, and obvious layout bugs. If the UI is ready to ship, verdict must be 'good'."
    " Recommend layout changes only; preserve the existing button order and interaction order exactly."
    " Flag user-visible copy that exposes tech stack, internal tools, profit/non-profit status, or ops details."
)


def _review_prompt(prompt: str = FRONTEND_REVIEW_PROMPT) -> str:
    try:
        from arka.core.design_guides import read_guides

        guide = read_guides(max_chars=1200, coding=True)
        if guide:
            return (
                f"{prompt}\n\nApply these UI design guides when judging layout, tokens, and copy:\n{guide}"
            )
    except ImportError:
        pass
    return prompt


def _normalize(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t


def _looks_like_frontend_target(text: str) -> bool:
    t = text.lower()
    reviewish = r"\b(review|inspect|evaluate|judge|polish|improve|retry|iterate|critique)\b"
    return bool(
        re.search(reviewish, t)
        and (
            re.search(r"\b(frontend|ui|ux|design|mockup|wireframe|website|webapp|landing\s+page)\b", t)
            or re.search(r"\b(app|site|page|screen)\b", t)
        )
    )


def parse_request(text: str) -> tuple[str | None, int, str, str | None]:
    raw = _normalize(text)
    if not raw:
        return None, 1, FRONTEND_REVIEW_PROMPT, None

    loops = 1
    m = re.search(r"(?i)\b(?:for|within|up\s+to|max(?:imum)?)\s+(?P<n>\d+)\s+loops?\b", raw)
    if m:
        loops = max(1, int(m.group("n")))
    else:
        m = re.search(r"(?i)\b(?:retry|loop)\s+(?P<n>\d+)\s+(?:times?|loops?)\b", raw)
        if m:
            loops = max(1, int(m.group("n")))
        else:
            m = re.search(r"(?i)\b(?P<n>\d+)\s+loops?\b", raw)
            if m:
                loops = max(1, int(m.group("n")))

    retry_cmd = None
    m = re.search(r'(?i)\b(?:retry|regenerate|rerun|rebuild)\s+(?P<cmd>(?:--)?[^\n]+)$', raw)
    if m:
        retry_cmd = m.group("cmd").strip()

    source_match = re.search(
        r'(?P<source>(?:~|/|\./|\.\./)[^\s"\']+|[^\s"\']+\.(?:png|jpe?g|webp|gif|bmp|tiff?|heic|svg|html?|json))',
        raw,
        re.I,
    )
    if source_match:
        source = source_match.group("source").strip("'\"")
        prompt = raw if raw else FRONTEND_REVIEW_PROMPT
        return source, loops, prompt, retry_cmd

    if _looks_like_frontend_target(raw):
        return raw, loops, FRONTEND_REVIEW_PROMPT, retry_cmd
    return None, loops, FRONTEND_REVIEW_PROMPT, retry_cmd


def nl_to_argv(text: str) -> list[str]:
    source, loops, prompt, retry_cmd = parse_request(_normalize(text))
    if not source:
        return []
    argv = ["review", source, "--loops", str(loops), "--prompt", prompt]
    if retry_cmd:
        argv.extend(["--retry", retry_cmd])
    return argv


def route_command(text: str) -> str:
    raw = _normalize(text)
    if not raw or not _looks_like_frontend_target(raw):
        return ""
    argv = nl_to_argv(raw)
    if not argv:
        return ""
    return "frontend_loop " + " ".join(shlex.quote(a) for a in argv)


def _parse_json_block(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    for candidate in (cleaned, re.search(r"\{.*\}", cleaned, re.S).group(0) if re.search(r"\{.*\}", cleaned, re.S) else ""):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


@dataclass(frozen=True)
class ReviewResult:
    verdict: str
    score: int
    reasons: list[str]
    fixes: list[str]
    summary: str
    raw: str


def review_frontend(source: str, *, prompt: str = FRONTEND_REVIEW_PROMPT) -> ReviewResult:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            text = describe_source(source, _review_prompt(prompt))
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.2)
    else:
        return ReviewResult("retry", 0, [f"vision backend unavailable after reconnect: {last_error}"], ["retry with an available local or hosted vision backend"], "Vision inspection did not complete after a reconnect attempt.", str(last_error))
    parsed = _parse_json_block(text) or {}
    verdict = str(parsed.get("verdict") or "").strip().lower()
    score_raw = parsed.get("score", 0)
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        score = 0
    reasons = [str(x).strip() for x in parsed.get("reasons", []) if str(x).strip()]
    fixes = [str(x).strip() for x in parsed.get("fixes", []) if str(x).strip()]
    summary = str(parsed.get("summary") or "").strip()
    if verdict not in {"good", "retry"}:
        verdict = "good" if re.search(r"(?i)\b(ready|ship|good|clean|polished)\b", text) else "retry"
    if score <= 0 and verdict == "good":
        score = 7
    return ReviewResult(verdict=verdict, score=score, reasons=reasons, fixes=fixes, summary=summary, raw=text)


def _run_retry(command: str, *, cwd: Path | None = None) -> None:
    args = shlex.split(command)
    if not args:
        raise SystemExit("retry command is empty")
    proc = subprocess.run(args, cwd=str(cwd) if cwd else None, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"retry command failed with exit code {proc.returncode}")


def run_frontend_loop(
    source: str,
    *,
    loops: int = 1,
    prompt: str = FRONTEND_REVIEW_PROMPT,
    retry: str | None = None,
    cwd: Path | None = None,
    stream=None,
) -> ReviewResult:
    out = stream or sys.stderr
    loops = max(1, int(loops))
    last = ReviewResult("retry", 0, [], [], "", "")
    for attempt in range(1, loops + 1):
        last = review_frontend(source, prompt=prompt)
        print(
            f"Frontend review {attempt}/{loops}: {last.verdict} (score {last.score}/10)",
            file=out,
        )
        if last.summary:
            print(f"  {last.summary}", file=out)
        for reason in last.reasons[:4]:
            print(f"  - {reason}", file=out)
        if last.verdict == "good":
            return last
        if attempt < loops and retry:
            print(f"  Retrying with: {retry}", file=out)
            _run_retry(retry, cwd=cwd)
    return last


def cmd_review(args: argparse.Namespace) -> int:
    source = args.source
    if not source:
        raise SystemExit("source is required")
    result = run_frontend_loop(
        source,
        loops=args.loops,
        prompt=args.prompt or FRONTEND_REVIEW_PROMPT,
        retry=args.retry,
        cwd=Path(args.cwd).expanduser() if args.cwd else None,
    )
    if args.json:
        print(json.dumps({"source": source, "verdict": result.verdict, "score": result.score if result.score > 0 else None, "status": "completed" if result.score > 0 or result.verdict == "good" else "vision_backend_unavailable", "reasons": result.reasons, "fixes": result.fixes, "summary": result.summary, "raw": result.raw}, indent=2))
    if result.verdict != "good":
        return 1
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(_normalize(" ".join(args.text)))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Review frontend screenshots and retry until good enough")
    sub = p.add_subparsers(dest="cmd")

    p_review = sub.add_parser("review", help="Review a screenshot or frontend artifact")
    p_review.add_argument("source", help="Image, HTML file, or URL to inspect")
    p_review.add_argument("--loops", type=int, default=1, help="Maximum review/retry loops")
    p_review.add_argument("--prompt", default=FRONTEND_REVIEW_PROMPT)
    p_review.add_argument("--retry", default="", help="Command to run before the next retry")
    p_review.add_argument("--cwd", default="", help="Working directory for retry commands")
    p_review.add_argument("--json", action="store_true", help="Print a structured bug report")
    p_review.set_defaults(func=cmd_review)

    p_parse = sub.add_parser("parse", help="Parse natural language → frontend_loop args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    sub.add_parser("help", help="Show usage").set_defaults(
        func=lambda _a: (build_parser().print_help(), 0)[1]
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _KNOWN_CMDS:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            argv = ["review", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
