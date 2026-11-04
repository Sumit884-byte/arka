#!/usr/bin/env python3
"""List live OS processes by CPU or memory — local only, never web search."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Any


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"(?:high|top|hottest|hog(?:ging)?|busy)\s+(?:cpu|processor)\s+process(?:es)?"
    r"|process(?:es)?\s+(?:using|with|by)\s+(?:high|the\s+most|most)\s+(?:cpu|processor)"
    r"|cpu\s+(?:hogs?|hogging|intensive)\s+process(?:es)?"
    r"|(?:show|list|get)\s+(?:me\s+)?(?:the\s+)?(?:high\s+)?cpu\s+process(?:es)?"
    r"|(?:show|list)\s+(?:me\s+)?(?:the\s+)?top\s+process(?:es)?"
    r"|what(?:'s| is)\s+(?:using|eating|hogging)\s+(?:my\s+)?(?:cpu|processor)"
    r"|which\s+process(?:es)?\s+(?:use|using|eat|eating)\s+(?:the\s+most\s+)?cpu"
    r")\b"
)
_STATS_RE = re.compile(
    r"(?i)\b("
    r"(?:show|list|get|print|display)\s+(?:me\s+)?(?:the\s+)?cpu\s+(?:stats?|statistics|usage|load|util(?:ization)?)"
    r"|cpu\s+(?:stats?|statistics|usage|load|util(?:ization)?)"
    r"|(?:show|check)\s+cpu\b"
    r")\b"
)
_MEM_RE = re.compile(
    r"(?i)\b(?:high|highest|top|most)\s+(?:ram|memory|mem)\s+process(?:es)?"
    r"|process(?:es)?\s+(?:using|with)\s+(?:the\s+most\s+)?(?:ram|memory)\b"
)


def wants_cpu_processes(text: str) -> bool:
    return bool(
        _TRIGGER_RE.search(text or "")
        or _MEM_RE.search(text or "")
        or _STATS_RE.search(text or "")
    )


def route_command(text: str) -> str:
    if not wants_cpu_processes(text):
        return ""
    if _STATS_RE.search(text or "") and not _TRIGGER_RE.search(text or ""):
        return "processes stats"
    if _MEM_RE.search(text or "") and not _TRIGGER_RE.search(text or ""):
        return "processes mem"
    return "processes cpu"


def _ps_rows(*, sort: str = "cpu", limit: int = 12) -> list[dict[str, Any]]:
    if sys.platform == "darwin":
        cmd = ["ps", "-Ao", "pid=,pcpu=,pmem=,user=,command=", "-r"]
    else:
        key = "-pcpu" if sort == "cpu" else "-pmem"
        cmd = ["ps", "-eo", "pid=,pcpu=,pmem=,user=,args=", f"--sort={key}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0])
            cpu = float(parts[1])
            mem = float(parts[2])
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        rows.append(
            {
                "pid": pid,
                "cpu": cpu,
                "mem": mem,
                "user": parts[3],
                "command": parts[4],
            }
        )
    key = "cpu" if sort == "cpu" else "mem"
    rows.sort(key=lambda row: float(row[key]), reverse=True)
    return rows[: max(1, limit)]


def format_process_table(rows: list[dict[str, Any]], *, sort: str = "cpu") -> str:
    label = "CPU" if sort == "cpu" else "memory"
    if not rows:
        return f"No live {label} process samples (ps failed or empty)."
    lines = [
        f"Highest {label} processes on this machine (live `ps`, not web search):",
        "",
        f"{'PID':>8}  {'CPU%':>6}  {'MEM%':>6}  {'USER':<12}  COMMAND",
    ]
    for row in rows:
        cmd = str(row["command"])
        if len(cmd) > 72:
            cmd = cmd[:69] + "..."
        lines.append(
            f"{row['pid']:>8}  {row['cpu']:>6.1f}  {row['mem']:>6.1f}  {str(row['user'])[:12]:<12}  {cmd}"
        )
    return "\n".join(lines)


def list_high_cpu(*, limit: int = 12) -> str:
    return format_process_table(_ps_rows(sort="cpu", limit=limit), sort="cpu")


def list_high_mem(*, limit: int = 12) -> str:
    return format_process_table(_ps_rows(sort="mem", limit=limit), sort="mem")


def _cpu_model() -> str:
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return (out.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[-1].strip()
    except OSError:
        pass
    return ""


def cpu_stats(*, limit: int = 8) -> str:
    """Live load + top processes. Never lscpu/htop advice and never web search."""
    cores = os.cpu_count() or 1
    try:
        load1, load5, load15 = os.getloadavg()
        load = f"{load1:.2f} {load5:.2f} {load15:.2f} (1/5/15 min)"
    except OSError:
        load = "unavailable"
    model = _cpu_model() or "unknown"
    lines = [
        "CPU stats (this machine, live — not web search, not lscpu/htop advice)",
        f"  Model:  {model}",
        f"  Cores:  {cores}",
        f"  Load:   {load}",
        "",
        list_high_cpu(limit=limit),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show live local processes by CPU or memory")
    parser.add_argument("sort", nargs="?", default="cpu", choices=("cpu", "mem", "memory", "ram", "stats"))
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)
    if args.sort == "stats":
        print(cpu_stats(limit=min(args.limit, 8)))
        return 0
    sort = "mem" if args.sort in {"mem", "memory", "ram"} else "cpu"
    text = list_high_mem(limit=args.limit) if sort == "mem" else list_high_cpu(limit=args.limit)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
