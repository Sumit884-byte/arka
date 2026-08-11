"""Lightweight JSONL logs for Arka MCP client/server debugging."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

MAX_LOG_BYTES = 2_000_000
_PROMPT_KEYS = ("prompt", "text", "goal", "query", "question", "message", "task")
_SECRET_KEY_MARKERS = ("key", "token", "secret", "password", "authorization")


def mcp_log_path() -> Path:
    import os

    if override := os.environ.get("ARKA_MCP_LOG_PATH", "").strip():
        return Path(override).expanduser()
    from arka.paths import config_dir

    return config_dir() / "logs" / "mcp.jsonl"


def _sanitize(value: Any, *, limit: int = 500) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = value.replace("\n", "\\n")
        for marker in ("KEY=", "TOKEN=", "SECRET=", "Authorization:"):
            if marker.lower() in text.lower():
                return "[redacted]"
        return text[:limit]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, raw in value.items():
            key_s = str(key)
            if any(marker in key_s.lower() for marker in _SECRET_KEY_MARKERS):
                out[key_s] = "[redacted]"
            else:
                out[key_s] = _sanitize(raw, limit=limit)
        return out
    if isinstance(value, list):
        return [_sanitize(item, limit=limit) for item in value[:20]]
    return str(value)[:limit]


def extract_mcp_prompt(tool_name: str, arguments: dict[str, Any]) -> str:
    """Extract primary user text from MCP tool arguments."""
    if not isinstance(arguments, dict):
        return ""
    for key in _PROMPT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if tool_name == "arka_skill":
        skill = str(arguments.get("skill") or arguments.get("name") or "").strip()
        args = arguments.get("args")
        if isinstance(args, str) and args.strip():
            return f"{skill} {args}".strip() if skill else args.strip()
        if isinstance(args, list) and args:
            parts = [skill] if skill else []
            parts.extend(str(item) for item in args[:5])
            return " ".join(parts).strip()
    return ""


def summarize_mcp_tool_args(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Sanitized non-prompt tool arguments for logging."""
    if not isinstance(arguments, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        key_s = str(key)
        if key_s in _PROMPT_KEYS:
            continue
        if any(marker in key_s.lower() for marker in _SECRET_KEY_MARKERS):
            out[key_s] = "[redacted]"
        else:
            out[key_s] = _sanitize(value, limit=200)
    return out


def mcp_tool_call_fields(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build JSONL/OTel fields for an MCP tools/call request."""
    fields: dict[str, Any] = {}
    prompt = extract_mcp_prompt(tool_name, arguments)
    if prompt:
        fields["prompt"] = prompt
    args_summary = summarize_mcp_tool_args(tool_name, arguments)
    if args_summary:
        fields["args_summary"] = args_summary
    return fields


def log_mcp_event(event: str, **fields: Any) -> None:
    path = mcp_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_suffix(".jsonl.1"))
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            **{
                key: "[redacted]"
                if any(marker in key.lower() for marker in _SECRET_KEY_MARKERS)
                else _sanitize(value)
                for key, value in fields.items()
            },
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        # MCP logging must never break the MCP server/client path.
        return


def read_mcp_logs(*, limit: int = 50, event: str = "", json_output: bool = False) -> str:
    path = mcp_log_path()
    if not path.is_file():
        return f"No MCP logs yet. Path: {path}"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit * 3):]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event and row.get("event") != event:
            continue
        rows.append(row)
    rows = rows[-max(1, limit):]
    if json_output:
        return json.dumps({"path": str(path), "count": len(rows), "events": rows}, indent=2)
    out = [f"path\t{path}", f"count\t{len(rows)}"]
    for row in rows:
        parts = [
            str(row.get(key))
            for key in ("server", "tool", "method", "status", "error")
            if row.get(key)
        ]
        detail = " ".join(parts)
        out.append(f"{row.get('ts')}\t{row.get('event')}\t{detail}")
    return "\n".join(out)


def mcp_tool_stats(*, top: int = 20, event: str = "server.tools_call", json_output: bool = False) -> str:
    """Aggregate MCP tool call frequency from the JSONL log."""
    path = mcp_log_path()
    if not path.is_file():
        return f"No MCP logs yet. Path: {path}"

    event_filter = event.strip()
    tool_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    total_rows = 0
    first_ts = ""
    last_ts = ""

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event_filter and row.get("event") != event_filter:
            continue
        tool = str(row.get("tool") or "").strip()
        if not tool:
            continue
        total_rows += 1
        tool_counts[tool] += 1
        status_counts[str(row.get("status") or "unknown")] += 1
        ts = str(row.get("ts") or "")
        if ts:
            if not first_ts:
                first_ts = ts
            last_ts = ts

    if not tool_counts:
        hint = f" (event={event_filter})" if event_filter else ""
        return f"No MCP tool calls logged yet{hint}. Path: {path}"

    ranked = tool_counts.most_common(max(1, top))
    if json_output:
        return json.dumps(
            {
                "path": str(path),
                "event": event_filter or "all",
                "total_calls": total_rows,
                "first_ts": first_ts,
                "last_ts": last_ts,
                "status": dict(status_counts),
                "tools": [{"tool": tool, "count": count} for tool, count in ranked],
            },
            indent=2,
        )

    out = [
        f"path\t{path}",
        f"event\t{event_filter or 'all'}",
        f"total_calls\t{total_rows}",
        f"range\t{first_ts} .. {last_ts}" if first_ts else "range\t",
        "status\t" + ", ".join(f"{k}={v}" for k, v in status_counts.most_common()),
        "",
        "count\ttool",
    ]
    for tool, count in ranked:
        out.append(f"{count}\t{tool}")
    return "\n".join(out)
