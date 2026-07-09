"""Shared NL detection for find-files-by-size queries."""

from __future__ import annotations

import re

FILE_SIZE_SUBJECT_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:find|search|list|show)\s+.*\bfiles?\b|"
    r"\b(?:find|search|list|show)\s+.*\bdownloads?\b|"
    r"\bfiles?\b.*\b(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b|"
    r"\bdownloads?\b.*\b(?:range\s+of|between|from|\d+\s*(?:kb|mb|gb))\b|"
    r"\bfiles?\s+in\s+(?:my\s+)?(?:the\s+)?(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b|"
    r"\blarge\s+files?\s+in\s+(?:my\s+)?(?:the\s+)?(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b|"
    r"\b(?:big|large|huge)\s+files?\b.*\b(?:downloads?|desktop|documents?|pictures?|photos?|videos?|music)\b"
    r")"
)

FILE_SIZE_THRESHOLD_RE = re.compile(
    r"(?i)(?:"
    r"(?:less|more|greater|larger|smaller|lesser|under|over|above|below|bigger)(?:\s+than)?|"
    r"\b(?:range\s+of|between|from)\b|"
    r"\d+\s*(?:kb|mb|gb)\b\s+(?:to|and|-)\s+\d+\s*(?:kb|mb|gb)\b|"
    r"\d+\s*(?:kb|mb|gb)\b"
    r")"
)


def is_file_size_query(cmd: str) -> bool:
    if not FILE_SIZE_SUBJECT_RE.search(cmd):
        return False
    if FILE_SIZE_THRESHOLD_RE.search(cmd):
        return True
    return bool(re.search(r"(?i)\b(?:large|big|huge)\s+files?\b", cmd))


def route_find_files_by_size(cmd: str) -> str | None:
    if not is_file_size_query(cmd):
        return None
    return f"find_files_by_size {cmd}"
