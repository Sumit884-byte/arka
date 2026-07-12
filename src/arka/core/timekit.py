#!/usr/bin/env python3
"""Offline time helpers — now, timezone convert, and simple relative offsets."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_REL_RE = re.compile(
    r"(?i)^\s*(?:in\s+)?([+-]?\d+)\s*"
    r"(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)\s*$"
)


def _parse_dt(value: str, *, tz: str | None = None) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("datetime is required")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {value!r}") from exc
    if dt.tzinfo is None:
        zone = _zone(tz)
        dt = dt.replace(tzinfo=zone)
    return dt


def _zone(name: str | None) -> Any:
    if not name or not str(name).strip():
        return datetime.now().astimezone().tzinfo or timezone.utc
    try:
        return ZoneInfo(str(name).strip())
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {name}") from exc


def _zone_key(zone: Any) -> str:
    return getattr(zone, "key", str(zone))


def now_payload(*, tz: str | None = None) -> dict[str, Any]:
    """Current time in a timezone for MCP / automation clients."""
    zone = _zone(tz)
    now = datetime.now(tz=zone)
    return {
        "ok": True,
        "timezone": _zone_key(zone),
        "iso": now.isoformat(timespec="seconds"),
        "unix": int(now.timestamp()),
        "utc_iso": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
    }


def convert_payload(
    value: str,
    *,
    to_tz: str,
    from_tz: str | None = None,
) -> dict[str, Any]:
    """Convert a datetime between timezones."""
    dt = _parse_dt(value, tz=from_tz)
    target = _zone(to_tz)
    converted = dt.astimezone(target)
    return {
        "ok": True,
        "input": value,
        "from_timezone": _zone_key(dt.tzinfo),
        "to_timezone": _zone_key(target),
        "iso": converted.isoformat(timespec="seconds"),
        "unix": int(converted.timestamp()),
        "utc_iso": converted.astimezone(timezone.utc).isoformat(timespec="seconds"),
    }


def relative_payload(
    expression: str,
    *,
    tz: str | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """Apply a simple relative offset like '2h' or 'in 3 days'."""
    match = _REL_RE.match(expression or "")
    if not match:
        raise ValueError("expression must look like '2h', '-30m', or 'in 3 days'")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit in {"s", "sec", "secs", "second", "seconds"}:
        delta = timedelta(seconds=amount)
        unit_norm = "seconds"
    elif unit in {"m", "min", "mins", "minute", "minutes"}:
        delta = timedelta(minutes=amount)
        unit_norm = "minutes"
    elif unit in {"h", "hr", "hrs", "hour", "hours"}:
        delta = timedelta(hours=amount)
        unit_norm = "hours"
    elif unit in {"d", "day", "days"}:
        delta = timedelta(days=amount)
        unit_norm = "days"
    elif unit in {"w", "week", "weeks"}:
        delta = timedelta(weeks=amount)
        unit_norm = "weeks"
    else:
        raise ValueError(f"unsupported unit: {unit}")

    zone = _zone(tz)
    start = _parse_dt(base, tz=tz) if base else datetime.now(tz=zone)
    result = start.astimezone(zone) + delta
    return {
        "ok": True,
        "expression": expression.strip(),
        "amount": amount,
        "unit": unit_norm,
        "base_iso": start.isoformat(timespec="seconds"),
        "iso": result.isoformat(timespec="seconds"),
        "unix": int(result.timestamp()),
        "timezone": _zone_key(zone),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arka time utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_now = sub.add_parser("now", help="Current time")
    p_now.add_argument("--tz", default="")

    p_conv = sub.add_parser("convert", help="Convert datetime timezone")
    p_conv.add_argument("datetime")
    p_conv.add_argument("--to", required=True)
    p_conv.add_argument("--from-tz", default="")

    p_rel = sub.add_parser("relative", help="Apply relative offset")
    p_rel.add_argument("expression")
    p_rel.add_argument("--tz", default="")
    p_rel.add_argument("--base", default="")

    args = parser.parse_args(argv)
    if args.cmd == "now":
        payload = now_payload(tz=args.tz or None)
    elif args.cmd == "convert":
        payload = convert_payload(args.datetime, to_tz=args.to, from_tz=args.from_tz or None)
    else:
        payload = relative_payload(args.expression, tz=args.tz or None, base=args.base or None)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
