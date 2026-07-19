"""Lightweight JSONL logs for Arka MCP client/server debugging."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

MAX_LOG_BYTES = 2_000_000


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
            if any(secret in key_s.lower() for secret in ("key", "token", "secret", "authorization")):
                out[key_s] = "[redacted]"
            else:
                out[key_s] = _sanitize(raw, limit=limit)
        return out
    if isinstance(value, list):
        return [_sanitize(item, limit=limit) for item in value[:20]]
    return str(value)[:limit]


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
                if any(secret in key.lower() for secret in ("key", "token", "secret", "authorization"))
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
