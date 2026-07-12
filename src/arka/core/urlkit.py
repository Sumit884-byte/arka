#!/usr/bin/env python3
"""Offline URL helpers — parse, normalize, and slugify."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def parse_payload(url: str) -> dict[str, Any]:
    """Parse a URL into structured parts for MCP / automation clients."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("url is required")
    # Allow bare domains
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    query = parse_qs(parsed.query, keep_blank_values=True)
    flat_query = {
        key: values[0] if len(values) == 1 else values
        for key, values in query.items()
    }
    return {
        "ok": True,
        "input": raw,
        "scheme": parsed.scheme,
        "netloc": parsed.netloc,
        "host": parsed.hostname or "",
        "port": parsed.port,
        "path": parsed.path or "/",
        "params": parsed.params,
        "query": flat_query,
        "fragment": parsed.fragment,
        "username": parsed.username or "",
        "password": bool(parsed.password),
    }


def normalize_payload(url: str, *, drop_fragment: bool = True) -> dict[str, Any]:
    """Normalize scheme/host casing and optionally strip fragment."""
    parts = parse_payload(url)
    scheme = (parts["scheme"] or "https").lower()
    host = (parts["host"] or "").lower()
    port = parts["port"]
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts["path"] or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_items = parts["query"]
    # Stable query encoding
    pairs: list[tuple[str, str]] = []
    if isinstance(query_items, dict):
        for key in sorted(query_items):
            val = query_items[key]
            if isinstance(val, list):
                for item in val:
                    pairs.append((key, str(item)))
            else:
                pairs.append((key, str(val)))
    query = urlencode(pairs)
    fragment = "" if drop_fragment else str(parts.get("fragment") or "")
    normalized = urlunparse((scheme, netloc, path, "", query, fragment))
    return {
        "ok": True,
        "input": parts["input"],
        "url": normalized,
        "dropped_fragment": bool(drop_fragment and parts.get("fragment")),
    }


def slugify_payload(text: str, *, max_length: int = 80) -> dict[str, Any]:
    """Slugify text for paths or filenames."""
    raw = (text or "").strip().lower()
    if not raw:
        raise ValueError("text is required")
    slug = _SLUG_RE.sub("-", raw).strip("-")
    max_length = max(1, min(int(max_length), 200))
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return {"ok": True, "input": text, "slug": slug, "length": len(slug)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arka URL utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_parse = sub.add_parser("parse", help="Parse a URL")
    p_parse.add_argument("url")

    p_norm = sub.add_parser("normalize", help="Normalize a URL")
    p_norm.add_argument("url")
    p_norm.add_argument("--keep-fragment", action="store_true")

    p_slug = sub.add_parser("slugify", help="Slugify text")
    p_slug.add_argument("text", nargs="+")
    p_slug.add_argument("--max-length", type=int, default=80)

    args = parser.parse_args(argv)
    if args.cmd == "parse":
        payload = parse_payload(args.url)
    elif args.cmd == "normalize":
        payload = normalize_payload(args.url, drop_fragment=not args.keep_fragment)
    else:
        payload = slugify_payload(" ".join(args.text), max_length=args.max_length)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
