"""CLI + NL routing for local LLM token usage and savings."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import TextIO

from arka.core.llm_usage import Period, format_report_text, report, reset

_TOKENS_USAGE_RE = re.compile(
    r"(?i)\b("
    r"how\s+much\s+(?:money|did\s+arka\s+save|have\s+i\s+saved|did\s+i\s+save)|"
    r"how\s+many\s+tokens?\s+(?:have\s+i\s+used|did\s+i\s+use|through\s+arka|with\s+arka)|"
    r"(?:show|check|view)\s+(?:my\s+)?(?:arka\s+)?token\s+usage|"
    r"(?:show|check)\s+(?:my\s+)?(?:llm\s+)?(?:token|usage)\s+(?:and\s+)?savings|"
    r"token\s+usage|tokens?\s+used|llm\s+usage|"
    r"how\s+much\s+(?:did\s+)?arka\s+cost|"
    r"money\s+saved\s+(?:by\s+)?arka"
    r")\b"
)


def is_tokens_usage_request(cmd: str) -> bool:
    clean = (cmd or "").strip()
    if not clean:
        return False
    if re.search(r"(?i)^tokens?\s+(usage|report|status)\b", clean):
        return True
    if re.search(r"(?i)^usage\s+tokens?\b", clean):
        return True
    return bool(_TOKENS_USAGE_RE.search(clean))


def route_command(cmd: str) -> str | None:
    if not is_tokens_usage_request(cmd):
        return None
    return "tokens usage"


def _parse_period(argv: list[str]) -> Period:
    for arg in argv:
        low = arg.lower().strip()
        if low in ("today", "day"):
            return "today"
        if low in ("week", "7d", "7days"):
            return "week"
        if low in ("month", "30d", "30days"):
            return "month"
        if low in ("all", "lifetime", "total"):
            return "all"
    return "all"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka tokens", description="Local LLM token usage and savings")
    sub = parser.add_subparsers(dest="cmd")

    p_report = sub.add_parser("usage", help="Show token usage and estimated savings")
    p_report.add_argument("period", nargs="?", default="all", choices=("today", "week", "month", "all"))
    p_report.add_argument("--json", action="store_true", help="Print JSON report")

    p_status = sub.add_parser("status", help="Alias for tokens usage today")
    p_status.add_argument("--json", action="store_true")

    sub.add_parser("reset", help="Clear local token ledger")

    args = parser.parse_args(argv)
    cmd = args.cmd or "usage"

    if cmd == "reset":
        reset()
        print("Token usage ledger cleared.")
        return 0

    period: Period = "today" if cmd == "status" else _parse_period([getattr(args, "period", "all")])
    payload = report(period=period)

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0

    print(format_report_text(period=period))
    return 0


def run_report(*, stream: TextIO | None = None, period: Period = "all") -> int:
    out = stream or sys.stdout
    print(format_report_text(period=period), file=out)
    return 0


__all__ = [
    "is_tokens_usage_request",
    "main",
    "route_command",
    "run_report",
]
