#!/usr/bin/env python3
"""Offline JSON helpers — validate, pretty/minify, and dotted-path get."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_INDEX_RE = re.compile(r"^(\w+|\[\d+\])(?:\.(.+)|(\[\d+\].*))?$")
_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"validate\s+json|json\s+validate|is\s+(?:this|it)\s+valid\s+json|"
    r"pretty\s*print\s+json|format\s+json|json\s+pretty|"
    r"minify\s+json|compress\s+json|"
    r"json\s+get|get\s+json|extract\s+json"
    r")\b"
)
_VALIDATE_RE = re.compile(r"(?i)\b(?:validate|valid|check)\b")
_PRETTY_RE = re.compile(r"(?i)\b(?:pretty|format|indent)\b")
_MINIFY_RE = re.compile(r"(?i)\b(?:minify|compress|compact)\b")
_GET_RE = re.compile(r"(?i)\b(?:get|extract|path)\b")
_FILE_RE = re.compile(r"([\w./~-]+\.json(?:c)?)")


def _json_input(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    path = Path(raw).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return raw


def wants_jsonkit(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_jsonkit(text):
        return ""
    clean = (text or "").strip()
    file_m = _FILE_RE.search(clean)
    path = file_m.group(1) if file_m else ""
    path_arg = f" {path}" if path else ""
    if _GET_RE.search(clean):
        path_m = re.search(r"(?i)\b(?:path|at)\s+([^\s]+)", clean)
        json_path = path_m.group(1) if path_m else "."
        if path:
            return f"jsonkit get {path} {json_path}"
        return f"jsonkit get {json_path}"
    if _MINIFY_RE.search(clean):
        return f"jsonkit minify{path_arg}".strip()
    if _PRETTY_RE.search(clean):
        return f"jsonkit pretty{path_arg}".strip()
    if _VALIDATE_RE.search(clean) or _TRIGGER_RE.search(clean):
        return f"jsonkit validate{path_arg}".strip()
    return f"jsonkit validate{path_arg}".strip()


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
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to jsonkit command")
    p_route.add_argument("text", nargs="+")

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
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if not args.cmd:
        parser.print_help()
        return 1
    json_text = _json_input(args.json_text)
    if args.cmd == "validate":
        payload = validate_payload(json_text)
    elif args.cmd == "pretty":
        payload = pretty_payload(json_text, indent=args.indent)
    elif args.cmd == "minify":
        payload = minify_payload(json_text)
    else:
        payload = get_payload(json_text, args.path)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
