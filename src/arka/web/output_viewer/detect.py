"""Detect the best representation for arbitrary user data."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from arka.core.markdown_style import looks_like_markdown

_MEDIA_EXT = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".mp4",
        ".webm",
        ".mov",
        ".mp3",
        ".wav",
        ".pdf",
    }
)

_EXT_MAP = {
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".csv": "csv",
    ".tsv": "csv",
    ".md": "markdown",
    ".mdx": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".log": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def detect_format(content: str, *, filename: str | None = None) -> str:
    """Return a format id: json, json_array, json_object, jsonl, csv, markdown, yaml, media, text."""
    if filename:
        ext = Path(filename).suffix.lower()
        mapped = _EXT_MAP.get(ext)
        if mapped and mapped != "text":
            if mapped == "json":
                return _refine_json_format(content)
            return mapped

    stripped = (content or "").strip()
    if not stripped:
        return "text"

    if filename and Path(filename).suffix.lower() in _MEDIA_EXT:
        return "media"

    if stripped[0] in "{[":
        refined = _refine_json_format(stripped)
        if refined != "text":
            return refined

    if _looks_like_jsonl(stripped):
        return "jsonl"

    if _looks_like_csv(stripped):
        return "csv"

    if stripped.startswith("---") or re.search(r"(?m)^[\w.-]+\s*:\s*\S", stripped):
        if re.search(r"(?m)^[\w.-]+\s*:\s*\S", stripped) and not _looks_like_csv(stripped):
            return "yaml"

    if looks_like_markdown(stripped):
        return "markdown"

    if _looks_like_media_metadata(stripped):
        return "media"

    return "text"


def _refine_json_format(content: str) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return "text"
    if isinstance(parsed, list):
        if parsed and all(isinstance(row, dict) for row in parsed[:50]):
            return "json_array"
        return "json"
    if isinstance(parsed, dict):
        if _dict_has_media_paths(parsed):
            return "media"
        return "json_object"
    return "json"


def _looks_like_jsonl(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    sample = lines[: min(len(lines), 20)]
    for line in sample:
        if line[0] not in "{[":
            return False
        try:
            json.loads(line)
        except json.JSONDecodeError:
            return False
    return True


def _looks_like_csv(content: str) -> bool:
    sample = content[:8192]
    if "\n" not in sample:
        return False
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        return False
    reader = csv.reader(io.StringIO(sample), dialect)
    rows = list(reader)
    if len(rows) < 2:
        return False
    header_len = len(rows[0])
    if header_len < 2:
        return False
    body = rows[1:]
    if not body:
        return False
    consistent = sum(1 for row in body[:20] if len(row) == header_len)
    return consistent >= max(1, min(len(body), 20) // 2)


def _looks_like_media_metadata(content: str) -> bool:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return bool(re.search(r"(?i)\.(png|jpe?g|gif|webp|mp4|webm|pdf)(?:[\"'\s,]|$)", content))
    return _dict_has_media_paths(parsed)


def _dict_has_media_paths(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in {"path", "file", "image", "video", "audio", "media", "src", "url"}:
                if isinstance(item, str) and _is_media_path(item):
                    return True
            if _dict_has_media_paths(item):
                return True
        return False
    if isinstance(value, list):
        return any(_dict_has_media_paths(item) for item in value[:50])
    if isinstance(value, str):
        return _is_media_path(value)
    return False


def _is_media_path(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered or "://" in lowered:
        return lowered.endswith(tuple(_MEDIA_EXT)) or any(ext in lowered for ext in (".png", ".jpg", ".mp4"))
    return Path(lowered).suffix.lower() in _MEDIA_EXT
