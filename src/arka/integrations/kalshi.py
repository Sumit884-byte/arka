#!/usr/bin/env python3
"""Kalshi prediction market quotes via the public Trade API (read-only, no API key)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; Arka/1.0)"
DEFAULT_BASE = "https://external-api.kalshi.com/trade-api/v2"

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$", re.I)
_SEARCH_QUERY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\s._'-]{0,120}$")

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"kalshi(?:\s+predictions?|\s+odds|\s+markets?|\s+market|\s+status|\s+trending)?|"
    r"prediction\s+market(?:s)?(?:\s+on|\s+for|\s+about)?|"
    r"what\s+are\s+(?:the\s+)?kalshi\s+odds|"
    r"kalshi\s+odds\s+(?:for|on|about)"
    r")\b"
)
_KNOWN_CMDS = frozenset({"search", "market", "trending", "status", "parse"})


def api_base() -> str:
    return (os.environ.get("KALSHI_API_BASE") or DEFAULT_BASE).rstrip("/")


def _auth_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    key = (os.environ.get("KALSHI_API_KEY") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _fetch_json(path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = f"{api_base()}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:240]
        raise RuntimeError(f"Kalshi API HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Kalshi API unavailable: {exc.reason}") from exc


def sanitize_search_query(query: str) -> str:
    raw = re.sub(r"\s+", " ", (query or "").strip())
    if not raw or not _SEARCH_QUERY_RE.fullmatch(raw):
        raise ValueError(f"Invalid search query: {query!r}")
    return raw


def sanitize_ticker(ticker: str) -> str:
    raw = (ticker or "").strip().upper()
    if not raw or not _TICKER_RE.fullmatch(raw):
        raise ValueError(f"Invalid market ticker: {ticker!r}")
    return raw


def _market_text(market: dict[str, Any]) -> str:
    parts = [
        str(market.get("title") or ""),
        str(market.get("subtitle") or ""),
        str(market.get("yes_sub_title") or ""),
        str(market.get("no_sub_title") or ""),
        str(market.get("ticker") or ""),
        str(market.get("event_ticker") or ""),
    ]
    return " ".join(p for p in parts if p).lower()


def _float_field(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _price_dollars(market: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    yes_bid = market.get("yes_bid_dollars")
    yes_ask = market.get("yes_ask_dollars")
    last = market.get("last_price_dollars")
    bid = _float_field(yes_bid) if yes_bid not in (None, "") else None
    ask = _float_field(yes_ask) if yes_ask not in (None, "") else None
    traded = _float_field(last) if last not in (None, "") else None
    return bid, ask, traded


def _format_prob(dollars: float | None) -> str:
    if dollars is None:
        return "—"
    cents = dollars * 100
    if cents >= 10:
        return f"{cents:.1f}¢"
    return f"{cents:.2f}¢"


def _format_volume(market: dict[str, Any]) -> str:
    vol = market.get("volume_24h_fp") or market.get("volume_fp") or "0"
    try:
        n = float(str(vol).replace(",", ""))
    except ValueError:
        return str(vol)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:.0f}"


def _format_close_time(market: dict[str, Any]) -> str:
    raw = market.get("close_time") or market.get("expected_expiration_time") or ""
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    except ValueError:
        return str(raw)[:19]


def _market_title(market: dict[str, Any]) -> str:
    title = (market.get("title") or "").strip()
    subtitle = (market.get("subtitle") or "").strip()
    yes_sub = (market.get("yes_sub_title") or "").strip()
    if title and subtitle:
        return f"{title} — {subtitle}"
    if title:
        return title
    if yes_sub:
        return yes_sub
    return str(market.get("ticker") or "Unknown market")


def format_market_line(market: dict[str, Any], *, detailed: bool = False) -> str:
    ticker = market.get("ticker") or "?"
    title = _market_title(market)
    bid, ask, last = _price_dollars(market)
    mid = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2
    elif last is not None:
        mid = last
    yes = _format_prob(mid)
    no = _format_prob(1 - mid if mid is not None else None)
    vol = _format_volume(market)
    close = _format_close_time(market)
    status = market.get("status") or "?"
    line = f"  {ticker}  YES {yes}  NO {no}  vol {vol}  close {close}  [{status}]"
    if detailed:
        spread = ""
        if bid is not None and ask is not None:
            spread = f"bid {_format_prob(bid)} / ask {_format_prob(ask)}"
        elif last is not None:
            spread = f"last {_format_prob(last)}"
        return "\n".join(
            [
                f"━━━ {title} ━━━",
                f"  Ticker: {ticker}",
                f"  Event:  {market.get('event_ticker') or '—'}",
                f"  YES:    {yes}   NO: {no}",
                f"  Quote:  {spread or '—'}",
                f"  Volume: {vol} (24h preferred)",
                f"  Close:  {close}",
                f"  Status: {status}",
            ]
        )
    return f"{line}\n    {title[:100]}"


def fetch_market(ticker: str) -> dict[str, Any]:
    safe = sanitize_ticker(ticker)
    data = _fetch_json(f"/markets/{urllib.parse.quote(safe, safe='')}")
    market = data.get("market")
    if not isinstance(market, dict):
        raise RuntimeError(f"Market not found: {safe}")
    return market


def fetch_open_markets(*, limit: int = 200, max_pages: int = 3) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    cursor = ""
    per_page = max(1, min(limit, 1000))
    for _ in range(max_pages):
        params: dict[str, str] = {"status": "open", "limit": str(per_page)}
        if cursor:
            params["cursor"] = cursor
        data = _fetch_json("/markets", params=params)
        batch = data.get("markets") or []
        if not isinstance(batch, list):
            break
        markets.extend(m for m in batch if isinstance(m, dict))
        cursor = str(data.get("cursor") or "").strip()
        if not cursor or len(batch) < per_page:
            break
    return markets


def search_markets(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    safe = sanitize_search_query(query)
    tokens = [t for t in re.split(r"\s+", safe.lower()) if t]
    if not tokens:
        return []
    pool = fetch_open_markets(limit=200, max_pages=3)
    scored: list[tuple[int, dict[str, Any]]] = []
    for market in pool:
        text = _market_text(market)
        score = sum(1 for tok in tokens if tok in text)
        if score:
            scored.append((score, market))
    scored.sort(key=lambda item: (-item[0], -_float_field(item[1].get("volume_24h_fp"))))
    return [m for _, m in scored[: max(1, min(limit, 25))]]


def trending_markets(*, limit: int = 10) -> list[dict[str, Any]]:
    pool = fetch_open_markets(limit=200, max_pages=2)
    pool.sort(key=lambda m: _float_field(m.get("volume_24h_fp")), reverse=True)
    return pool[: max(1, min(limit, 25))]


def exchange_status() -> dict[str, Any]:
    data = _fetch_json("/exchange/status")
    return data if isinstance(data, dict) else {}


def format_status(data: dict[str, Any]) -> str:
    active = data.get("exchange_active")
    trading = data.get("trading_active")
    resume = data.get("exchange_estimated_resume_time") or "—"
    lines = [
        "━━━ Kalshi Exchange Status ━━━",
        "",
        f"  Exchange active: {active}",
        f"  Trading active:  {trading}",
        f"  Resume ETA:      {resume}",
        f"  API base:        {api_base()}",
    ]
    return "\n".join(lines)


def format_market_list(
    markets: list[dict[str, Any]],
    *,
    heading: str,
    empty_hint: str,
) -> str:
    if not markets:
        return f"{heading}\n\n  {empty_hint}"
    lines = [heading, ""]
    for market in markets:
        lines.append(format_market_line(market))
        lines.append("")
    return "\n".join(lines).rstrip()


def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    if not query:
        print("Usage: kalshi search <keywords>", file=sys.stderr)
        return 1
    try:
        markets = search_markets(query, limit=args.limit)
    except (ValueError, RuntimeError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(
        format_market_list(
            markets,
            heading=f"━━━ Kalshi search: {query} ━━━",
            empty_hint="No open markets matched. Try a shorter keyword or check kalshi trending.",
        )
    )
    return 0


def cmd_market(args: argparse.Namespace) -> int:
    ticker = (args.ticker or "").strip()
    if not ticker:
        print("Usage: kalshi market <TICKER>", file=sys.stderr)
        return 1
    try:
        market = fetch_market(ticker)
    except (ValueError, RuntimeError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(format_market_line(market, detailed=True))
    return 0


def cmd_trending(args: argparse.Namespace) -> int:
    try:
        markets = trending_markets(limit=args.limit)
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(
        format_market_list(
            markets,
            heading="━━━ Kalshi trending (24h volume) ━━━",
            empty_hint="No open markets returned.",
        )
    )
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    try:
        data = exchange_status()
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(format_status(data))
    return 0


def _strip_nl_prefix(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:arka\s+)?(?:show\s+me\s+|get\s+|tell\s+me\s+|what\s+are\s+|what\s+is\s+)?",
        "",
        t,
    )
    t = re.sub(r"(?i)^kalshi\s+(?:predictions?|odds|markets?|market)\s+(?:on|for|about)\s+", "", t)
    t = re.sub(r"(?i)^kalshi\s+(?:odds|predictions?)\s+(?:for|on|about)\s+", "", t)
    t = re.sub(r"(?i)^prediction\s+markets?\s+(?:on|for|about)\s+", "", t)
    t = re.sub(r"(?i)^kalshi\s+", "", t)
    return t.strip()


def nl_to_argv(text: str) -> list[str]:
    """Parse natural language into kalshi argv."""
    raw = (text or "").strip()
    if not raw:
        return []
    lower = raw.lower()
    if not _TRIGGER_RE.search(raw) and "kalshi" not in lower:
        return []

    if re.search(r"(?i)\b(?:status|health|online|offline|maintenance)\b", raw):
        return ["status"]

    if re.search(r"(?i)\btrending\b", raw):
        return ["trending"]

    m = re.search(r"(?i)\b(?:market|ticker)\s+([A-Z0-9][A-Z0-9._-]{1,63})\b", raw)
    if m:
        return ["market", m.group(1)]

    rest = _strip_nl_prefix(raw)
    if not rest:
        return ["trending"]

    if re.fullmatch(r"(?i)(?:status|trending)", rest):
        return [rest.lower()]

    if _TICKER_RE.fullmatch(rest) and rest.upper() == rest:
        return ["market", rest]

    if rest:
        return ["search", rest]
    return ["trending"]


def wants_kalshi(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "kalshi " + " ".join(shlex.quote(a) for a in argv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kalshi prediction market quotes (read-only)")
    sub = parser.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse natural language → argv (internal)")
    p_parse.add_argument("text", nargs="+")

    p_search = sub.add_parser("search", help="Search open markets by keyword")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_market = sub.add_parser("market", help="Show one market by ticker")
    p_market.add_argument("ticker")
    p_market.set_defaults(func=cmd_market)

    p_trending = sub.add_parser("trending", help="Top open markets by 24h volume")
    p_trending.add_argument("--limit", type=int, default=10)
    p_trending.set_defaults(func=cmd_trending)

    sub.add_parser("status", help="Kalshi exchange status").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    if args.cmd == "parse":
        out = nl_to_argv(" ".join(args.text))
        if not out:
            return 1
        print(" ".join(shlex.quote(a) for a in out))
        return 0

    if hasattr(args, "func"):
        return int(args.func(args))

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
