"""Read local workspace files for MCP agents — full contents with size and line limits."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_MAX_BYTES = 524_288  # 512 KiB
DEFAULT_MAX_LINES = 2000

_FILE_PATH_RE = re.compile(
    r"(?i)(?:['\"]([^'\"]+)['\"]"
    r"|((?:[\w.-]+/)+[\w.-]+(?:\.\w+)?)"
    r"|([~./][^\s'\"]+)"
    r"|([\w./~-]+\.\w+)\b)"
)

_AFTER_FILE_RE = re.compile(
    r"(?i)\b(?:file|source|contents?\s+of)\s+(['\"]?)([\w./~-]+(?:\.\w+)?)\1"
)

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"read_file|readfile|cat_file|show_file|view_file|open_file|"
    r"(?:read|show|view|open|cat|display|print|dump)\s+(?:the\s+)?(?:file|source|contents?)\b|"
    r"(?:read|show|view|open|cat|display|print|dump)\s+[\w./~-]+\.\w+\b|"
    r"(?:what(?:'s|\s+is)\s+in|contents?\s+of)\s+[\w./~-]+"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"(?:entire|whole|full)\s+(?:repo|repository|codebase|project)|"
    r"(?:read|explore|scan)\s+(?:the\s+)?(?:repo|repository|codebase|project)|"
    r"llm\.txt|"
    r"(?:markdown|md)\s+file|"
    r"\.(?:md|mdx|markdown|csv|tsv)\b"
    r")\b"
)


def _project_root(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    try:
        from arka.core.code_project import get_active_root

        active = get_active_root()
        if active is not None:
            return active.resolve()
    except ImportError:
        pass
    try:
        from arka.agent.pr_check import git_root

        root = git_root()
        if root is not None:
            return root.resolve()
    except ImportError:
        pass
    return Path.cwd().resolve()


def resolve_file(path: str | Path, *, root: Path | None = None) -> Path:
    raw = Path(str(path).strip().strip("'\"")).expanduser()
    base = root or _project_root()
    if not raw.is_absolute():
        raw = (base / raw).resolve()
    else:
        raw = raw.resolve()
    if not raw.is_file():
        raise FileNotFoundError(f"File not found: {raw}")
    return raw


def extract_file_path(text: str) -> str | None:
    after = _AFTER_FILE_RE.search(text or "")
    if after:
        return after.group(2).strip().strip("'\"")
    match = _FILE_PATH_RE.search(text or "")
    if not match:
        return None
    for group in match.groups():
        if group:
            return group.strip().strip("'\"")
    return None


def wants_read_file(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _EXCLUDE_RE.search(clean):
        return False
    if not extract_file_path(clean) and not _TRIGGER_RE.search(clean):
        return False
    return bool(_TRIGGER_RE.search(clean))


def read_file_payload(
    path: str,
    *,
    root: Path | str | None = None,
    offset: int = 1,
    limit: int | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Read a local file with edit-guard checks and size limits."""
    project = _project_root(str(root) if root else None)
    try:
        resolved = resolve_file(path, root=project)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "path": str(path)}

    try:
        from arka.core.edit_guard import check_edit_path

        guard = check_edit_path(resolved, root=project)
        if not guard.allowed:
            return {
                "ok": False,
                "blocked": True,
                "error": guard.reason or f"read blocked: {guard.path}",
                "path": str(resolved),
            }
    except ImportError:
        pass

    size_bytes = resolved.stat().st_size
    if size_bytes > max(1, max_bytes):
        return {
            "ok": False,
            "error": (
                f"File too large ({size_bytes} bytes); max is {max_bytes} bytes. "
                "Use offset/limit for a slice or arka_code_search for snippets."
            ),
            "path": str(resolved),
            "size_bytes": size_bytes,
            "max_bytes": max_bytes,
        }

    try:
        raw_text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": f"Could not read file: {exc}", "path": str(resolved)}

    lines = raw_text.splitlines()
    total_lines = len(lines)
    start = max(1, int(offset))
    end = total_lines if limit is None else min(total_lines, start - 1 + max(1, int(limit)))
    if limit is not None and int(limit) > DEFAULT_MAX_LINES:
        end = min(end, start - 1 + DEFAULT_MAX_LINES)
    slice_lines = lines[start - 1 : end] if start <= total_lines else []
    content = "\n".join(slice_lines)
    if end < total_lines and slice_lines:
        content += "\n"

    truncated = end < total_lines
    try:
        rel = str(resolved.relative_to(project))
    except ValueError:
        rel = resolved.as_posix()

    payload: dict[str, Any] = {
        "ok": True,
        "path": str(resolved),
        "relative_path": rel,
        "root": str(project),
        "content": content,
        "offset": start,
        "limit": len(slice_lines),
        "total_lines": total_lines,
        "size_bytes": size_bytes,
        "truncated": truncated,
    }
    if truncated:
        payload["notice"] = f"Showing lines {start}-{end} of {total_lines}. Pass offset/limit for more."
    return payload


def read_file_text(
    path: str,
    *,
    root: Path | str | None = None,
    offset: int = 1,
    limit: int | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    payload = read_file_payload(
        path,
        root=root,
        offset=offset,
        limit=limit,
        max_bytes=max_bytes,
    )
    if not payload.get("ok"):
        return payload.get("error") or "read failed"
    return str(payload.get("content") or "")


def route_command(text: str) -> str:
    clean = " ".join((text or "").split())
    if not wants_read_file(clean):
        return ""
    path = extract_file_path(clean)
    if not path:
        return ""
    quoted = shlex.quote(path)
    offset_match = re.search(r"(?i)\b(?:from|offset|line)\s+(\d+)\b", clean)
    limit_match = re.search(r"(?i)\b(?:limit|lines?|count)\s+(\d+)\b", clean)
    parts = ["read_file", "read", quoted]
    if offset_match:
        parts.extend(["--offset", offset_match.group(1)])
    if limit_match:
        parts.extend(["--limit", limit_match.group(1)])
    return " ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read a local workspace file with size limits")
    sub = p.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to read_file command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=_cmd_route)

    p_read = sub.add_parser("read", help="Read a file")
    p_read.add_argument("path")
    p_read.add_argument("--root", default=None, help="Optional project root")
    p_read.add_argument("--offset", type=int, default=1, help="1-based start line")
    p_read.add_argument("--limit", type=int, default=None, help="Max lines to return")
    p_read.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Max file size in bytes")
    p_read.add_argument("--json", action="store_true", help="Return JSON payload")
    p_read.set_defaults(func=_cmd_read)

    return p


def _cmd_route(args: argparse.Namespace) -> int:
    route = route_command(" ".join(args.text))
    if route:
        print(route)
        return 0
    return 1


def _cmd_read(args: argparse.Namespace) -> int:
    payload = read_file_payload(
        args.path,
        root=args.root,
        offset=args.offset,
        limit=args.limit,
        max_bytes=args.max_bytes,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok") else 1
    if not payload.get("ok"):
        print(payload.get("error") or "read failed", file=sys.stderr)
        return 1
    print(payload.get("content") or "")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv if argv is not None else sys.argv[1:])
    if argv_list and argv_list[0] in ("route", "read"):
        args = build_parser().parse_args(argv_list)
        return int(args.func(args))
    if argv_list and wants_read_file(" ".join(argv_list)):
        path = extract_file_path(" ".join(argv_list))
        if path:
            return _cmd_read(
                argparse.Namespace(
                    path=path,
                    root=None,
                    offset=1,
                    limit=None,
                    max_bytes=DEFAULT_MAX_BYTES,
                    json=False,
                )
            )
    parser = build_parser()
    args = parser.parse_args(["read", *argv_list]) if argv_list else parser.parse_args(["read"])
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
