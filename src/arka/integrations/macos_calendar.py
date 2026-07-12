"""Read today's events from macOS Calendar.app (EventKit via AppleScript)."""

from __future__ import annotations

import platform
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

_APPLESCRIPT = r'''
set todayStart to current date
set hours of todayStart to 0
set minutes of todayStart to 0
set seconds of todayStart to 0
set todayEnd to todayStart + (1 * days)

set outLines to {}
tell application "Calendar"
    repeat with cal in calendars
        try
            set calName to name of cal
            set evts to (every event of cal whose start date ≥ todayStart and start date < todayEnd)
            repeat with e in evts
                set sUnix to (start date of e) as integer
                set eUnix to (end date of e) as integer
                set startIso to do shell script "date -r " & sUnix & " +%Y-%m-%dT%H:%M:%S%z"
                set endIso to do shell script "date -r " & eUnix & " +%Y-%m-%dT%H:%M:%S%z"
                set end of outLines to (calName & "|||" & (summary of e) & "|||" & startIso & "|||" & endIso)
            end repeat
        end try
    end repeat
end tell
set AppleScript's text item delimiters to linefeed
return outLines as string
'''


def _available() -> bool:
    return platform.system() == "Darwin"


def _normalize_tz(raw: str) -> str:
    """Convert +0530 suffix to +05:30 for fromisoformat."""
    if len(raw) >= 5 and raw[-5] in "+-" and raw[-3:].isdigit() and raw[-5:-3].isdigit():
        if ":" not in raw[-6:]:
            return raw[:-2] + ":" + raw[-2:]
    return raw


def _parse_apple_iso(raw: str) -> datetime | None:
    raw = _normalize_tz((raw or "").strip())
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def _format_when(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return ""
    local = start.astimezone()
    label = local.strftime("%a %b %d, %Y · %I:%M %p")
    if end is not None:
        end_local = end.astimezone()
        if end_local.date() == local.date():
            label += " – " + end_local.strftime("%I:%M %p")
    return label



def today_payload() -> dict[str, object]:
    """Structured today's calendar events for MCP / automation clients."""
    events, error = fetch_today_events()
    rows: list[dict[str, object]] = []
    for event in events:
        start = event.get("start")
        end = event.get("end")
        rows.append(
            {
                "summary": event.get("summary") or "",
                "calendar": event.get("calendar") or "",
                "when": event.get("when") or "",
                "start": start.isoformat() if hasattr(start, "isoformat") and start else None,
                "end": end.isoformat() if hasattr(end, "isoformat") and end else None,
                "source": event.get("source") or "macos",
            }
        )
    return {
        "ok": error is None,
        "available": _available(),
        "error": error,
        "count": len(rows),
        "events": rows,
    }


def fetch_today_events() -> tuple[list[dict[str, Any]], str | None]:
    """Return (events, error). Each event has summary, start, end, calendar, when, source."""
    if not _available():
        return [], "macOS only"

    try:
        proc = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)

    combined = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0:
        if "-1743" in combined or "Not authorised" in combined:
            return [], (
                "Calendar.app access denied — allow your terminal in "
                "System Settings → Privacy & Security → Automation → Calendar"
            )
        return [], combined.strip() or f"osascript exit {proc.returncode}"

    raw = (proc.stdout or "").strip()
    if not raw:
        return [], None

    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|||")
        if len(parts) != 4:
            continue
        cal_name, summary, start_raw, end_raw = parts
        start = _parse_apple_iso(start_raw)
        end = _parse_apple_iso(end_raw)
        events.append(
            {
                "summary": summary.strip(),
                "start": start,
                "end": end,
                "calendar": cal_name.strip(),
                "when": _format_when(start, end),
                "source": "macos",
            }
        )

    events.sort(
        key=lambda row: row["start"] or datetime.max.replace(tzinfo=timezone.utc)
    )
    return events, None
