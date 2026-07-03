#!/usr/bin/env python3
"""Competition peer analysis + recent funding/VC/IPO intelligence for stock predictions."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

STOCK_PROJECT = Path(
    __import__("os").environ.get(
        "ARKA_STOCK_PROJECT", Path.home() / "Projects/python/products/stock_analysis"
    )
)

FUNDING_NEWS_FEEDS: list[tuple[str, str]] = [
    ("Startup funding India", "https://news.google.com/rss/search?q=startup+funding+India+Series+round+2025&hl=en-IN&gl=IN&ceid=IN:en"),
    ("VC / PE deals", "https://news.google.com/rss/search?q=venture+capital+private+equity+deal+India&hl=en-IN&gl=IN&ceid=IN:en"),
    ("IPO & listings", "https://news.google.com/rss/search?q=IPO+listing+NSE+BSE+India+2025&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Global VC", "https://news.google.com/rss/search?q=startup+funding+Series+A+B+million&hl=en-US&gl=US&ceid=US:en"),
    ("Corporate raise", "https://news.google.com/rss/search?q=company+raises+funding+investment+round&hl=en&gl=US&ceid=US:en"),
]

COMPETITION_NEWS_FEEDS: list[tuple[str, str]] = [
    ("Market share", "https://news.google.com/rss/search?q=market+share+competition+India+sector&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Corporate rivalry", "https://news.google.com/rss/search?q=competition+rival+pricing+war+India+business&hl=en-IN&gl=IN&ceid=IN:en"),
]

# Sector → listed peer groups for head-to-head comparison
PEER_GROUPS: dict[str, list[str]] = {
    "IT services": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTIM.NS"],
    "Private banks": ["HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS"],
    "Oil & gas": ["RELIANCE.NS", "ONGC.NS", "OIL.NS", "BPCL.NS", "HPCL.NS"],
    "Cement": ["ULTRACEMCO.NS", "ACC.NS", "AMBUJACEM.NS", "SHREECEM.NS"],
    "Auto": ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS"],
    "Telecom": ["BHARTIARTL.NS", "IDEA.NS"],
    "Consumer internet": ["ZOMATO.NS", "PAYTM.NS", "NYKAA.NS", "POLICYBZR.NS", "NAUKRI.NS"],
    "Pharma": ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "LUPIN.NS"],
    "FMCG": ["ITC.NS", "HINDUNILVR.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS"],
    "Defense": ["HAL.NS", "BEL.NS", "BDL.NS"],
    "Renewables": ["SUZLON.NS", "ADANIGREEN.NS", "TATAPOWER.NS", "NTPC.NS"],
    "Steel": ["TATASTEEL.NS", "JSWSTEEL.NS", "SAIL.NS", "JINDALSTEL.NS"],
    "Airlines": ["INDIGO.NS", "SPICEJET.NS"],
    "Paints": ["ASIANPAINT.NS", "BERGEPAINT.NS", "INDIGOPNTS.NS"],
}

# Startup/funding themes → listed beneficiaries (indirect exposure)
FUNDING_THEME_MAP: list[tuple[str, list[str], str]] = [
    (r"fintech|payments|upi|lending|neobank", ["PAYTM.NS", "HDFCBANK.NS", "ICICIBANK.NS", "POLICYBZR.NS"], "Fintech ecosystem"),
    (r"quick commerce|grocery|delivery|zomato|swiggy|blinkit", ["ZOMATO.NS", "DMART.NS", "TATACONSUM.NS"], "Quick commerce"),
    (r"\bai\b|artificial intelligence|genai|llm|machine learning", ["INFY.NS", "TCS.NS", "LTIM.NS", "PERSISTENT.NS", "COFORGE.NS"], "AI/tech services"),
    (r"saas|cloud|enterprise software", ["PERSISTENT.NS", "COFORGE.NS", "LTIM.NS", "TCS.NS"], "Enterprise SaaS"),
    (r"ev|electric vehicle|battery|charging", ["TATAMOTORS.NS", "M&M.NS", "EXIDEIND.NS", "TATAPOWER.NS"], "EV supply chain"),
    (r"defence|defense|drone|aerospace", ["HAL.NS", "BEL.NS", "BDL.NS", "MTARTECH.NS"], "Defense supply chain"),
    (r"renewable|solar|wind|green energy", ["SUZLON.NS", "ADANIGREEN.NS", "TATAPOWER.NS", "NTPC.NS"], "Renewables"),
    (r"healthtech|health tech|telemedicine|pharma tech", ["APOLLOHOSP.NS", "MAXHEALTH.NS", "SUNPHARMA.NS"], "Healthtech"),
    (r"edtech|education tech", ["NAUKRI.NS", "ZOMATO.NS"], "Consumer internet adjacency"),
    (r"semiconductor|chip|fab", ["VEDL.NS", "TATAELXSI.NS", "MOTHERSON.NS"], "Electronics/manufacturing"),
    (r"ipo|listing|public offering", ["NIFTYBEES.NS", "^NSEI"], "IPO market sentiment"),
]

TICKER_TO_SECTORS: dict[str, list[str]] = {}
for sector, tickers in PEER_GROUPS.items():
    for t in tickers:
        TICKER_TO_SECTORS.setdefault(t, []).append(sector)


@dataclass
class FundingSignal:
    headline: str
    source: str
    round_hint: str
    amount_hint: str
    sector_hint: str
    listed_peers: list[str]


@dataclass
class PeerRow:
    ticker: str
    sector: str
    price: float | None
    chg_1d: float | None
    chg_1mo: float | None
    volatility: float | None
    score: float


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _is_valid_headline(title: str) -> bool:
    t = title.lower()
    if len(t) < 28:
        return False
    junk = ("wikipedia", "what is", "definition", "how to start", "careers in")
    return not any(j in t for j in junk)


def _fetch_rss(source: str, url: str, limit: int, seen: set[str]) -> list[dict]:
    items: list[dict] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "arka-competition-funding/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8", errors="replace")
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml_data)
        for raw in titles[1:]:
            title = _clean_text(raw)
            if not _is_valid_headline(title):
                continue
            key = title.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append({"source": source, "title": title})
            if len(items) >= limit:
                break
    except Exception:
        pass
    return items


def _fetch_via_stock_project(feeds: dict[str, str], limit: int) -> list[dict]:
    py = STOCK_PROJECT / ".venv/bin/python3"
    if not py.is_file():
        return []
    code = (
        f"import json; feeds={json.dumps(feeds)}; "
        "from get_free_data import fetch_news; "
        f"n=fetch_news(feeds, 4, {limit * 2}); "
        "print(json.dumps([{'source':x['source'],'title':x['title']} for x in n]))"
    )
    try:
        proc = subprocess.run(
            [str(py), "-c", code],
            cwd=str(STOCK_PROJECT),
            capture_output=True,
            text=True,
            timeout=90,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip())
    except Exception:
        pass
    return []


def fetch_funding_news(limit: int = 8) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    feeds = {k: v for k, v in FUNDING_NEWS_FEEDS}
    for item in _fetch_via_stock_project(feeds, limit * 2):
        title = _clean_text(item.get("title", ""))
        if not _is_valid_headline(title):
            continue
        key = title.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        items.append({"source": item.get("source", "Funding"), "title": title})
        if len(items) >= limit:
            return items
    for source, url in FUNDING_NEWS_FEEDS:
        for item in _fetch_rss(source, url, 4, seen):
            items.append(item)
            if len(items) >= limit:
                return items
    return items


def fetch_competition_news(limit: int = 5) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for source, url in COMPETITION_NEWS_FEEDS:
        for item in _fetch_rss(source, url, 4, seen):
            items.append(item)
            if len(items) >= limit:
                return items
    return items


def _parse_funding_headline(headline: str) -> tuple[str, str, str]:
    low = headline.lower()
    round_hint = "unknown"
    for label, pat in (
        ("Pre-seed", r"pre-?seed"),
        ("Seed", r"\bseed\b"),
        ("Series A", r"series\s*a"),
        ("Series B", r"series\s*b"),
        ("Series C", r"series\s*c"),
        ("Series D+", r"series\s*[d-z]"),
        ("IPO", r"\bipo\b|listing|public offering"),
        ("PE/growth", r"private equity|growth round|growth capital"),
        ("Debt", r"debt funding|venture debt"),
    ):
        if re.search(pat, low):
            round_hint = label
            break

    amount_hint = "undisclosed"
    m = re.search(
        r"(?:\$|usd\s*|₹|rs\.?\s*|inr\s*)?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(million|mn|m\b|crore|cr|billion|bn|lakh|lac)\b",
        headline,
        re.I,
    )
    if m:
        amount_hint = f"{m.group(1)} {m.group(2)}"
    elif re.search(r"\$\d+", headline):
        amount_hint = re.search(r"(\$[\d.]+\s*[MBmb]?)", headline).group(1)  # type: ignore[union-attr]

    sector_hint = "general"
    for theme_pat, _, label in FUNDING_THEME_MAP:
        if re.search(theme_pat, low):
            sector_hint = label
            break
    return round_hint, amount_hint, sector_hint


def extract_funding_signals(news: list[dict]) -> list[FundingSignal]:
    signals: list[FundingSignal] = []
    for item in news:
        title = item.get("title", "")
        rnd, amt, sector = _parse_funding_headline(title)
        peers: list[str] = []
        low = title.lower()
        for theme_pat, tickers, _ in FUNDING_THEME_MAP:
            if re.search(theme_pat, low):
                for t in tickers:
                    if t not in peers:
                        peers.append(t)
        signals.append(FundingSignal(
            headline=title,
            source=item.get("source", ""),
            round_hint=rnd,
            amount_hint=amt,
            sector_hint=sector,
            listed_peers=peers[:6],
        ))
    return signals


def resolve_peer_groups(tickers: list[str], query: str = "") -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for t in tickers:
        for sector in TICKER_TO_SECTORS.get(t.upper(), []):
            groups[sector] = PEER_GROUPS[sector]
    if groups:
        return groups
    low = (query or "").lower()
    keyword_map = (
        (r"\bit\b|software|tcs|infosys", "IT services"),
        (r"bank|finance|lending", "Private banks"),
        (r"oil|energy|gas|ongc|reliance", "Oil & gas"),
        (r"cement|ultratech", "Cement"),
        (r"auto|car|vehicle|maruti", "Auto"),
        (r"telecom|jio|airtel", "Telecom"),
        (r"zomato|paytm|startup|internet", "Consumer internet"),
        (r"pharma|drug|medicine", "Pharma"),
        (r"fmcg|consumer goods", "FMCG"),
        (r"defence|defense|hal", "Defense"),
        (r"solar|wind|renewable", "Renewables"),
        (r"steel|iron", "Steel"),
        (r"airline|indigo", "Airlines"),
        (r"paint|asian paint", "Paints"),
    )
    for pat, sector in keyword_map:
        if re.search(pat, low):
            groups[sector] = PEER_GROUPS[sector]
    if not groups:
        groups["IT services"] = PEER_GROUPS["IT services"]
        groups["Private banks"] = PEER_GROUPS["Private banks"]
    return groups


def _fetch_quote(ticker: str) -> dict | None:
    encoded = urllib.parse.quote(ticker, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1mo"
    req = urllib.request.Request(url, headers={"User-Agent": "arka-competition-funding/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode())
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return None
        closes = [
            float(c)
            for c in result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if c is not None
        ]
        if len(closes) < 2:
            return None
        latest, prev, first = closes[-1], closes[-2], closes[0]
        rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
        vol = 0.0
        if len(rets) > 1:
            import statistics
            import math
            vol = statistics.stdev(rets) * math.sqrt(252) * 100
        return {
            "price": latest,
            "chg_1d": round((latest - prev) / prev * 100, 2) if prev else 0.0,
            "chg_1mo": round((latest - first) / first * 100, 2) if first else 0.0,
            "volatility": round(vol, 2),
        }
    except Exception:
        return None


def compare_peer_group(sector: str, tickers: list[str]) -> list[PeerRow]:
    rows: list[PeerRow] = []
    for ticker in tickers:
        q = _fetch_quote(ticker)
        chg_1d = q.get("chg_1d") if q else None
        chg_1mo = q.get("chg_1mo") if q else None
        vol = q.get("volatility") if q else None
        score = 0.0
        if q and chg_1d is not None and chg_1mo is not None:
            score = chg_1d * 1.5 + chg_1mo * 1.0 - (vol or 0) * 0.15
        elif not q:
            score = -999.0
        rows.append(PeerRow(
            ticker=ticker,
            sector=sector,
            price=q.get("price") if q else None,
            chg_1d=chg_1d,
            chg_1mo=chg_1mo,
            volatility=vol,
            score=round(score, 2),
        ))
    rows.sort(key=lambda r: r.score, reverse=True)
    return rows


def format_competition_funding_report(
    tickers: list[str] | None = None,
    query: str = "",
    *,
    funding_limit: int = 8,
    competition_limit: int = 5,
) -> tuple[str, list[str]]:
    sources = ["funding-news", "competition-peers"]
    lines = ["## Competition & funding intelligence"]

    # --- Recent fundings ---
    funding_news = fetch_funding_news(limit=funding_limit)
    lines.append("")
    lines.append("### Recent fundings & deals (live RSS)")
    if funding_news:
        signals = extract_funding_signals(funding_news)
        for i, sig in enumerate(signals, 1):
            peers = ", ".join(sig.listed_peers) if sig.listed_peers else "—"
            lines.append(
                f"{i}. **[{sig.round_hint}]** {sig.amount_hint} — _{sig.sector_hint}_"
            )
            lines.append(f"   [{sig.source}] {sig.headline[:120]}{'…' if len(sig.headline) > 120 else ''}")
            if sig.listed_peers:
                lines.append(f"   → Listed peers to watch: **{peers}**")
        sources.append("funding-parse")
    else:
        lines.append("(No funding headlines fetched.)")

    # --- Competition news ---
    comp_news = fetch_competition_news(limit=competition_limit)
    lines.append("")
    lines.append("### Competition & market-share headlines")
    if comp_news:
        for i, item in enumerate(comp_news, 1):
            lines.append(f"{i}. [{item['source']}] {item['title']}")
        sources.append("competition-news")
    else:
        lines.append("(No competition headlines fetched.)")

    # --- Peer comparison tables ---
    tickers = tickers or []
    groups = resolve_peer_groups(tickers, query)
    lines.append("")
    lines.append("### Peer competition scoreboard (live prices)")
    for sector, peers in list(groups.items())[:4]:
        rows = compare_peer_group(sector, peers)
        if not rows:
            continue
        lines.append("")
        lines.append(f"**{sector}** — ranked by momentum score (1d + 1mo − vol penalty):")
        lines.append("")
        lines.append("| Rank | Ticker | Price | 1d% | 1mo% | Vol% | Score | Leader? |")
        lines.append("|------|--------|-------|-----|------|------|-------|---------|")
        for i, row in enumerate(rows, 1):
            leader = "**#1**" if i == 1 else ("#2" if i == 2 else "")
            px = f"{row.price:,.2f}" if row.price else "—"
            c1 = f"{row.chg_1d:+.2f}" if row.chg_1d is not None else "—"
            cm = f"{row.chg_1mo:+.2f}" if row.chg_1mo is not None else "—"
            vol = f"{row.volatility:.1f}" if row.volatility is not None else "—"
            lines.append(
                f"| {i} | {row.ticker} | {px} | {c1} | {cm} | {vol} | {row.score:.1f} | {leader} |"
            )
        valid = [r for r in rows if r.price is not None]
        if not valid:
            continue
        leader = valid[0]
        laggard = valid[-1]
        leader_chg = f"{leader.chg_1mo:+.2f}%" if leader.chg_1mo is not None else "n/a"
        laggard_chg = f"{laggard.chg_1mo:+.2f}%" if laggard.chg_1mo is not None else "n/a"
        lines.append(
            f"  → **Leader:** {leader.ticker} ({leader_chg} 1mo) · "
            f"**Laggard:** {laggard.ticker} ({laggard_chg} 1mo)"
        )

    # --- Fundamental ratios (D/E, ROE, P/E, etc.) ---
    try:
        from arka.stock.fundamentals import format_fundamentals_table

        lines.append("")
        lines.append("### Fundamental ratios — debt/equity, ROE, P/E, margins")
        for sector, peers in list(groups.items())[:3]:
            tradable = [p for p in peers if not p.startswith("^")][:8]
            if tradable:
                lines.append("")
                lines.append(format_fundamentals_table(tradable, title=f"**{sector}**"))
        sources.append("fundamentals-yahoo")
    except Exception:
        pass

    lines.append("")
    lines.append("### How to use this data")
    lines.append("- **Funding in a theme** (AI, fintech, EV) → indirect tailwind for listed peers in that chain.")
    lines.append("- **Peer leader** with accelerating 1mo + fresh funding in sector → competitive momentum candidate.")
    lines.append("- **Peer laggard** + heavy competition news → avoid for short-term unless deep value thesis.")
    lines.append("- **IPO/funding boom** → sentiment boost for consumer internet; watch post-listing lock-up expiry.")
    lines.append("- **Low D/E + high ROE** → stronger balance sheet for long holds; **high D/E** → avoid for conservative short-term.")

    return "\n".join(lines), sources


def print_competition_funding_terminal(
    tickers: list[str] | None = None,
    query: str = "",
    *,
    funding_limit: int = 8,
    competition_limit: int = 5,
) -> None:
    from arka.stock.ui import banner, bullet, headline_item, leader_footer, note, pct, section, table, tag

    tickers = tickers or []
    banner("Competition & funding intel", subtitle="VC/PE deals · rivalry news · peer scoreboard")

    funding_news = fetch_funding_news(limit=funding_limit)
    section("Recent fundings & deals")
    if funding_news:
        signals = extract_funding_signals(funding_news)
        for i, sig in enumerate(signals[:funding_limit], 1):
            rnd = tag(sig.round_hint, "info" if sig.round_hint != "unknown" else "neutral")
            amt = sig.amount_hint if sig.amount_hint != "undisclosed" else "—"
            headline_item(i, sig.source, sig.headline, max_len=76)
            bullet(f"{rnd} · {amt} · {sig.sector_hint}", indent=6)
            if sig.listed_peers:
                peers = ", ".join(sig.listed_peers[:5])
                bullet(f"Listed peers: {peers}", indent=4)
    else:
        note("No funding headlines fetched.")

    comp_news = fetch_competition_news(limit=competition_limit)
    section("Competition headlines")
    if comp_news:
        for i, item in enumerate(comp_news, 1):
            headline_item(i, item["source"], item["title"])
    else:
        note("No competition headlines fetched.")

    groups = resolve_peer_groups(tickers, query)
    section("Peer scoreboard")
    for sector, peers in list(groups.items())[:3]:
        rows = compare_peer_group(sector, peers)
        valid = [r for r in rows if r.price is not None]
        if not valid:
            continue
        print(f"\n  {_c_sector(sector)}")
        table_rows = []
        for i, row in enumerate(rows, 1):
            leader = tag("#1", "good") if i == 1 else (tag("#2", "warn") if i == 2 else "")
            px = f"{row.price:,.2f}" if row.price else "—"
            table_rows.append([
                str(i),
                row.ticker,
                px,
                pct(row.chg_1d),
                pct(row.chg_1mo),
                f"{row.volatility:.1f}" if row.volatility is not None else "—",
                f"{row.score:.1f}",
                leader,
            ])
        table(
            ["#", "Ticker", "Price", "1d", "1mo", "Vol", "Score", ""],
            table_rows,
            aligns=["r", "l", "r", "r", "r", "r", "r", "c"],
        )
        leader, laggard = valid[0], valid[-1]
        leader_footer(
            leader.ticker,
            laggard.ticker,
            f"{leader.chg_1mo:+.2f}% 1mo" if leader.chg_1mo is not None else "n/a",
            f"{laggard.chg_1mo:+.2f}% 1mo" if laggard.chg_1mo is not None else "n/a",
        )

    try:
        from arka.stock.fundamentals import build_fundamental_rows, _fmt_num, _fmt_pct

        section("Fundamental ratios (peers)")
        for sector, peers in list(groups.items())[:2]:
            tradable = [p for p in peers if not p.startswith("^")][:6]
            frows = build_fundamental_rows(tradable)
            if not frows:
                continue
            print(f"\n  {_c_sector(sector)}")
            f_table = []
            for i, row in enumerate(frows, 1):
                m = row.metrics
                f_table.append([
                    str(i), row.ticker,
                    _fmt_num(m.get("debtToEquity"), 1),
                    _fmt_pct(m.get("returnOnEquity")),
                    _fmt_num(m.get("trailingPE"), 1),
                    f"{row.quality_score:.0f}",
                ])
            table(["#", "Ticker", "D/E", "ROE", "P/E", "Q"], f_table, aligns=["r", "l", "r", "r", "r", "r"])
    except Exception:
        pass

    note("Funding themes map to listed peers indirectly — verify before trading.")


def _c_num(i: int) -> str:
    from arka.stock.ui import C, use_color
    t = f"{i:>2}."
    return f"{C.DIM}{t}{C.RESET}" if use_color() else t


def _c_amt(text: str) -> str:
    from arka.stock.ui import C, use_color
    return f"{C.GREEN}{text}{C.RESET}" if use_color() and text != "—" else text


def _c_sector(text: str) -> str:
    from arka.stock.ui import C, use_color
    return f"{C.BOLD}{C.YELLOW}{text}{C.RESET}" if use_color() else text


def is_competition_funding_query(query: str) -> bool:
    low = query.lower()
    return bool(re.search(
        r"\b(funding|funded|series [a-z]|venture|vc\b|pe deal|ipo|listing|competition|competitor|"
        r"market share|rival|peer|vs\b|beat.*estimates|debt.?to.?equity|d/e ratio|"
        r"fundamental|p/e|roe|balance sheet|leverage)\b",
        low,
    ))


def main() -> int:
    import argparse
    import sys

    from arka.stock.ui import use_terminal_ui

    p = argparse.ArgumentParser(description="Competition + funding intelligence")
    p.add_argument("tickers", nargs="*", help="Optional tickers to focus peer groups")
    p.add_argument("--query", default="", help="Natural language query for sector detection")
    p.add_argument("--funding-limit", type=int, default=8)
    p.add_argument("--plain", action="store_true")
    args = p.parse_args()
    if args.plain:
        import os
        os.environ["ARKA_STOCK_PLAIN"] = "1"
    if use_terminal_ui():
        print_competition_funding_terminal(
            args.tickers, args.query, funding_limit=args.funding_limit
        )
    else:
        report, _ = format_competition_funding_report(
            args.tickers, args.query, funding_limit=args.funding_limit
        )
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
