#!/usr/bin/env python3
"""Smoke-test documented Arka CLI commands (read-only / low-impact)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Case:
    name: str
    argv: list[str]
    expect_code: int | None = 0
    expect_in: str | None = None


CASES = [
    Case("version", ["--version"], expect_in="arka"),
    Case("help", ["help"], expect_in="Arka Help"),
    Case("capabilities", ["capabilities"], expect_in="Skills"),
    Case("doctor", ["doctor"], expect_in="Next steps"),
    Case("route", ["route", "what can you do"], expect_in="skill:"),
    Case("mode list", ["mode", "list"], expect_in="agent"),
    Case("provider list", ["provider", "list"], expect_in="slug"),
    Case("ai-models", ["ai-models"], expect_in="default"),
    Case("session status", ["session", "status"], expect_in="Message sessions"),
    Case("session list", ["session", "list"], expect_in=":"),
    Case("platform show", ["platform", "show"], expect_in="platform:"),
    Case("mcp doctor", ["mcp", "doctor"], expect_in="summary"),
    Case("meme help", ["meme", "--help"], expect_in="vibe-coding"),
    Case("capture help", ["capture", "video", "--help"], expect_in="walkthrough"),
    Case("generate music help", ["generate", "music", "--help"], expect_in="instrumental"),
    Case("route music", ["route", "generate music lo-fi instrumental"], expect_in="generate_music"),
    Case("route capture", ["route", "capture walkthrough of the arka web dashboard"], expect_in="capture video"),
    Case("plugins list", ["plugins", "list"], expect_in="skills"),
]


def run(case: Case) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "arka", *case.argv],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if case.expect_code is not None and proc.returncode != case.expect_code:
        return False, f"exit {proc.returncode}\n{out[:400]}"
    if case.expect_in and case.expect_in not in out:
        return False, f"missing {case.expect_in!r}\n{out[:400]}"
    return True, out.splitlines()[0][:120] if out else "(empty)"


def main() -> int:
    failed: list[str] = []
    for case in CASES:
        ok, detail = run(case)
        status = "ok" if ok else "FAIL"
        print(f"[{status}] {case.name}: {detail}")
        if not ok:
            failed.append(case.name)
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        return 1
    print(f"\nAll {len(CASES)} CLI smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
