#!/usr/bin/env python3
"""Capture real arka command output for extra CLI showcase JPGs (sanitized)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT_DIR = ROOT / "terminal_captures_extra"
META_FILE = OUT_DIR / "capture_meta.json"

HOME = Path.home()
ARKA_CANDIDATES = [
    Path(os.environ.get("ARKA_BIN", "")),
    REPO / "venv-arka" / "bin" / "arka",
    Path.home() / "miniforge3/bin/arka",
    Path.home() / ".local/bin/arka",
]

# (capture_name, cli_args, timeout_sec, module_fallback)
CaptureSpec = tuple[str, list[str], float, list[str] | None]

CAPTURES: list[CaptureSpec] = [
    ("skills_list", ["skills", "list"], 90, ["-m", "arka.agent.skills", "list"]),
    ("repo_health", ["repo_health"], 90, ["-m", "arka.agent.repo_health"]),
    ("dev_route_audit", ["dev", "route-audit"], 90, ["-m", "arka.agent.dev_tools", "route-audit"]),
    ("route_chart_btc", ["route", "chart BTC"], 30, None),
    ("chart_bar", ["chart", "bar", "--data", "Apple:230,Samsung:210,Google:180", "--title", "Phone sales"], 30, ["-m", "arka.charts.plot", "bar", "--data", "Apple:230,Samsung:210,Google:180", "--title", "Phone sales"]),
    ("compose_slides", ["compose", "slides", "AI agents"], 90, None),
    ("compose_3d_help", ["compose", "3d", "--help"], 45, ["-m", "arka.media.compose_3d", "--help"]),
    ("password_list", ["password", "list"], 30, ["-m", "arka.agent.password_vault", "list"]),
    ("bookmark_list", ["bookmark", "list"], 45, ["-m", "arka.agent.bookmarks", "list"]),
    ("docker_ps", ["docker", "ps"], 30, ["-m", "arka.integrations.docker_status", "ps"]),
    ("github_help", ["github", "--help"], 45, ["-m", "arka.agent.github_repo", "--help"]),
    ("agent_hub_list", ["agent_hub", "list"], 30, None),
    ("self_improve_status", ["self-improve", "status"], 45, ["-m", "arka.agent.self_improve", "status"]),
    ("remind_help", ["remind", "--help"], 30, ["-m", "arka.agent.remind", "--help"]),
    ("free_tier_help", ["free", "tier", "setup", "--help"], 30, None),
    ("ascii_arka", ["ascii", "ARKA"], 30, None),
]


def find_arka() -> Path:
    for candidate in ARKA_CANDIDATES:
        if candidate and candidate.is_file():
            return candidate
    found = subprocess.run(["which", "arka"], capture_output=True, text=True)
    if found.returncode == 0 and found.stdout.strip():
        return Path(found.stdout.strip())
    raise SystemExit("arka binary not found")


def sanitize(text: str) -> str:
    text = text.replace(str(HOME), "~")
    text = text.replace(str(REPO), "~/dev/arka")
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)(\S+)",
        r"\1***",
        text,
    )
    text = re.sub(r"sk-[a-zA-Z0-9]{8,}", "sk-***", text)
    text = re.sub(r"AIza[a-zA-Z0-9_-]{8,}", "AIza***", text)
    # Password vault: keep entry names, never show generated secrets
    text = re.sub(r"(len=)\d+", r"\1**", text)
    return text.rstrip() + "\n"


def run_cmd(argv: list[str], *, timeout: float, cwd: Path) -> tuple[str, bool, str]:
    python = REPO / "venv-arka" / "bin" / "python"
    if argv[0] == "-m":
        cmd = [str(python), *argv]
        label = "python " + " ".join(argv)
    else:
        cmd = argv
        label = " ".join(argv)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return sanitize(out), proc.returncode == 0, label
    except subprocess.TimeoutExpired:
        return sanitize("[timed out]\n"), False, label
    except OSError as exc:
        return sanitize(f"error: {exc}\n"), False, label


def run_capture(arka: Path, args: list[str], timeout: float) -> tuple[str, bool, str]:
    try:
        proc = subprocess.run(
            [str(arka), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return sanitize(out), proc.returncode == 0, "arka " + " ".join(args)
    except subprocess.TimeoutExpired:
        return sanitize("[timed out]\n"), False, "arka " + " ".join(args)
    except OSError as exc:
        return sanitize(f"error: {exc}\n"), False, "arka " + " ".join(args)


def save(name: str, text: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.txt"
    path.write_text(text)
    return path


def main() -> None:
    arka = find_arka()
    print(f"Using arka: {arka}")

    meta: dict[str, dict] = {}

    for name, args, timeout, fallback in CAPTURES:
        print(f"Capturing {name}…")
        text, ok, via = run_capture(arka, args, timeout)
        source = "cli"
        if (not ok or "[timed out]" in text or len(text.strip()) < 8) and fallback:
            print(f"  fallback for {name}")
            fb_text, fb_ok, fb_via = run_cmd(fallback, timeout=min(timeout, 45), cwd=REPO)
            if len(fb_text.strip()) >= len(text.strip()):
                text, ok, via = fb_text, fb_ok, "arka " + " ".join(args)
                source = "module_fallback"
        save(name, text)
        meta[name] = {
            "live": ok,
            "args": args,
            "source": source,
            "via": via,
            "chars": len(text),
        }

    META_FILE.write_text(json.dumps(meta, indent=2))
    print(f"Saved captures to {OUT_DIR}")
    print(f"Metadata: {META_FILE}")


if __name__ == "__main__":
    main()
