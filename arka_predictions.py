#!/usr/bin/env python3
"""Arka predictions talent — opportunity analysis for antiques, stocks, and strategy."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

FISH_DIR = Path.home() / ".config" / "fish"
CACHE = Path.home() / ".cache" / "fish-agent"
HISTORY_FILE = CACHE / "predictions.json"
STOCK_PROJECT = Path(
    os.environ.get("ARKA_STOCK_PROJECT", Path.home() / "Projects/python/products/stock_analysis")
)
VENV_PY = FISH_DIR / "venv-arka" / "bin" / "python3"

DEFAULT_STOCKS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS",
    "AAPL", "MSFT", "NVDA", "GOOGL", "^NSEI", "^GSPC",
]

INDIA_WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "SBIN.NS", "WIPRO.NS", "ITC.NS", "TATASTEEL.NS", "NIFTYBEES.NS",
    "LIQUIDBEES.NS", "MON100.NS", "^NSEI",
]

AFFORDABLE_IN = [
    "NIFTYBEES.NS", "LIQUIDBEES.NS", "MON100.NS", "IDEA.NS", "YESBANK.NS",
    "TATASTEEL.NS", "SUZLON.NS", "IRFC.NS", "RELIANCE.NS", "ITC.NS",
]

AFFORDABLE_US = ["F", "INTC", "SNAP", "SOFI", "NIO", "PLUG", "AAPL", "BAC"]

INSTRUMENT_META: dict[str, dict] = {
    "LIQUIDBEES.NS": {"type": "Liquid ETF", "risk": 1},
    "NIFTYBEES.NS": {"type": "Index ETF", "risk": 3},
    "MON100.NS": {"type": "Global ETF", "risk": 4},
    "RELIANCE.NS": {"type": "Large-cap stock", "risk": 6},
    "TCS.NS": {"type": "Large-cap stock", "risk": 5},
    "HDFCBANK.NS": {"type": "Large-cap stock", "risk": 5},
    "INFY.NS": {"type": "Large-cap stock", "risk": 5},
    "ITC.NS": {"type": "Large-cap stock", "risk": 5},
    "TATASTEEL.NS": {"type": "Mid-cap stock", "risk": 7},
    "IDEA.NS": {"type": "Small-cap stock", "risk": 9},
    "YESBANK.NS": {"type": "Small-cap stock", "risk": 9},
    "SUZLON.NS": {"type": "Small-cap stock", "risk": 8},
    "IRFC.NS": {"type": "PSU stock", "risk": 6},
}

SYNTHETIC_IN: list[dict] = [
    {"name": "Liquid / overnight mutual fund", "type": "Debt MF", "risk": 1, "est_monthly_pct": 0.55},
    {"name": "Arbitrage mutual fund", "type": "Hybrid MF", "risk": 2, "est_monthly_pct": 0.48},
    {"name": "Ultra-short debt fund", "type": "Debt MF", "risk": 2, "est_monthly_pct": 0.50},
    {"name": "Bank FD (30–45 days)", "type": "Fixed deposit", "risk": 1, "est_monthly_pct": 0.52},
]

SYNTHETIC_US: list[dict] = [
    {"name": "High-yield savings / money market", "type": "Cash", "risk": 1, "est_monthly_pct": 0.35},
    {"name": "US T-bill (4-week)", "type": "Treasury", "risk": 1, "est_monthly_pct": 0.30},
]

INVEST_NEWS_FEEDS: list[tuple[str, str]] = [
    ("Markets India", "https://news.google.com/rss/search?q=NSE+BSE+stock+market+today&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Short-term invest", "https://news.google.com/rss/search?q=short+term+investment+India+mutual+fund+FD&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Global markets", "https://news.google.com/rss/search?q=global+stock+market&hl=en-US&gl=US&ceid=US:en"),
    ("Yahoo Finance", "https://finance.yahoo.com/rss/topfinstories"),
    ("Economic Times", "https://economictimes.indiatimes.com/markets/rss.cms"),
]

TICKER_STOPWORDS = frozenset({
    "I", "A", "THE", "AND", "FOR", "ALL", "AI", "AN", "TO", "IN", "ON", "AT", "OR",
    "IS", "IT", "AS", "BE", "BY", "DO", "GO", "HE", "IF", "ME", "MY", "NO", "OF",
    "SO", "UP", "US", "WE", "AM", "ARE", "CAN", "DAY", "GET", "HAD", "HAS", "HER",
    "HIM", "HIS", "HOW", "ITS", "MAY", "NEW", "NOT", "NOW", "OLD", "ONE", "OUR",
    "OUT", "OWN", "PUT", "RUN", "SAY", "SHE", "TOO", "TRY", "TWO", "USE", "WAS",
    "WAY", "WHO", "WHY", "WIN", "WON", "YET", "YOU", "ANY", "ASK", "BUY", "END",
    "FEW", "GOT", "LET", "MAN", "MEN", "NET", "OFF", "PAY", "PER", "PRO", "RAW",
    "SET", "SIT", "TOP", "VIA", "WAR", "WHERE", "WHEN", "WHAT", "WHICH", "WITH",
    "FROM", "INTO", "OVER", "SOME", "THAN", "THEM", "THEN", "THIS", "THAT", "THEY",
    "MAKE", "MADE", "MUCH", "MOST", "MORE", "MONTH", "WEEK", "YEAR", "DAYS", "TIME",
    "BEST", "GOOD", "HIGH", "LOW", "LONG", "SHORT", "FAST", "SLOW", "ONLY", "ALSO",
    "JUST", "LIKE", "NEED", "WANT", "GIVE", "TAKE", "FIND", "LOOK", "HELP", "WORK",
    "FUND", "CASH", "GOLD", "BOND", "DEBT", "LOAN", "BANK", "RATE", "RS", "INR",
    "USD", "EUR", "PROFIT", "LOSS", "GAIN", "RISK", "SAFE", "MONEY", "Rupees",
})

NEWS_FEEDS = {
    "markets": "https://news.google.com/rss/search?q=stock+market+opportunity&hl=en-IN&gl=IN&ceid=IN:en",
    "antiques": "https://news.google.com/rss/search?q=antique+auction+market+trends&hl=en-US&gl=US&ceid=US:en",
    "strategy": "https://news.google.com/rss/search?q=investment+strategy+outlook&hl=en-US&gl=US&ceid=US:en",
}


def _py() -> str:
    return str(VENV_PY if VENV_PY.is_file() else sys.executable)


def _load_env() -> None:
    env_path = FISH_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def _llm(system: str, user: str, temperature: float = 0.25) -> str:
    proc = subprocess.run(
        [
            _py(),
            str(FISH_DIR / "arka_llm.py"),
            "complete",
            "--system",
            system,
            "--user",
            user,
            "--temperature",
            str(temperature),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        return ""
    return re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", out.strip())


def is_investment_query(text: str) -> bool:
    low = text.lower()
    patterns = (
        r"where\s+(?:to|should\s+i)\s+invest",
        r"how\s+(?:to|can\s+i)\s+invest",
        r"\binvest(?:ment|ing)?\b",
        r"make\s+(?:a\s+)?profit",
        r"best\s+(?:place|option|way|stock|fund)\s+to",
        r"(?:₹|rs\.?\s*\d|\d+\s*(?:rupees|inr))",
        r"\d+\s*(?:k|thousand|lakh|lac)\b",
        r"\d+\s+for\s+\d+\s*(?:day|week|month)",
        r"(?:short|quick)\s+term\s+(?:gain|return|profit)",
    )
    return any(re.search(p, low) for p in patterns)


def parse_amount(text: str) -> tuple[float | None, str]:
    low = text.lower()
    currency = "INR"
    if re.search(r"\$|usd|dollar", low):
        currency = "USD"
    elif re.search(r"€|eur|euro", low):
        currency = "EUR"
    elif re.search(r"₹|rs\.?\b|inr\b|rupee", low):
        currency = "INR"

    m = re.search(
        r"(?:₹|rs\.?\s*|inr\s*)?([\d,]+(?:\.\d+)?)\s*(k|thousand|lakh|lac|crore|cr)?",
        text,
        re.I,
    )
    if not m:
        m = re.search(r"\b([\d,]+(?:\.\d+)?)\s*(k|thousand|lakh|lac|crore|cr)?\b", text, re.I)
    if not m:
        return None, currency

    amount = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    if suffix in {"k", "thousand"}:
        amount *= 1000
    elif suffix in {"lakh", "lac"}:
        amount *= 100_000
    elif suffix in {"crore", "cr"}:
        amount *= 10_000_000
    return amount, currency


def parse_horizon(text: str) -> str:
    m = re.search(r"(\d+)\s*(day|week|month|year)s?\b", text, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        plural = "s" if n != 1 else ""
        return f"{n} {unit}{plural}"
    m = re.search(r"(?:one|a)\s+(day|week|month|year)\b", text, re.I)
    if m:
        return f"1 {m.group(1)}"
    return ""


def detect_domain(text: str) -> str:
    low = text.lower()
    if is_investment_query(text):
        return "stocks"
    scores = {
        "antiques": len(re.findall(
            r"\b(antique|collectible|auction|vintage|numismatic|heirloom|art\s+deco|porcelain)\b", low
        )),
        "stocks": len(re.findall(
            r"\b(stock|share|equity|nifty|sensex|portfolio|ticker|market|nse|bse|dividend|"
            r"invest|profit|mutual\s+fund|etf|fd|sip)\b",
            low,
        )),
        "strategy": len(re.findall(
            r"\b(strategy|future|forecast|trend|opportunity|outlook|plan|roadmap|scenario)\b", low
        )),
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "all"
    return best


def extract_tickers(text: str) -> list[str]:
    tickers: list[str] = []
    for t in re.findall(r"\b(\^[A-Z]{2,10}|[A-Z]{2,12}(?:\.NS|\.BO))\b", text.upper()):
        if t not in tickers:
            tickers.append(t)
    if not tickers:
        for t in re.findall(r"\b[A-Z]{2,5}\b", text.upper()):
            if t in TICKER_STOPWORDS or t in tickers:
                continue
            tickers.append(t)
    return tickers[:12]


def _default_tickers_for_query(query: str, amount: float | None, currency: str) -> list[str]:
    explicit = extract_tickers(query)
    if explicit:
        return explicit
    if currency == "INR" or is_investment_query(query):
        return list(INDIA_WATCHLIST[:10])
    return list(DEFAULT_STOCKS[:8])


def fetch_yahoo_quote(symbol: str) -> dict | None:
    return fetch_yahoo_metrics(symbol)


def fetch_yahoo_metrics(symbol: str, range_: str = "1mo") -> dict | None:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range={range_}"
    req = urllib.request.Request(url, headers={"User-Agent": "arka-predictions/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return None
        meta = result[0].get("meta", {})
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [float(c) for c in closes if c is not None]
        if not closes:
            return None
        latest = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else latest
        chg_1d = ((latest - prev) / prev * 100) if prev else 0.0
        chg_5d = ((latest - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 else chg_1d
        chg_1mo = ((latest - closes[0]) / closes[0] * 100) if len(closes) >= 2 else chg_1d
        rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
        vol = statistics.stdev(rets) * math.sqrt(252) * 100 if len(rets) > 1 else 0.0
        return {
            "ticker": symbol,
            "price": latest,
            "change_pct": round(chg_1d, 2),
            "chg_1d": round(chg_1d, 2),
            "chg_5d": round(chg_5d, 2),
            "chg_1mo": round(chg_1mo, 2),
            "volatility": round(vol, 2),
            "currency": meta.get("currency", ""),
        }
    except Exception:
        return None


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _is_valid_headline(title: str) -> bool:
    t = title.lower().strip()
    if len(t) < 25:
        return False
    junk = ("google news", "yahoo finance", "moneycontrol", "economic times")
    return not any(t == j or t.startswith(j + " ") for j in junk)


def fetch_top_investment_news(limit: int = 5, currency: str = "INR") -> list[dict]:
    """Fetch top N unique market/investment headlines (stock_analysis RSS first)."""
    seen: set[str] = set()
    items: list[dict] = []

    def _add(item: dict) -> None:
        title = _clean_text(item.get("title", ""))
        if not _is_valid_headline(title):
            return
        key = title.lower()[:80]
        if key in seen:
            return
        seen.add(key)
        items.append({
            "source": item.get("source", "News"),
            "title": title,
            "summary": _clean_text(item.get("summary", ""))[:200],
        })

    for item in _fetch_top_news_via_stock_project(limit * 4):
        _add(item)
        if len(items) >= limit:
            return items[:limit]

    try:
        import feedparser
    except ImportError:
        for item in _fetch_top_news_rss_raw(limit * 3, currency):
            _add(item)
            if len(items) >= limit:
                break
        return items[:limit]

    feeds = INVEST_NEWS_FEEDS if currency == "INR" else INVEST_NEWS_FEEDS[2:]
    for source, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                _add({"source": source, "title": entry.get("title", ""), "summary": entry.get("summary", "")})
                if len(items) >= limit:
                    return items[:limit]
        except Exception:
            continue
    return items[:limit]


def _fetch_top_news_rss_raw(limit: int, currency: str) -> list[dict]:
    """Minimal RSS fetch without feedparser."""
    url = INVEST_NEWS_FEEDS[0][1] if currency == "INR" else INVEST_NEWS_FEEDS[2][1]
    source = INVEST_NEWS_FEEDS[0][0] if currency == "INR" else INVEST_NEWS_FEEDS[2][0]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "arka-predictions/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8", errors="replace")
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml_data)
        items = []
        for title in titles[1:]:  # skip feed title
            clean = _clean_text(title)
            if _is_valid_headline(clean):
                items.append({"source": source, "title": clean, "summary": ""})
            if len(items) >= limit:
                break
        return items
    except Exception:
        return []


def _fetch_top_news_via_stock_project(limit: int) -> list[dict]:
    """Fallback: pull headlines via stock_analysis get_free_data."""
    script = STOCK_PROJECT / "get_free_data.py"
    py = STOCK_PROJECT / ".venv/bin/python3"
    if not script.is_file() or not py.is_file():
        return []
    code = (
        "import json,re; from get_free_data import fetch_news, NEWS_FEEDS; "
        f"n=fetch_news(NEWS_FEEDS, 3, {limit * 3}); "
        "def clean(t): return re.sub(r'\\s+',' ',re.sub(r'<[^>]+>','',t or '')).strip(); "
        "print(json.dumps([{'source':x['source'],'title':clean(x['title']),"
        "'summary':clean(x.get('summary',''))} "
        f"for x in n[:{limit}]]))"
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


def horizon_to_days(horizon: str) -> int:
    if not horizon:
        return 30
    m = re.search(r"(\d+)\s*(day|week|month|year)s?\b", horizon, re.I)
    if not m:
        return 30
    n, unit = int(m.group(1)), m.group(2).lower()
    mult = {"day": 1, "week": 7, "month": 30, "year": 365}.get(unit, 30)
    return n * mult


def _score_investment_option(opt: dict, horizon_days: int) -> float:
    risk = float(opt.get("risk", 5))
    vol = float(opt.get("volatility", opt.get("est_volatility", 3)))
    momentum = float(opt.get("chg_1mo", opt.get("est_monthly_pct", 0)))
    fit = float(opt.get("fit_pct", 95))
    chg_5d = float(opt.get("chg_5d", momentum))

    safety = max(0.0, 100.0 - vol * 2.5 - risk * 7.0)
    mom = min(100.0, max(0.0, 50.0 + momentum * 8.0 + chg_5d * 2.0))
    fit_score = min(100.0, fit)

    if horizon_days <= 35:
        return 0.55 * safety + 0.20 * mom + 0.25 * fit_score
    if horizon_days <= 180:
        return 0.35 * safety + 0.40 * mom + 0.25 * fit_score
    return 0.20 * safety + 0.55 * mom + 0.25 * fit_score


def compare_and_rank_investments(
    amount: float,
    currency: str,
    horizon: str = "1 month",
) -> str:
    """Fetch live data for affordable instruments, score them, return ranked comparison."""
    horizon_days = horizon_to_days(horizon)
    sym = "₹" if currency == "INR" else "$" if currency == "USD" else ""
    candidates = AFFORDABLE_IN if currency == "INR" else AFFORDABLE_US
    options: list[dict] = []

    for ticker in candidates:
        row = fetch_yahoo_metrics(ticker)
        if not row or not row.get("price"):
            continue
        price = float(row["price"])
        if price > amount:
            continue
        shares = int(amount // price)
        if shares < 1:
            continue
        deployed = shares * price
        meta = INSTRUMENT_META.get(ticker, {"type": "Stock/ETF", "risk": 6})
        options.append({
            "name": ticker,
            "type": meta["type"],
            "risk": meta["risk"],
            "price": price,
            "shares": shares,
            "deployed": deployed,
            "fit_pct": (deployed / amount) * 100,
            "chg_1d": row["chg_1d"],
            "chg_5d": row["chg_5d"],
            "chg_1mo": row["chg_1mo"],
            "volatility": row["volatility"],
            "currency": row["currency"],
            "live": True,
        })

    synth = SYNTHETIC_IN if currency == "INR" else SYNTHETIC_US
    for s in synth:
        options.append({
            "name": s["name"],
            "type": s["type"],
            "risk": s["risk"],
            "price": None,
            "shares": None,
            "deployed": amount,
            "fit_pct": 100.0,
            "chg_1d": 0.0,
            "chg_5d": 0.0,
            "chg_1mo": s["est_monthly_pct"],
            "volatility": s["risk"] * 1.5,
            "currency": currency,
            "live": False,
        })

    for opt in options:
        opt["score"] = round(_score_investment_option(opt, horizon_days), 1)

    options.sort(key=lambda x: x["score"], reverse=True)

    lines = [
        f"Data-driven comparison for {sym}{amount:,.0f} {currency} over {horizon} ({horizon_days} days):",
        "",
        "| Rank | Option | Type | 1d% | 5d% | 1mo% | Vol% | Risk | Score |",
        "|------|--------|------|-----|-----|------|------|------|-------|",
    ]
    for i, opt in enumerate(options[:10], 1):
        lines.append(
            f"| {i} | {opt['name']} | {opt['type']} | {opt['chg_1d']:+.2f} | {opt['chg_5d']:+.2f} | "
            f"{opt['chg_1mo']:+.2f} | {opt['volatility']:.1f} | {opt['risk']}/10 | **{opt['score']}** |"
        )

    if options:
        best = options[0]
        lines.extend([
            "",
            f"**Best match (data score): {best['name']}** — {best['type']}, score {best['score']}/100",
        ])
        if best.get("live") and best.get("shares"):
            lines.append(
                f"  → Buy up to {best['shares']} unit(s) @ {best['price']:,.2f} "
                f"≈ {sym}{best['deployed']:,.0f} deployed"
            )
        elif not best.get("live"):
            lines.append(
                f"  → Est. return ~{best['chg_1mo']:+.2f}%/month (indicative, not guaranteed)"
            )
        if len(options) > 1:
            runner = options[1]
            lines.append(
                f"**Runner-up: {runner['name']}** (score {runner['score']}) — "
                f"{'tradeable now' if runner.get('live') else 'via MF/FD platform'}"
            )
        lines.extend([
            "",
            "Score weights for this horizon: "
            + ("safety-heavy (short-term)" if horizon_days <= 35 else "momentum-heavy (longer horizon)"),
            "Lower volatility + lower risk rank higher for ≤1 month; past 1mo% does NOT predict next month.",
        ])
    else:
        lines.append("(No tradeable instruments found in scan — use synthetic MF/FD options above.)")

    live_tickers = [o["name"] for o in options if o.get("live")][:8]
    if live_tickers:
        try:
            from arka_stock_fundamentals import format_fundamentals_table
            lines.append("")
            lines.append(format_fundamentals_table(
                live_tickers, title="Fundamental ratios for tradeable options (D/E, ROE, P/E):"
            ))
        except Exception:
            pass

    return "\n".join(lines)


def format_top_news(news: list[dict]) -> str:
    if not news:
        return "(No live news fetched.)"
    lines = ["Top headlines affecting markets & short-term investments:"]
    for i, item in enumerate(news, 1):
        title = _clean_text(item.get("title", ""))
        lines.append(f"{i}. [{item.get('source', 'News')}] {title}")
        summary = _clean_text(item.get("summary", ""))
        if summary and not summary.startswith("http") and len(summary) > 20:
            lines.append(f"   {summary[:180]}{'…' if len(summary) > 180 else ''}")
    return "\n".join(lines)


def fetch_stock_snapshot(tickers: list[str]) -> str:
    lines = ["Live price snapshot (Yahoo Finance, delayed):"]
    for sym in tickers:
        row = fetch_yahoo_quote(sym)
        if row:
            lines.append(
                f"  {row['ticker']}: {row['price']} {row['currency']} ({row['change_pct']:+.2f}% 1d)"
            )
        else:
            lines.append(f"  {sym}: unavailable")
    return "\n".join(lines)


def _investment_system_prompt(amount: float | None, currency: str, horizon: str) -> str:
    cap = f"{currency} {amount:,.0f}" if amount else "unspecified amount"
    hz = horizon or "unspecified"
    return (
        "You are Arka Predictions — investment research assistant (NOT a SEBI-registered advisor).\n"
        "The user wants practical allocation ideas for a specific amount and time horizon.\n"
        "Rules:\n"
        "- Use ONLY provided market data and frameworks; flag when you lack live rates.\n"
        "- NEVER promise or guarantee profit. Short horizons (≤1 month) rarely yield safe profit.\n"
        "- Give tiered options: (1) capital-preservation, (2) moderate, (3) aggressive/speculative.\n"
        f"- Anchor every suggestion to their capital ({cap}) and horizon ({hz}).\n"
        "- For small amounts (≤₹10k / ≤$500): mention brokerage, taxes (STT/LTCG/STCG India), and minimum ticket sizes.\n"
        "- State realistic return RANGES (e.g. liquid fund ~0.4–0.6%/month pre-tax), not certainties.\n"
        "- If they ask to 'make profit' quickly, explain why that pushes toward gambling-level risk.\n"
        "- **Primary sources:** use [Top 5 market news] for macro context and [Data-driven comparison ranking] "
        "for the ranked recommendation — cite rank #1 and runner-up by name and score.\n"
        "- Cross-check news sentiment with comparison table (e.g. market rally → ETFs vs liquid funds).\n"
        "- **Macro/disaster section:** use [Macro event intelligence] to name event-driven stock picks, "
        "expected direction, and **how long** to hold (cite duration from the table).\n"
        "- **Competition & funding:** use [Competition & funding intelligence] for peer leaders/laggards, "
        "recent VC/IPO deals, and which listed stocks benefit from startup funding themes.\n"
        "- **Fundamentals:** use [Fundamental ratios] for debt/equity, ROE, P/E, margins — prefer lower D/E "
        "for short-term safety unless high-growth thesis; cite quality scores.\n"
        "- **Emotion/crowd:** use [Market emotion & crowd behavior] — cite net emotion sum, "
        "Fear & Greed index, and 'who will do what' table (retail, FIIs, traders).\n"
        "Output markdown:\n"
        "## Direct answer — name the #1 ranked option and why (from comparison table)\n"
        "## Top 5 news impact — how today's headlines affect the choice\n"
        "## Event-driven opportunities — stocks likely to rise/fall, with hold duration (from macro scan)\n"
        "## Competition & funding — peer leaders, recent deals, indirect listed beneficiaries\n"
        "## Crowd emotion — net sentiment sum, who will buy/sell, sector tilt from mood\n"
        "## Ranked comparison summary (safe → risky, reference the data table)\n"
        "## Costs & gotchas (tax, fees, lock-in, exit load)\n"
        "## Risks & what could go wrong\n"
        "## Step-by-step next actions (accounts to open, what to verify)\n"
        "## Confidence & realistic outcome\n"
    )


def _general_system_prompt() -> str:
    return (
        "You are Arka Predictions — an analytical talent that surfaces OPPORTUNITIES, not certainties.\n"
        "Rules:\n"
        "- Base analysis ONLY on provided context; flag gaps when data is thin.\n"
        "- Always include risks, invalidation signals, and what would change your view.\n"
        "- Never guarantee returns; this is research/education, NOT financial or investment advice.\n"
        "- Be specific: names, sectors, categories, time horizons, and actionable next steps.\n"
        "- When [Macro event intelligence] is present: prioritize disaster/resource/geopolitical catalysts, "
        "list beneficiaries with **hold duration** (days/weeks/months), and state invalidation triggers.\n"
        "- When [Market emotion & crowd behavior] is present: report **net emotion sum**, dominant mood, "
        "and forecast what retail/FIIs/traders likely do next with time windows.\n"
        "- When [Competition & funding intelligence] is present: name peer group **leader vs laggard**, "
        "cite recent funding rounds in the sector, and map startup deals to listed supply-chain winners.\n"
        "Output markdown with sections:\n"
        "## Executive summary (3-5 bullets)\n"
        "## Event-driven stock map (what rises/falls, for how long)\n"
        "## Competition & funding signals (peers, VC/IPO, listed beneficiaries)\n"
        "## Top opportunities (ranked, with why now)\n"
        "## Risks & what could go wrong\n"
        "## Watchlist (items to monitor weekly)\n"
        "## Suggested next actions (concrete, low-cost research steps)\n"
        "## Confidence & time horizon\n"
    )


def fetch_rss_headlines(feed_url: str, limit: int = 8) -> list[str]:
    try:
        import feedparser
    except ImportError:
        return []
    try:
        feed = feedparser.parse(feed_url)
        out = []
        for entry in feed.entries[:limit]:
            title = (entry.get("title") or "").strip()
            if title:
                out.append(title)
        return out
    except Exception:
        return []


def fetch_web_context(query: str, domain: str) -> str:
    try:
        from arka_chat import scrape_search_results, snippet_lookup
    except ImportError:
        return ""
    search_q = query
    if domain == "antiques":
        search_q = f"antique collectibles market opportunities auction trends {query}"
    elif domain == "stocks":
        search_q = f"stock market opportunities sectors to watch {query}"
    elif domain == "strategy":
        search_q = f"investment strategy outlook opportunities {query}"
    snip = snippet_lookup(search_q)
    web = scrape_search_results(search_q, min_words=250, hard_limit=5)
    parts = []
    if snip:
        parts.append(snip)
    if web:
        parts.append(web[:6000])
    return "\n\n".join(parts)


def _stock_project_context(tickers: list[str], *, deep: bool) -> str:
    if not STOCK_PROJECT.is_dir():
        return ""
    try:
        sys.path.insert(0, str(FISH_DIR))
        from arka_stock_bridge import gather_context

        return gather_context(tickers or None, include_ml=deep)[:8000]
    except Exception:
        return ""


def gather_context(
    query: str,
    domain: str,
    *,
    deep: bool,
    amount: float | None = None,
    currency: str = "INR",
    horizon: str = "",
) -> tuple[str, list[str]]:
    sources: list[str] = []
    blocks: list[str] = []
    invest = is_investment_query(query)
    hz = horizon or parse_horizon(query) or "1 month"

    if domain in {"stocks", "all"} or invest:
        tickers = _default_tickers_for_query(query, amount, currency)
        snap = fetch_stock_snapshot(tickers)
        blocks.append(f"[Market data]\n{snap}")
        sources.append("yahoo")

        if invest:
            top_news = fetch_top_investment_news(limit=5, currency=currency)
            blocks.append(f"[Top 5 market news]\n{format_top_news(top_news)}")
            sources.append("news-top5")

            cap = amount if amount else (3000.0 if currency == "INR" else 500.0)
            comparison = compare_and_rank_investments(cap, currency, hz)
            blocks.append(f"[Data-driven comparison ranking]\n{comparison}")
            sources.append("comparison-rank")

        headlines = fetch_rss_headlines(NEWS_FEEDS["markets"], limit=5 if invest else 10)
        if headlines and not invest:
            blocks.append("[Market headlines]\n" + "\n".join(f"- {h}" for h in headlines))
            sources.append("rss-markets")

        use_ml = deep or invest
        proj = _stock_project_context(tickers, deep=use_ml)
        if proj:
            blocks.append(f"[Stock analysis project ({STOCK_PROJECT.name})]\n{proj[:6000]}")
            sources.append("stock_analysis")

        try:
            from arka_macro_events import format_macro_event_report, is_macro_relevant_query

            if domain in {"stocks", "all"} or invest or is_macro_relevant_query(query):
                macro_report, macro_sources = format_macro_event_report(news_limit=8)
                blocks.append(f"[Macro event intelligence]\n{macro_report}")
                sources.extend(macro_sources)
        except Exception:
            pass

        try:
            from arka_competition_funding import (
                format_competition_funding_report,
                is_competition_funding_query,
            )

            if domain in {"stocks", "all", "strategy"} or invest or is_competition_funding_query(query):
                cf_report, cf_sources = format_competition_funding_report(
                    tickers, query, funding_limit=8, competition_limit=5
                )
                blocks.append(f"[Competition & funding intelligence]\n{cf_report}")
                sources.extend(cf_sources)
        except Exception:
            pass

        try:
            from arka_stock_fundamentals import format_fundamentals_report, is_fundamentals_query

            if domain in {"stocks", "all"} or invest or is_fundamentals_query(query):
                fund_report, fund_sources = format_fundamentals_report(tickers, query)
                blocks.append(f"[Fundamental ratios]\n{fund_report}")
                sources.extend(fund_sources)
        except Exception:
            pass

        try:
            from arka_market_emotion import format_emotion_report, is_emotion_query

            if domain in {"stocks", "all", "strategy"} or invest or is_emotion_query(query):
                emo_report, emo_sources = format_emotion_report(news_limit=20)
                blocks.append(f"[Market emotion & crowd behavior]\n{emo_report}")
                sources.extend(emo_sources)
        except Exception:
            pass

    if domain in {"antiques", "all"}:
        headlines = fetch_rss_headlines(NEWS_FEEDS["antiques"], limit=10)
        if headlines:
            blocks.append("[Antiques & auction headlines]\n" + "\n".join(f"- {h}" for h in headlines))
            sources.append("rss-antiques")

    if domain in {"strategy", "all"}:
        headlines = fetch_rss_headlines(NEWS_FEEDS["strategy"], limit=8)
        if headlines:
            blocks.append("[Strategy & macro headlines]\n" + "\n".join(f"- {h}" for h in headlines))
            sources.append("rss-strategy")

    mem = ""
    try:
        from arka_talents import memory_semantic_context

        mem = memory_semantic_context(query, limit_chars=2000)
        if mem:
            blocks.append(f"[Your memory]\n{mem}")
            sources.append("memory")
    except Exception:
        pass

    if deep or domain == "all" or invest:
        web_domain = "stocks" if invest else (domain if domain != "all" else "strategy")
        web_q = query
        if invest:
            web_q = f"short term investment options India {query} liquid fund FD ETF 2025"
        web = fetch_web_context(web_q, web_domain)
        if web.strip():
            blocks.append(f"[Web research]\n{web[:8000]}")
            sources.append("web")

    return "\n\n---\n\n".join(blocks), sources


def run_prediction(
    query: str,
    *,
    domain: str = "auto",
    deep: bool = False,
    horizon: str = "3-6 months",
) -> str:
    query = query.strip()
    if not query:
        return "Provide a topic, e.g. 'antique silver opportunities' or 'RELIANCE.NS and tech stocks'."

    invest = is_investment_query(query)
    amount, currency = parse_amount(query)
    parsed_horizon = parse_horizon(query)
    if parsed_horizon:
        horizon = parsed_horizon

    if domain == "auto":
        domain = detect_domain(query)

    if invest and not deep:
        deep = True  # investment questions need web + stock project context

    context, sources = gather_context(
        query, domain, deep=deep, amount=amount, currency=currency, horizon=horizon
    )
    today = datetime.now().strftime("%A, %d %B %Y")

    domain_label = {
        "antiques": "Antiques & Collectibles",
        "stocks": "Stocks & Markets",
        "strategy": "Future Strategy",
        "all": "Multi-domain (Antiques + Stocks + Strategy)",
    }.get(domain, domain.title())
    if invest:
        domain_label = "Investment advisory (Stocks & short-term instruments)"

    system = (
        _investment_system_prompt(amount, currency, horizon)
        if invest
        else _general_system_prompt()
    )

    cap_line = ""
    if amount:
        sym = "₹" if currency == "INR" else "$" if currency == "USD" else ""
        cap_line = f"Parsed capital: {sym}{amount:,.0f} {currency}\n"

    user = (
        f"Date: {today}\n"
        f"Domain: {domain_label}\n"
        f"Horizon: {horizon}\n"
        f"{cap_line}"
        f"User question: {query}\n\n"
        f"Context:\n{context if context else '(Limited live data — use general frameworks and clearly state uncertainty)'}"
    )

    answer = _llm(system, user, temperature=0.3)
    if not answer:
        answer = "Could not generate predictions — check GEMINI_API_KEY, GROQ_API_KEY, or ollama."

    disclaimer = (
        "\n\n---\n"
        "⚠ **Not financial, legal, or investment advice.** "
        "Predictions are probabilistic research summaries. Verify with primary sources before acting."
    )
    full = answer + disclaimer

    _save_history(query, domain, horizon, sources, answer)
    return full


def _save_history(query: str, domain: str, horizon: str, sources: list[str], answer: str) -> None:
    items = []
    if HISTORY_FILE.is_file():
        try:
            items = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            items = []
    if not isinstance(items, list):
        items = []
    items.append({
        "when": datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "domain": domain,
        "horizon": horizon,
        "sources": sources,
        "preview": answer[:400],
    })
    CACHE.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(items[-50:], indent=2, ensure_ascii=False), encoding="utf-8")


def list_history(limit: int = 10) -> None:
    if not HISTORY_FILE.is_file():
        print("No prediction history yet.")
        return
    items = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items:
        print("No prediction history yet.")
        return
    print("━━━ Recent predictions ━━━")
    for row in items[-limit:]:
        print(f"\n[{row.get('when')}] ({row.get('domain')}) {row.get('query', '')[:80]}")
        print(f"  sources: {', '.join(row.get('sources') or [])}")
        prev = (row.get("preview") or "").replace("\n", " ")[:120]
        if prev:
            print(f"  → {prev}...")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Arka predictions talent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="Generate opportunity predictions")
    p.add_argument("query", nargs="+")
    p.add_argument("--domain", "-d", default="auto", choices=["auto", "antiques", "stocks", "strategy", "all"])
    p.add_argument("--deep", action="store_true", help="Extra web research")
    p.add_argument("--horizon", default=os.environ.get("ARKA_PREDICT_HORIZON", "3-6 months"))

    p = sub.add_parser("history", help="List recent predictions")
    p.add_argument("--limit", "-n", type=int, default=10)

    p = sub.add_parser("compare", help="Top 5 news + ranked investment comparison (no LLM)")
    p.add_argument("amount", type=float, nargs="?", default=3000)
    p.add_argument("--horizon", default="1 month")
    p.add_argument("--currency", default="INR", choices=["INR", "USD"])

    args = parser.parse_args()

    if args.cmd == "run":
        query = " ".join(args.query)
        domain = detect_domain(query) if args.domain == "auto" else args.domain
        label = {"antiques": "Antiques", "stocks": "Stocks", "strategy": "Strategy", "all": "All domains"}.get(
            domain, domain
        )
        print(f"━━━ Predictions ({label}) ━━━", file=sys.stderr)
        if args.deep:
            print("  Deep research enabled …", file=sys.stderr)
        result = run_prediction(query, domain=domain, deep=args.deep, horizon=args.horizon)
        print(result)
        return 0

    if args.cmd == "history":
        list_history(args.limit)
        return 0

    if args.cmd == "compare":
        print("━━━ Top 5 market news ━━━")
        print(format_top_news(fetch_top_investment_news(5, args.currency)))
        print()
        print("━━━ Macro events → stock impacts ━━━")
        try:
            from arka_macro_events import format_macro_event_report
            print(format_macro_event_report(news_limit=8)[0])
        except Exception as exc:
            print(f"(Macro scan unavailable: {exc})")
        print()
        try:
            from arka_competition_funding import format_competition_funding_report
            print(format_competition_funding_report([], "", funding_limit=8)[0])
        except Exception as exc:
            print(f"(Competition/funding scan unavailable: {exc})")
        print()
        try:
            from arka_market_emotion import format_emotion_report
            print(format_emotion_report(news_limit=15)[0])
        except Exception as exc:
            print(f"(Emotion scan unavailable: {exc})")
        print()
        print("━━━ Investment comparison ━━━")
        print(compare_and_rank_investments(args.amount, args.currency, args.horizon))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
