#!/usr/bin/env python3
"""Natural-language timezone conversion using zoneinfo."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from dateutil import parser as date_parser
except ImportError:  # pragma: no cover - dateutil is a project dependency
    date_parser = None  # type: ignore[assignment]

TZ_ALIASES: dict[str, str] = {
    "utc": "UTC",
    "gmt": "UTC",
    "z": "UTC",
    "ist": "Asia/Kolkata",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "pt": "America/Los_Angeles",
    "est": "America/New_York",
    "edt": "America/New_York",
    "et": "America/New_York",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "ct": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "mt": "America/Denver",
    "akst": "America/Anchorage",
    "akdt": "America/Anchorage",
    "hst": "Pacific/Honolulu",
    "bst": "Europe/London",
    "cet": "Europe/Paris",
    "cest": "Europe/Paris",
    "eet": "Europe/Bucharest",
    "eest": "Europe/Bucharest",
    "wet": "Europe/Lisbon",
    "jst": "Asia/Tokyo",
    "kst": "Asia/Seoul",
    "sgt": "Asia/Singapore",
    "hkt": "Asia/Hong_Kong",
    "aest": "Australia/Sydney",
    "aedt": "Australia/Sydney",
    "nzst": "Pacific/Auckland",
    "nzdt": "Pacific/Auckland",
    "msk": "Europe/Moscow",
    "pkt": "Asia/Karachi",
    "brt": "America/Sao_Paulo",
    "art": "America/Argentina/Buenos_Aires",
    # Common city names (normalized: lowercase, no spaces/punctuation)
    "tokyo": "Asia/Tokyo",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "rome": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "moscow": "Europe/Moscow",
    "dubai": "Asia/Dubai",
    "singapore": "Asia/Singapore",
    "hongkong": "Asia/Hong_Kong",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "seoul": "Asia/Seoul",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "auckland": "Pacific/Auckland",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "newyork": "America/New_York",
    "losangeles": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "denver": "America/Denver",
    "toronto": "America/Toronto",
    "vancouver": "America/Vancouver",
    "saopaulo": "America/Sao_Paulo",
    "buenosaires": "America/Argentina/Buenos_Aires",
}

_TZ_NAMES = "|".join(sorted(TZ_ALIASES, key=len, reverse=True))
_TZ_TOKEN_RE = re.compile(rf"(?i)\b({_TZ_NAMES})\b")
_TIME_RE = re.compile(
    r"(?i)\b(?:"
    r"\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?|"
    r"\d{1,2}\s*(?:am|pm)|"
    r"\d{1,2}:\d{2}\s*(?:am|pm)?|"
    r"noon|midnight"
    r")\b"
)
_DATE_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|"
    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"\d{4}-\d{2}-\d{2}"
    r")\b"
)
_INTENT_RE = re.compile(
    r"(?i)\b(?:"
    r"timezone(?:\s+convert)?|time\s+zone|what\s+time|convert\s+(?:\d|today|tomorrow|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))"
    r")\b"
)
_CURRENT_TIME_RE = re.compile(
    r"(?i)\b(?:"
    r"what(?:'s|\s+is)\s+(?:the\s+)?time(?:\s+is\s+it)?|"
    r"what\s+time(?:\s+is\s+it)?|"
    r"time\s+now|"
    r"time\s+in|"
    r"current\s+time"
    r")\b"
)
_NOISE_RE = re.compile(
    r"(?i)^(?:please\s+)?(?:arka\s+)?(?:timezone_convert|timezone|tz_convert|tz)\s+"
)
_FILLER_RE = re.compile(
    r"(?i)\b(?:what\s+is|what's|whats|convert|this|that|the|please|time|zone|at|on)\b"
)
_KNOWN_CMDS = frozenset({"parse", "convert"})


def normalize_tz(token: str) -> str | None:
    raw = (token or "").strip()
    if not raw:
        return None
    if "/" in raw:
        try:
            ZoneInfo(raw)
        except ZoneInfoNotFoundError:
            return None
        return raw
    key = re.sub(r"[^a-z]", "", raw.lower())
    return TZ_ALIASES.get(key)


def _zone(name: str) -> ZoneInfo:
    iana = normalize_tz(name)
    if not iana:
        raise ValueError(f"Unknown timezone: {name!r}")
    return ZoneInfo(iana)


def _zone_label(name: str) -> str:
    iana = normalize_tz(name) or name
    token = (name or "").strip().upper()
    if token and token.lower() in TZ_ALIASES:
        return token
    return iana


def _has_time_signal(text: str) -> bool:
    return bool(
        _TIME_RE.search(text)
        or _DATE_RE.search(text)
        or _INTENT_RE.search(text)
        or _CURRENT_TIME_RE.search(text)
    )


def _is_current_time_query(text: str) -> bool:
    return bool(_CURRENT_TIME_RE.search(text or ""))


def _local_tz_name() -> str:
    tz = datetime.now().astimezone().tzinfo
    key = getattr(tz, "key", None)
    if key:
        return str(key)
    return "UTC"


def wants_timezone_convert(text: str) -> bool:
    clean = (text or "").strip()
    if not clean or not _TZ_TOKEN_RE.search(clean):
        return False
    if not _has_time_signal(clean):
        return False
    try:
        from arka.integrations.currency import parse_convert as parse_currency

        if parse_currency(clean):
            return False
    except ImportError:
        pass
    return parse_convert(clean) is not None


def _strip_wrapping_quotes(text: str) -> str:
    t = (text or "").strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1].strip()
    return t


def _normalize_text(text: str) -> str:
    t = _strip_wrapping_quotes(text)
    t = _NOISE_RE.sub("", t)
    t = re.sub(r"(?i)^(?:please\s+)?(?:arka\s+)?(?:convert|what\s+is|what's)\s+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_datetime(text: str) -> datetime | None:
    if date_parser is None:
        return None
    cleaned = _FILLER_RE.sub(" ", text or "")
    cleaned = _TZ_TOKEN_RE.sub(" ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:to|in|into)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;")
    if not cleaned:
        return None
    try:
        return date_parser.parse(
            cleaned,
            default=datetime.now().replace(hour=9, minute=0, second=0, microsecond=0),
            fuzzy=True,
        )
    except (ValueError, TypeError, OverflowError):
        return None


def _infer_zones(text: str) -> tuple[str | None, str | None]:
    from_tz: str | None = None
    to_tz: str | None = None

    pair = re.search(rf"(?i)\b({_TZ_NAMES})\s+(?:to|in|into)\s+({_TZ_NAMES})\b", text)
    if pair:
        from_tz = normalize_tz(pair.group(1))
        to_tz = normalize_tz(pair.group(2))

    target = re.search(rf"(?i)\b(?:to|in|into)\s+({_TZ_NAMES})\b", text)
    if target:
        to_tz = to_tz or normalize_tz(target.group(1))

    source_after_time = re.search(rf"(?i){_TIME_RE.pattern}\s+({_TZ_NAMES})\b", text)
    if source_after_time:
        from_tz = from_tz or normalize_tz(source_after_time.group(1))

    source_before_target = re.search(rf"(?i)\b({_TZ_NAMES})\s+(?:to|in|into)\s+({_TZ_NAMES})\b", text)
    if source_before_target:
        from_tz = from_tz or normalize_tz(source_before_target.group(1))

    tokens = [normalize_tz(m.group(1)) for m in _TZ_TOKEN_RE.finditer(text)]
    tokens = [tz for tz in tokens if tz]
    if not to_tz and len(tokens) >= 2:
        to_tz = tokens[-1]
    if not from_tz and len(tokens) >= 2:
        from_tz = tokens[0]
    if not from_tz and len(tokens) == 1 and to_tz and tokens[0] != to_tz:
        from_tz = tokens[0]
    if not to_tz and len(tokens) == 1:
        lone = tokens[0]
        if re.search(rf"(?i)\b(?:to|in|into)\s+{re.escape(lone.split('/')[-1])}\b", text):
            to_tz = lone
        elif source_after_time:
            from_tz = lone

    return from_tz, to_tz


def parse_convert(text: str) -> tuple[datetime, str, str] | None:
    """Parse NL into (naive datetime, from_tz, to_tz)."""
    t = _normalize_text(text)
    if not t or not _TZ_TOKEN_RE.search(t) or not _has_time_signal(t):
        return None

    now_query = _is_current_time_query(t)
    from_tz, to_tz = _infer_zones(t)
    if not to_tz:
        return None
    if not from_tz:
        from_tz = _local_tz_name() if now_query else "UTC"

    dt = _parse_datetime(t)
    if dt is None:
        if not now_query:
            return None
        dt = datetime.now().replace(second=0, microsecond=0)

    if from_tz == to_tz and not now_query:
        return None

    return dt.replace(tzinfo=None), from_tz, to_tz


def nl_to_argv(text: str) -> list[str]:
    parsed = parse_convert(text)
    if not parsed:
        return []
    dt, from_tz, to_tz = parsed
    return [
        dt.isoformat(sep=" ", timespec="minutes"),
        "--from",
        from_tz,
        "--to",
        to_tz,
    ]


def route_command(text: str) -> str:
    if not wants_timezone_convert(text):
        return ""
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "timezone_convert " + " ".join(shlex.quote(a) for a in argv)


def convert_datetime(dt: datetime, *, from_tz: str, to_tz: str) -> dict[str, Any]:
    source = _zone(from_tz)
    target = _zone(to_tz)
    if dt.tzinfo is None:
        localized = dt.replace(tzinfo=source)
    else:
        localized = dt.astimezone(source)
    converted = localized.astimezone(target)
    return {
        "input": dt.isoformat(sep=" ", timespec="minutes"),
        "from_timezone": _zone_label(from_tz),
        "to_timezone": _zone_label(to_tz),
        "from_iana": source.key,
        "to_iana": target.key,
        "from_local": localized.strftime("%A, %B %-d, %Y at %-I:%M %p %Z"),
        "to_local": converted.strftime("%A, %B %-d, %Y at %-I:%M %p %Z"),
        "iso": converted.isoformat(timespec="minutes"),
    }


def format_result(payload: dict[str, Any]) -> str:
    lines = [
        "━━━ Timezone Conversion ━━━",
        "",
        f"  {payload['from_local']}",
        "  ↓",
        f"  {payload['to_local']}",
        "",
        f"  {payload['from_timezone']} → {payload['to_timezone']}",
    ]
    return "\n".join(lines)


def cmd_convert(argv: list[str]) -> int:
    text = " ".join(argv).strip()
    if not text:
        print(
            "Usage: timezone_convert <datetime> --from <tz> --to <tz>\n"
            "       timezone_convert convert July 13 9:00am PDT to IST\n"
            "       arka 'what is July 13 at 9:00am PDT in IST'",
            file=sys.stderr,
        )
        return 1

    parsed = parse_convert(text)
    if not parsed and "--from" in argv and "--to" in argv:
        try:
            to_idx = argv.index("--to")
            from_idx = argv.index("--from")
            dt_text = " ".join(argv[:from_idx]).strip()
            from_tz = argv[from_idx + 1]
            to_tz = argv[to_idx + 1]
            dt = _parse_datetime(dt_text) or datetime.fromisoformat(dt_text.replace(" ", "T", 1))
            parsed = (dt.replace(tzinfo=None), from_tz, to_tz)
        except (IndexError, ValueError):
            parsed = None

    if not parsed:
        print(
            f"Could not parse timezone conversion: {text!r}\n"
            "Examples:\n"
            "  what is July 13 at 9:00am PDT in IST\n"
            "  convert 9am PDT to IST\n"
            "  timezone_convert 'July 13 9:00' --from PDT --to IST",
            file=sys.stderr,
        )
        return 1

    dt, from_tz, to_tz = parsed
    try:
        payload = convert_datetime(dt, from_tz=from_tz, to_tz=to_tz)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(format_result(payload))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: arka_timezone_convert.py [convert] <natural language>\n"
            "       arka_timezone_convert.py parse <natural language>",
            file=sys.stderr,
        )
        return 0 if not argv else 1

    if argv[0] == "parse":
        return cmd_parse(argparse.Namespace(text=argv[1:]))

    if argv[0] == "convert":
        return cmd_convert(argv[1:])

    if argv[0] not in _KNOWN_CMDS:
        return cmd_convert(argv)

    parser = argparse.ArgumentParser(description="Convert datetimes between timezones.")
    sub = parser.add_subparsers(dest="cmd")
    p_parse = sub.add_parser("parse", help="Parse natural language → args (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)
    sub.add_parser("convert", help="Convert datetime between timezones").set_defaults(
        func=lambda _a: cmd_convert(argv[1:])
    )
    args = parser.parse_args()
    if args.cmd is None:
        return cmd_convert(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
