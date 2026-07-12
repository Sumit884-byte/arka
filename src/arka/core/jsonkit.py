#!/usr/bin/env python3
"""Offline JSON helpers — validate, pretty/minify, and dotted-path get."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any


_INDEX_RE = re.compile(r"^(\w+|\[\d+\])(?:\.(.+)|(\[\d+\].*))?$")


def _loads(text: str) -> Any:
    raw = text if text is not None else ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def validate_payload(text: str) -> dict[str, Any]:
    """Validate JSON text for MCP / automation clients."""
    try:
        data = _loads(text)
    except ValueError as exc:
        return {"ok": False, "valid": False, "error": str(exc), "type": None}
    return {
        "ok": True,
        "valid": True,
        "error": None,
        "type": type(data).__name__,
        "bytes": len((text or "").encode("utf-8")),
    }


def pretty_payload(text: str, *, indent: int = 2) -> dict[str, Any]:
    """Pretty-print JSON."""
    data = _loads(text)
    indent = max(0, min(int(indent), 8))
    rendered = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    return {"ok": True, "json": rendered, "indent": indent}


def minify_payload(text: str) -> dict[str, Any]:
    """Minify JSON."""
    data = _loads(text)
    rendered = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return {"ok": True, "json": rendered, "bytes": len(rendered.encode("utf-8"))}


def _get_path(data: Any, path: str) -> Any:
    if not path or not str(path).strip():
        return data
    cur = data
    token = path.strip()
    # Support a.b[0].c and a.0.c
    parts: list[str] = []
    buf = ""
    i = 0
    while i < len(token):
        ch = token[i]
        if ch == ".":
            if buf:
                parts.append(buf)
                buf = ""
            i += 1
            continue
        if ch == "[":
            if buf:
                parts.append(buf)
                buf = ""
            j = token.find("]", i)
            if j < 0:
                raise ValueError(f"invalid path: {path!r}")
            parts.append(token[i + 1 : j])
            i = j + 1
            continue
        buf += ch
        i += 1
    if buf:
        parts.append(buf)

    for part in parts:
        if isinstance(cur, list):
            try:
                idx = int(part)
            except ValueError as exc:
                raise ValueError(f"list index required at {part!r}") from exc
            cur = cur[idx]
        elif isinstance(cur, dict):
            if part not in cur:
                raise ValueError(f"key not found: {part}")
            cur = cur[part]
        else:
            raise ValueError(f"cannot traverse into {type(cur).__name__}")
    return cur


def get_payload(text: str, path: str) -> dict[str, Any]:
    """Get a value from JSON by dotted/bracket path."""
    data = _loads(text)
    value = _get_path(data, path)
    return {
        "ok": True,
        "path": path,
        "type": type(value).__name__,
        "value": value,
        "json": json.dumps(value, ensure_ascii=False),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arka JSON utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, help_text in (
        ("validate", "Validate JSON"),
        ("pretty", "Pretty-print JSON"),
        ("minify", "Minify JSON"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("json_text")
        if name == "pretty":
            p.add_argument("--indent", type=int, default=2)

    p_get = sub.add_parser("get", help="Get value by path")
    p_get.add_argument("json_text")
    p_get.add_argument("path")

    args = parser.parse_args(argv)
    if args.cmd == "validate":
        payload = validate_payload(args.json_text)
    elif args.cmd == "pretty":
        payload = pretty_payload(args.json_text, indent=args.indent)
    elif args.cmd == "minify":
        payload = minify_payload(args.json_text)
    else:
        payload = get_payload(args.json_text, args.path)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
