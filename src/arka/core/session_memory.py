#!/usr/bin/env python3
"""OpenClaw-style persistent markdown memory — MEMORY.md + daily notes with sanitization."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

try:
    from arka.paths import cache_dir, config_dir, load_env_file

    load_env_file()
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass


def memory_root() -> Path:
    if raw := os.environ.get("SESSION_MEMORY_DIR", "").strip():
        return Path(raw).expanduser()
    return config_dir() / "agent-memory"


def long_term_path() -> Path:
    return memory_root() / "MEMORY.md"


def daily_dir() -> Path:
    return memory_root() / "daily"


def _max_longterm_lines() -> int:
    try:
        return max(20, int(os.environ.get("MEMORY_LONGTERM_MAX_LINES", "100")))
    except ValueError:
        return 100


def _enabled() -> bool:
    return os.environ.get("SESSION_MEMORY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _sanitize_text(text: str) -> tuple[str, str | None]:
    """Block or strip unsafe content before writing to memory files."""
    text = " ".join((text or "").split()).strip()
    if not text:
        return "", "empty"
    try:
        from arka.core.security import sanitize_llm_context, verify_user_prompt

        gate = verify_user_prompt(text)
        if gate.status == "block":
            return "", gate.reason
        cleaned, _ = sanitize_llm_context(text)
        return (cleaned or text).strip(), None
    except ImportError:
        return text, None


def _append_file(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- [{stamp}] {line}\n")


def _prune_longterm() -> None:
    path = long_term_path()
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    limit = _max_longterm_lines()
    if len(lines) <= limit:
        return
    header = [ln for ln in lines if ln.startswith("#")]
    body = [ln for ln in lines if ln and not ln.startswith("#")]
    kept_body = body[-limit:]
    path.write_text("\n".join(header + kept_body) + "\n", encoding="utf-8")


def append(text: str, *, long_term: bool = False) -> int:
    if not _enabled():
        print("Session memory disabled (SESSION_MEMORY=0).", file=sys.stderr)
        return 1
    cleaned, err = _sanitize_text(text)
    if err:
        print(f"Memory blocked: {err}", file=sys.stderr)
        return 1
    if not cleaned:
        print("Nothing to store.", file=sys.stderr)
        return 1

    daily = daily_dir() / f"{date.today().isoformat()}.md"
    _append_file(daily, cleaned)
    if long_term or os.environ.get("MEMORY_AUTO_LONGTERM", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        lt = long_term_path()
        if not lt.is_file():
            lt.write_text("# Long-term memory\n\n", encoding="utf-8")
        _append_file(lt, cleaned)
        _prune_longterm()

    try:
        from arka.integrations.heartbeat import ping

        ping("memory.append", source="session_memory")
    except Exception:
        pass
    print(f"Stored: {cleaned[:120]}")
    return 0


def search(query: str, *, limit: int = 8) -> list[tuple[str, str]]:
    q = query.lower().strip()
    hits: list[tuple[float, str, str]] = []
    root = memory_root()
    if not root.is_dir():
        return []
    files = sorted(root.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:40]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            body = re.sub(r"^-\s*\[[^\]]+\]\s*", "", stripped)
            if not body:
                continue
            score = 0.0
            if q:
                for word in q.split():
                    if len(word) > 1 and word in body.lower():
                        score += 2.0
            else:
                score = 1.0
            if score > 0:
                rel = str(path.relative_to(root))
                hits.append((score, rel, body))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [(rel, body) for _, rel, body in hits[:limit]]


def context_for(goal: str, *, limit_chars: int = 2500) -> str:
    if not _enabled():
        return ""
    parts: list[str] = []
    lt = long_term_path()
    if lt.is_file():
        text = lt.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            parts.append("Long-term memory (MEMORY.md):\n" + text[-1200:])
    hits = search(goal, limit=5)
    if hits:
        lines = [f"- {body}" for _, body in hits]
        parts.append("Relevant session notes:\n" + "\n".join(lines))
    out = "\n\n".join(parts).strip()
    if len(out) > limit_chars:
        out = out[-limit_chars:]
    return out


def status() -> dict[str, object]:
    root = memory_root()
    lt = long_term_path()
    daily = list(daily_dir().glob("*.md")) if daily_dir().is_dir() else []
    return {
        "enabled": _enabled(),
        "root": str(root),
        "long_term_lines": len(lt.read_text(encoding="utf-8").splitlines()) if lt.is_file() else 0,
        "daily_files": len(daily),
        "max_longterm_lines": _max_longterm_lines(),
    }


def clear(*, scope: str = "daily") -> dict[str, object]:
    """Clear OpenClaw-style markdown memory.

    scope:
      - daily: remove daily/*.md only
      - long_term: reset MEMORY.md
      - all: both
    """
    target = (scope or "daily").strip().lower().replace("-", "_")
    if target in {"longterm", "memory", "lt"}:
        target = "long_term"
    if target not in {"daily", "long_term", "all"}:
        raise ValueError("scope must be daily, long_term, or all")

    removed_daily = 0
    cleared_long_term = False

    if target in {"daily", "all"}:
        ddir = daily_dir()
        if ddir.is_dir():
            for path in ddir.glob("*.md"):
                try:
                    path.unlink()
                    removed_daily += 1
                except OSError:
                    continue

    if target in {"long_term", "all"}:
        lt = long_term_path()
        if lt.is_file():
            lt.write_text("# Long-term memory\n\n", encoding="utf-8")
            cleared_long_term = True
        elif target == "long_term":
            lt.parent.mkdir(parents=True, exist_ok=True)
            lt.write_text("# Long-term memory\n\n", encoding="utf-8")
            cleared_long_term = True

    try:
        from arka.integrations.heartbeat import ping

        ping(f"memory.clear.{target}", source="session_memory")
    except Exception:
        pass

    return {
        "scope": target,
        "removed_daily": removed_daily,
        "cleared_long_term": cleared_long_term,
        **status(),
    }


def print_status() -> None:
    info = status()
    print(f"Session memory: {'on' if info['enabled'] else 'off'}")
    print(f"  Root: {info['root']}")
    print(f"  MEMORY.md lines: {info['long_term_lines']} (max {info['max_longterm_lines']})")
    print(f"  Daily note files: {info['daily_files']}")


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="OpenClaw-style markdown session memory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("append", help="Append sanitized note to daily + optional MEMORY.md")
    p.add_argument("text")
    p.add_argument("--long-term", action="store_true")

    p = sub.add_parser("search")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--limit", type=int, default=8)

    p = sub.add_parser("context")
    p.add_argument("goal")

    sub.add_parser("status")

    p = sub.add_parser("clear", help="Clear daily notes, MEMORY.md, or both")
    p.add_argument(
        "--scope",
        choices=["daily", "long_term", "all"],
        default="daily",
        help="What to clear (default: daily)",
    )
    p.add_argument("--long-term", action="store_true", help="Alias for --scope long_term")
    p.add_argument("--all", action="store_true", help="Alias for --scope all")

    args = parser.parse_args()
    if args.cmd == "append":
        return append(args.text, long_term=args.long_term)
    if args.cmd == "search":
        rows = search(args.query, limit=args.limit)
        if not rows:
            print("No matching session notes.")
            return 0
        for rel, body in rows:
            print(f"[{rel}] {body}")
        return 0
    if args.cmd == "context":
        ctx = context_for(args.goal)
        print(ctx or "(no session memory context)")
        return 0
    if args.cmd == "status":
        print_status()
        return 0
    if args.cmd == "clear":
        scope = args.scope
        if args.all:
            scope = "all"
        elif args.long_term:
            scope = "long_term"
        info = clear(scope=scope)
        print(
            f"Cleared session memory ({info['scope']}): "
            f"daily={info['removed_daily']} long_term={info['cleared_long_term']}"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
