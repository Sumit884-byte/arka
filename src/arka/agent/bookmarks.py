#!/usr/bin/env python3
"""Save, search, and recall terminal bookmarks with tags and notes."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"


_BOOKMARKS_FILE = "bookmarks.json"
_MAX_BOOKMARKS = 500

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"bookmarks?|saved?\s+links?|saved?\s+urls?|"
    r"bookmark\s+manager|link\s+manager"
    r")\b"
)
_SAVE_RE = re.compile(
    r"(?i)\b(?:save|add|store|bookmark)\b.*\b(?:url|link|bookmark|page)\b"
)
_LIST_RE = re.compile(
    r"(?i)\b(?:list|show|my)\s+(?:bookmarks?|saved?\s+(?:links?|urls?))\b"
)
_SEARCH_RE = re.compile(
    r"(?i)\b(?:search|find)\s+(?:bookmarks?|saved?\s+(?:links?|urls?))\b"
)
_OPEN_RE = re.compile(r"(?i)\bopen\s+(?:bookmark|saved\s+link)\b")
_DELETE_RE = re.compile(r"(?i)\b(?:delete|remove)\s+bookmark\b")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def _store_path() -> Path:
    path = config_dir() / _BOOKMARKS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load() -> list[dict]:
    path = _store_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(rows: list[dict]) -> None:
    path = _store_path()
    path.write_text(json.dumps(rows[:_MAX_BOOKMARKS], indent=2), encoding="utf-8")


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def _extract_url(text: str) -> str | None:
    match = _URL_RE.search(text or "")
    return match.group(0).rstrip(".,);]") if match else None


def _title_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or parsed.path
        return host.removeprefix("www.") or url
    except Exception:
        return url


def wants_bookmarks(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _TRIGGER_RE.search(clean):
        return True
    if _SAVE_RE.search(clean) and _extract_url(clean):
        return True
    if _LIST_RE.search(clean) or _SEARCH_RE.search(clean):
        return True
    if _OPEN_RE.search(clean) or _DELETE_RE.search(clean):
        return True
    return False


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip().lower() for t in re.split(r"[,;]", raw) if t.strip()]


def cmd_save(args: argparse.Namespace) -> int:
    url = _normalize_url(args.url)
    if not url:
        print("Usage: bookmarks save <url> [--title T] [--tags a,b] [--note N]", file=sys.stderr)
        return 1
    rows = _load()
    title = (args.title or "").strip() or _title_from_url(url)
    tags = _parse_tags(args.tags)
    note = (args.note or "").strip()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "url": url,
        "title": title,
        "tags": tags,
        "note": note,
        "created": _now_iso(),
    }
    rows.insert(0, entry)
    _save(rows)
    print(f"Saved bookmark #{len(rows)}: {title}")
    print(url)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    rows = _load()
    tag = (args.tag or "").strip().lower()
    if tag:
        rows = [r for r in rows if tag in (r.get("tags") or [])]
    if not rows:
        print("No bookmarks saved yet. Try: bookmarks save https://example.com --tags docs")
        return 0
    lines = [f"Bookmarks ({len(rows)}):"]
    for idx, row in enumerate(rows, start=1):
        title = row.get("title") or row.get("url") or "untitled"
        url = row.get("url") or ""
        tags = row.get("tags") or []
        tag_txt = f" [{', '.join(tags)}]" if tags else ""
        note = (row.get("note") or "").strip()
        lines.append(f"{idx}. {title}{tag_txt}")
        lines.append(f"   {url}")
        if note:
            lines.append(f"   note: {note[:120]}")
    print("\n".join(lines))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip().lower()
    if not query:
        print("Usage: bookmarks search <keywords>", file=sys.stderr)
        return 1
    rows = _load()
    hits: list[dict] = []
    for row in rows:
        hay = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("url") or ""),
                str(row.get("note") or ""),
                " ".join(row.get("tags") or []),
            ]
        ).lower()
        if all(part in hay for part in query.split()):
            hits.append(row)
    if not hits:
        print(f"No bookmarks matching: {query}")
        return 1
    lines = [f"Matches ({len(hits)}):"]
    for idx, row in enumerate(hits, start=1):
        lines.append(f"{idx}. {row.get('title') or row.get('url')}")
        lines.append(f"   {row.get('url')}")
    print("\n".join(lines))
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    rows = _load()
    try:
        idx = int(args.index)
    except ValueError:
        print("Index must be a number", file=sys.stderr)
        return 1
    if idx < 1 or idx > len(rows):
        print(f"Invalid index {idx} (have {len(rows)} bookmarks)", file=sys.stderr)
        return 1
    row = rows[idx - 1]
    print(row.get("url") or "")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    rows = _load()
    try:
        idx = int(args.index)
    except ValueError:
        print("Index must be a number", file=sys.stderr)
        return 1
    if idx < 1 or idx > len(rows):
        print(f"Invalid index {idx}", file=sys.stderr)
        return 1
    url = rows[idx - 1].get("url") or ""
    if not url:
        print("Bookmark has no URL", file=sys.stderr)
        return 1
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    code = subprocess.call([opener, url])
    return code


def cmd_delete(args: argparse.Namespace) -> int:
    rows = _load()
    try:
        idx = int(args.index)
    except ValueError:
        print("Index must be a number", file=sys.stderr)
        return 1
    if idx < 1 or idx > len(rows):
        print(f"Invalid index {idx}", file=sys.stderr)
        return 1
    removed = rows.pop(idx - 1)
    _save(rows)
    print(f"Deleted: {removed.get('title') or removed.get('url')}")
    return 0


def route_command(text: str) -> str:
    if not wants_bookmarks(text):
        return ""
    clean = (text or "").strip()
    if _LIST_RE.search(clean):
        tag_m = re.search(r"(?i)\b(?:tag|tags)\s+([a-z0-9_-]+)", clean)
        if tag_m:
            return f"bookmarks list --tag {shlex.quote(tag_m.group(1))}"
        return "bookmarks list"
    if _SEARCH_RE.search(clean):
        q = re.sub(r"(?i)\b(?:search|find)\s+(?:bookmarks?|saved?\s+(?:links?|urls?))\s*(?:for)?\s*", "", clean)
        q = q.strip() or clean
        return "bookmarks search " + " ".join(shlex.quote(p) for p in q.split())
    if _DELETE_RE.search(clean):
        m = re.search(r"\b(\d+)\b", clean)
        if m:
            return f"bookmarks delete {m.group(1)}"
    if _OPEN_RE.search(clean):
        m = re.search(r"\b(\d+)\b", clean)
        if m:
            return f"bookmarks open {m.group(1)}"
    url = _extract_url(clean)
    if url and (_SAVE_RE.search(clean) or _TRIGGER_RE.search(clean)):
        parts = ["bookmarks", "save", shlex.quote(_normalize_url(url))]
        tag_m = re.search(r"(?i)\b(?:tag|tags)\s+([a-z0-9_,-]+)", clean)
        if tag_m:
            parts.extend(["--tags", shlex.quote(tag_m.group(1))])
        title_m = re.search(r'(?i)\b(?:as|title)\s+"([^"]+)"', clean)
        if title_m:
            parts.extend(["--title", shlex.quote(title_m.group(1))])
        return " ".join(parts)
    if _TRIGGER_RE.search(clean):
        return "bookmarks list"
    return ""


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Terminal bookmark manager")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to bookmarks command")
    p_route.add_argument("text", nargs="+")

    p_save = sub.add_parser("save", help="Save a URL bookmark")
    p_save.add_argument("url")
    p_save.add_argument("--title")
    p_save.add_argument("--tags")
    p_save.add_argument("--note")
    p_save.set_defaults(func=cmd_save)

    p_list = sub.add_parser("list", help="List saved bookmarks")
    p_list.add_argument("--tag")
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="Search bookmarks")
    p_search.add_argument("query", nargs="+")
    p_search.set_defaults(func=cmd_search)

    p_get = sub.add_parser("get", help="Print bookmark URL by index")
    p_get.add_argument("index")
    p_get.set_defaults(func=cmd_get)

    p_open = sub.add_parser("open", help="Open bookmark in browser")
    p_open.add_argument("index")
    p_open.set_defaults(func=cmd_open)

    p_del = sub.add_parser("delete", help="Delete bookmark by index")
    p_del.add_argument("index")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
