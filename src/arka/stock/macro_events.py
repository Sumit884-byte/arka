#!/usr/bin/env python3
"""Macro event intelligence: disasters, resources, geopolitics → sector/stock impact + duration."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

FISH_DIR = Path.home() / ".config" / "fish"
STOCK_PROJECT = Path(
    __import__("os").environ.get(
        "ARKA_STOCK_PROJECT", Path.home() / "Projects/python/products/stock_analysis"
    )
)

MACRO_NEWS_FEEDS: list[tuple[str, str]] = [
    ("Disasters", "https://news.google.com/rss/search?q=natural+disaster+earthquake+flood+wildfire&hl=en&gl=US&ceid=US:en"),
    ("Climate/Resources", "https://news.google.com/rss/search?q=commodity+shortage+oil+gas+mining+drought&hl=en&gl=US&ceid=US:en"),
    ("Geopolitics", "https://news.google.com/rss/search?q=war+sanctions+supply+chain+disruption+stock+market&hl=en&gl=US&ceid=US:en"),
    ("India disasters", "https://news.google.com/rss/search?q=India+flood+cyclone+earthquake+disaster&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Energy shock", "https://news.google.com/rss/search?q=crude+oil+price+OPEC+energy+crisis&hl=en&gl=US&ceid=US:en"),
]

# Event type → beneficiaries/losers with typical impact duration
EVENT_PLAYBOOK: dict[str, dict] = {
    "earthquake": {
        "keywords": (r"earthquake", r"seismic", r"tremor", r"aftershock"),
        "beneficiaries": [
            {"tickers": ["ULTRACEMCO.NS", "ACC.NS", "AMBUJACEM.NS"], "sector": "Cement & construction", "duration": "2–8 weeks", "move": "+5–15% typical rebuild rally"},
            {"tickers": ["LT.NS", "IRB.NS"], "sector": "Infrastructure/EPC", "duration": "1–3 months", "move": "Order-book optimism"},
            {"tickers": ["TATASTEEL.NS", "JSWSTEEL.NS"], "sector": "Steel", "duration": "2–6 weeks", "move": "Reconstruction demand"},
        ],
        "losers": [
            {"tickers": ["ICICIBANK.NS", "HDFCBANK.NS"], "sector": "Banks (local exposure)", "duration": "1–4 weeks", "move": "NPA/credit risk fears"},
        ],
    },
    "flood_cyclone": {
        "keywords": (r"flood", r"cyclone", r"hurricane", r"typhoon", r"landslide", r"monsoon.*damage"),
        "beneficiaries": [
            {"tickers": ["ULTRACEMCO.NS", "LT.NS"], "sector": "Reconstruction", "duration": "3–10 weeks", "move": "Relief/rebuild spending"},
            {"tickers": ["UPL.NS", "PIIND.NS"], "sector": "Agrochemicals (crop recovery)", "duration": "1–2 months", "move": "Demand for inputs"},
            {"tickers": ["IRCTC.NS"], "sector": "Travel (post-recovery)", "duration": "2–4 weeks dip then recovery", "move": "Volatile"},
        ],
        "losers": [
            {"tickers": ["ITC.NS", "BRITANNIA.NS"], "sector": "FMCG (rural demand hit)", "duration": "2–6 weeks", "move": "Volume disruption"},
            {"tickers": ["SBIN.NS"], "sector": "PSU banks (rural NPAs)", "duration": "1–3 months", "move": "Regional stress"},
        ],
    },
    "drought_agri": {
        "keywords": (r"drought", r"crop.*fail", r"monsoon.*deficit", r"food.*shortage", r"harvest.*loss"),
        "beneficiaries": [
            {"tickers": ["UPL.NS", "PIIND.NS", "RALLIS.NS"], "sector": "Agrochemicals/irrigation", "duration": "1–3 months", "move": "Input demand rises"},
            {"tickers": ["ITC.NS"], "sector": "Agri-trading (price volatility)", "duration": "2–8 weeks", "move": "Mixed"},
        ],
        "losers": [
            {"tickers": ["ITC.NS", "MARICO.NS"], "sector": "FMCG raw-material cost", "duration": "1–2 months", "move": "Margin pressure"},
        ],
    },
    "oil_gas_spike": {
        "keywords": (r"oil.*surge", r"crude.*jump", r"oil.*spike", r"OPEC.*cut", r"energy.*crisis", r"gas.*shortage", r"oil.*sanction"),
        "beneficiaries": [
            {"tickers": ["RELIANCE.NS", "ONGC.NS", "OIL.NS"], "sector": "Oil & gas upstream", "duration": "2 days–8 weeks", "move": "Tracks crude +3–12%"},
            {"tickers": ["GAIL.NS"], "sector": "Gas distribution", "duration": "1–4 weeks", "move": "Spread-dependent"},
            {"tickers": ["XOM", "CVX"], "sector": "US oil majors", "duration": "1–6 weeks", "move": "Earnings leverage"},
        ],
        "losers": [
            {"tickers": ["INDIGO.NS", "SPICEJET.NS"], "sector": "Airlines", "duration": "2–8 weeks", "move": "Fuel cost −5–15%"},
            {"tickers": ["BPCL.NS", "HPCL.NS"], "sector": "OMCs (marketing margin squeeze)", "duration": "1–3 weeks", "move": "Unless pass-through fast"},
            {"tickers": ["ASIANPAINT.NS", "BERGEPAINT.NS"], "sector": "Paints (input costs)", "duration": "2–4 weeks", "move": "Margin worry"},
        ],
    },
    "oil_gas_drop": {
        "keywords": (r"oil.*fall", r"crude.*drop", r"oil.*plunge", r"OPEC.*increase", r"oil.*glut"),
        "beneficiaries": [
            {"tickers": ["INDIGO.NS", "BPCL.NS", "HPCL.NS"], "sector": "Airlines & OMCs", "duration": "2–6 weeks", "move": "Margin relief"},
            {"tickers": ["ASIANPAINT.NS"], "sector": "Paints/chemicals", "duration": "2–4 weeks", "move": "Input cost ease"},
        ],
        "losers": [
            {"tickers": ["ONGC.NS", "OIL.NS", "RELIANCE.NS"], "sector": "Upstream (partial)", "duration": "1–4 weeks", "move": "E&P sentiment"},
        ],
    },
    "mining_resource": {
        "keywords": (r"mining.*disaster", r"mine.*collapse", r"coal.*shortage", r"iron.*ore", r"copper.*shortage", r"lithium", r"rare.*earth"),
        "beneficiaries": [
            {"tickers": ["COALINDIA.NS", "NMDC.NS", "HINDCOPPER.NS"], "sector": "Mining PSUs", "duration": "2–8 weeks", "move": "Supply tightness premium"},
            {"tickers": ["TATASTEEL.NS", "JSWSTEEL.NS"], "sector": "Steel (input cost)", "duration": "1–3 months", "move": "Inverse if ore spikes"},
            {"tickers": ["GC=F"], "sector": "Gold (safe haven)", "duration": "1–4 weeks", "move": "Risk-off bid"},
        ],
        "losers": [
            {"tickers": ["TATASTEEL.NS"], "sector": "Steel (if ore price up)", "duration": "2–6 weeks", "move": "Cost pressure"},
        ],
    },
    "war_geopolitical": {
        "keywords": (r"\bwar\b", r"invasion", r"missile", r"sanction", r"military.*conflict", r"geopolitical", r"naval.*blockade", r"\biran\b", r"middle east.*tension"),
        "beneficiaries": [
            {"tickers": ["HAL.NS", "BEL.NS", "BDL.NS"], "sector": "Defense India", "duration": "1–6 months", "move": "Order sentiment +5–20%"},
            {"tickers": ["GC=F", "GLD"], "sector": "Gold", "duration": "2 days–3 months", "move": "Safe-haven rally"},
            {"tickers": ["ONGC.NS", "RELIANCE.NS"], "sector": "Energy", "duration": "1–8 weeks", "move": "Risk premium on oil"},
            {"tickers": ["LMT", "RTX", "NOC"], "sector": "US defense", "duration": "1–3 months", "move": "Sector rotation"},
        ],
        "losers": [
            {"tickers": ["^NSEI", "NIFTYBEES.NS"], "sector": "Broad market", "duration": "1–4 weeks", "move": "Risk-off −3–10%"},
            {"tickers": ["INDIGO.NS"], "sector": "Airlines/travel", "duration": "2–8 weeks", "move": "Route disruption"},
        ],
    },
    "renewable_push": {
        "keywords": (r"renewable.*push", r"solar.*boom", r"wind.*energy", r"clean.*energy.*policy", r"climate.*investment"),
        "beneficiaries": [
            {"tickers": ["SUZLON.NS", "ADANIGREEN.NS", "TATAPOWER.NS"], "sector": "Renewables India", "duration": "1–6 months", "move": "Policy tailwind"},
            {"tickers": ["ENPH", "FSLR"], "sector": "US solar", "duration": "2–8 weeks", "move": "Sector beta"},
        ],
        "losers": [
            {"tickers": ["COALINDIA.NS"], "sector": "Coal (long-term headwind)", "duration": "months–years", "move": "Structural, not trade"},
        ],
    },
    "pandemic_health": {
        "keywords": (r"pandemic", r"outbreak", r"virus.*surge", r"health.*emergency", r"lockdown"),
        "beneficiaries": [
            {"tickers": ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS"], "sector": "Pharma", "duration": "2–8 weeks", "move": "Defensive + API demand"},
            {"tickers": ["APOLLOHOSP.NS", "MAXHEALTH.NS"], "sector": "Hospitals", "duration": "1–3 months", "move": "Volume spike"},
        ],
        "losers": [
            {"tickers": ["IRCTC.NS", "INDIGO.NS"], "sector": "Travel/leisure", "duration": "1–3 months", "move": "Demand collapse"},
            {"tickers": ["TITAN.NS"], "sector": "Discretionary retail", "duration": "2–6 weeks", "move": "Footfall drop"},
        ],
    },
    "food_commodity_shock": {
        "keywords": (r"food.*price", r"food.*shortage", r"el.?nino", r"la.?nina", r"supply.?chain.*disrupt", r"wheat.*surge", r"grain.*crisis"),
        "beneficiaries": [
            {"tickers": ["ITC.NS", "LTFOODS.NS"], "sector": "Food/agri-trading", "duration": "2–8 weeks", "move": "Price volatility"},
            {"tickers": ["UPL.NS", "PIIND.NS"], "sector": "Agrochemicals", "duration": "1–3 months", "move": "Crop protection demand"},
            {"tickers": ["GC=F"], "sector": "Gold (inflation hedge)", "duration": "2–6 weeks", "move": "Safe haven"},
        ],
        "losers": [
            {"tickers": ["BRITANNIA.NS", "NESTLEIND.NS"], "sector": "FMCG (input inflation)", "duration": "1–2 months", "move": "Margin squeeze"},
            {"tickers": ["INDIGO.NS"], "sector": "Airlines (fuel + consumer)", "duration": "2–4 weeks", "move": "Dual pressure"},
        ],
    },
}


@dataclass
class DetectedEvent:
    event_type: str
    label: str
    headline: str
    source: str
    matched_keyword: str


@dataclass
class StockImpact:
    ticker: str
    sector: str
    direction: str  # beneficiary | loser
    duration: str
    move_hint: str
    event_type: str
    headline: str
    price: float | None = None
    chg_1d: float | None = None
    chg_1mo: float | None = None
    score: float = 0.0


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _is_valid_headline(title: str) -> bool:
    t = title.lower().strip()
    if len(t) < 30:
        return False
    junk = (
        "britannica", "wikipedia", "world bank group", "all about natural",
        "causes, types", "what is ", "definition of", "international idea",
    )
    return not any(j in t for j in junk)


def _fetch_rss_titles(url: str, limit: int) -> list[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "arka-macro-events/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8", errors="replace")
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml_data)
        out = []
        for t in titles[1:]:
            clean = _clean_text(t)
            if _is_valid_headline(clean):
                out.append(clean)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _fetch_via_stock_project(limit: int) -> list[dict]:
    py = STOCK_PROJECT / ".venv/bin/python3"
    if not py.is_file():
        return []
    feeds_json = json.dumps({k: v for k, v in [
        ("Disasters", MACRO_NEWS_FEEDS[0][1]),
        ("Resources", MACRO_NEWS_FEEDS[1][1]),
        ("Geopolitics", MACRO_NEWS_FEEDS[2][1]),
    ]})
    code = (
        f"import json; feeds={feeds_json}; "
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


def fetch_macro_event_news(limit: int = 8) -> list[dict]:
    """Fetch headlines about disasters, resources, geopolitics."""
    seen: set[str] = set()
    items: list[dict] = []

    for item in _fetch_via_stock_project(limit * 2):
        title = _clean_text(item.get("title", ""))
        if not _is_valid_headline(title):
            continue
        key = title.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        items.append({"source": item.get("source", "Macro"), "title": title})
        if len(items) >= limit:
            return items

    for source, url in MACRO_NEWS_FEEDS:
        for title in _fetch_rss_titles(url, 4):
            key = title.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append({"source": source, "title": title})
            if len(items) >= limit:
                return items
    return items


def classify_headline(headline: str) -> list[DetectedEvent]:
    low = headline.lower()
    found: list[DetectedEvent] = []
    for event_type, spec in EVENT_PLAYBOOK.items():
        for kw in spec["keywords"]:
            if re.search(kw, low):
                found.append(DetectedEvent(
                    event_type=event_type,
                    label=event_type.replace("_", " ").title(),
                    headline=headline,
                    source="",
                    matched_keyword=kw,
                ))
                break
    return found


def detect_macro_events(news: list[dict]) -> list[DetectedEvent]:
    events: list[DetectedEvent] = []
    seen_types: set[str] = set()
    for item in news:
        title = item.get("title", "")
        for ev in classify_headline(title):
            ev.source = item.get("source", "")
            if ev.event_type not in seen_types:
                seen_types.add(ev.event_type)
                events.append(ev)
    return events


def _fetch_quote(ticker: str) -> dict | None:
    encoded = urllib.parse.quote(ticker, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1mo"
    req = urllib.request.Request(url, headers={"User-Agent": "arka-macro-events/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
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
        return {
            "price": latest,
            "chg_1d": round((latest - prev) / prev * 100, 2) if prev else 0.0,
            "chg_1mo": round((latest - first) / first * 100, 2) if first else 0.0,
        }
    except Exception:
        return None


def _impact_score(direction: str, chg_1d: float | None, chg_1mo: float | None) -> float:
    c1 = chg_1d or 0.0
    cm = chg_1mo or 0.0
    if direction == "beneficiary":
        return c1 * 2.0 + cm * 0.5 + 10.0
    return -(c1 * 2.0 + cm * 0.5) + 5.0


def build_event_impacts(events: list[DetectedEvent]) -> list[StockImpact]:
    impacts: list[StockImpact] = []
    seen: set[tuple[str, str, str]] = set()

    for ev in events:
        spec = EVENT_PLAYBOOK.get(ev.event_type, {})
        for side, direction in (("beneficiaries", "beneficiary"), ("losers", "loser")):
            for entry in spec.get(side, []):
                for ticker in entry["tickers"]:
                    key = (ticker, ev.event_type, direction)
                    if key in seen:
                        continue
                    seen.add(key)
                    q = _fetch_quote(ticker)
                    imp = StockImpact(
                        ticker=ticker,
                        sector=entry["sector"],
                        direction=direction,
                        duration=entry["duration"],
                        move_hint=entry["move"],
                        event_type=ev.event_type,
                        headline=ev.headline[:100],
                        price=q.get("price") if q else None,
                        chg_1d=q.get("chg_1d") if q else None,
                        chg_1mo=q.get("chg_1mo") if q else None,
                    )
                    imp.score = _impact_score(direction, imp.chg_1d, imp.chg_1mo)
                    impacts.append(imp)

    impacts.sort(key=lambda x: x.score, reverse=True)
    # One row per ticker — keep strongest score
    by_ticker: dict[str, StockImpact] = {}
    for imp in impacts:
        prev = by_ticker.get(imp.ticker)
        if prev is None or imp.score > prev.score:
            by_ticker[imp.ticker] = imp
    deduped = sorted(by_ticker.values(), key=lambda x: x.score, reverse=True)
    return deduped


def format_macro_event_report(news_limit: int = 8) -> tuple[str, list[str]]:
    """Build full macro event context block and source tags."""
    news = fetch_macro_event_news(limit=news_limit)
    events = detect_macro_events(news)
    sources = ["macro-news"]

    lines = ["## Macro & disaster event scan (live RSS)"]
    lines.append("")
    lines.append("### Top event headlines")
    if news:
        for i, item in enumerate(news[:8], 1):
            lines.append(f"{i}. [{item.get('source', 'News')}] {item['title']}")
    else:
        lines.append("(No macro headlines fetched.)")

    lines.append("")
    lines.append("### Detected event types")
    if events:
        for ev in events:
            lines.append(f"- **{ev.label}** (trigger: \"{ev.matched_keyword}\" in: {ev.headline[:90]}…)")
        sources.append("event-classify")
    else:
        lines.append("- No disaster/resource/geopolitical patterns matched in current headlines.")
        lines.append("- Baseline: monitor oil, monsoon, US-Iran/Middle East, Fed/rates, India elections/policy.")
        return "\n".join(lines), sources

    impacts = build_event_impacts(events)
    if impacts:
        sources.append("event-impact-prices")

    lines.append("")
    lines.append("### Predicted stock impacts (rule-based + live prices)")
    lines.append("")
    lines.append("| Priority | Ticker | Sector | Role | Typical duration | Move hint | 1d% | 1mo% |")
    lines.append("|----------|--------|--------|------|------------------|-----------|-----|------|")

    for i, imp in enumerate(impacts[:15], 1):
        role = "↑ Likely beneficiary" if imp.direction == "beneficiary" else "↓ Likely pressure"
        c1 = f"{imp.chg_1d:+.2f}" if imp.chg_1d is not None else "—"
        cm = f"{imp.chg_1mo:+.2f}" if imp.chg_1mo is not None else "—"
        lines.append(
            f"| {i} | {imp.ticker} | {imp.sector} | {role} | {imp.duration} | {imp.move_hint} | {c1} | {cm} |"
        )

    # Group by event with duration guidance
    lines.append("")
    lines.append("### Duration guide (how long moves typically last)")
    for ev in events:
        spec = EVENT_PLAYBOOK[ev.event_type]
        ben = spec.get("beneficiaries", [{}])[0]
        dur = ben.get("duration", "2–8 weeks")
        lines.append(f"- **{ev.label}**: active trade window usually **{dur}**; fade when headlines peak / relief arrives.")

    lines.append("")
    lines.append("### Watchlist rules")
    lines.append("- **Day 1–3**: headline shock, gaps, high volume — mostly sentiment.")
    lines.append("- **Week 1–2**: sector rotation; beneficiaries often peak here for disasters.")
    lines.append("- **Month 1–3**: rebuild/policy plays (cement, infra, defense) can extend; verify order news.")
    lines.append("- **Invalidation**: ceasefire/peace deal, rain recovery, OPEC surprise, gov subsidy caps.")

    top_up = [imp for imp in impacts if imp.direction == "beneficiary"][:3]
    if top_up:
        lines.append("")
        lines.append("### Top beneficiaries to research now")
        for imp in top_up:
            px = f" @ {imp.price:.2f}" if imp.price else ""
            lines.append(f"- **{imp.ticker}**{px} — {imp.sector}, hold window **{imp.duration}**, {imp.move_hint}")

    return "\n".join(lines), sources


def print_macro_event_terminal(news_limit: int = 8) -> None:
    from arka.stock.ui import banner, bullet, headline_item, note, pct, section, table, tag

    news = fetch_macro_event_news(limit=news_limit)
    events = detect_macro_events(news)
    banner("Macro & disaster scan", subtitle="Live RSS · sector impact · hold duration")

    section("Headlines")
    if news:
        for i, item in enumerate(news[:news_limit], 1):
            headline_item(i, item.get("source", "News"), item["title"])
    else:
        note("No macro headlines fetched.")

    section("Detected events")
    if not events:
        bullet("No disaster/resource/geopolitics patterns in current headlines.")
        bullet("Watch: oil, monsoon, Middle East, Fed/rates, India policy.")
        return

    for ev in events:
        bullet(f"{ev.label} — matched \"{ev.matched_keyword}\"")

    impacts = build_event_impacts(events)
    if not impacts:
        return

    section("Stock impact watchlist")
    rows = []
    for i, imp in enumerate(impacts[:12], 1):
        role = tag("BENEFICIARY", "good") if imp.direction == "beneficiary" else tag("PRESSURE", "bad")
        rows.append([
            str(i),
            imp.ticker,
            imp.sector[:18],
            role,
            imp.duration,
            pct(imp.chg_1d),
            pct(imp.chg_1mo),
        ])
    table(
        ["#", "Ticker", "Sector", "Role", "Window", "1d", "1mo"],
        rows,
        aligns=["r", "l", "l", "l", "l", "r", "r"],
    )

    section("Duration guide")
    for ev in events[:4]:
        spec = EVENT_PLAYBOOK[ev.event_type]
        ben = spec.get("beneficiaries", [{}])[0]
        dur = ben.get("duration", "2–8 weeks")
        bullet(f"{ev.label}: typical trade window {dur}")

    top = [imp for imp in impacts if imp.direction == "beneficiary"][:3]
    if top:
        section("Top beneficiaries to research")
        for imp in top:
            px = f" @ {imp.price:.2f}" if imp.price else ""
            bullet(f"{imp.ticker}{px} — {imp.sector} · {imp.move_hint}")


def is_macro_relevant_query(query: str) -> bool:
    low = query.lower()
    return bool(re.search(
        r"\b(disaster|earthquake|flood|cyclone|drought|oil|war|sanction|commodity|"
        r"natural resource|geopolit|conflict|pandemic|climate|energy crisis|"
        r"which stock|what stock|predict.*stock|increase|surge|rally)\b",
        low,
    ))


def main() -> int:
    import argparse
    import sys

    from arka.stock.ui import use_color, use_terminal_ui

    p = argparse.ArgumentParser(description="Macro event → stock impact scanner")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--plain", action="store_true", help="Disable colors (or set ARKA_STOCK_PLAIN=1)")
    args = p.parse_args()
    if args.plain:
        import os
        os.environ["ARKA_STOCK_PLAIN"] = "1"
    if use_terminal_ui():
        print_macro_event_terminal(news_limit=args.limit)
    else:
        report, _ = format_macro_event_report(news_limit=args.limit)
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
