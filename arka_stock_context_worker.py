#!/usr/bin/env python3
"""Gather plain-text market context from stock_analysis (run with project venv)."""

from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

from get_free_data import (  # noqa: E402
    DEFAULT_WATCHLIST,
    MAX_NEWS_PER_FEED,
    MAX_TOTAL_NEWS,
    NEWS_FEEDS,
    fetch_news,
    fetch_prices,
)
from policy_impact_scanner import fetch_policy_news  # noqa: E402


def _fmt_price(row: dict) -> str:
    if row.get("error"):
        return f"{row['ticker']}: unavailable"
    sym = "₹" if row.get("currency") == "INR" else "$" if row.get("currency") == "USD" else ""
    chg = row.get("chg_pct", 0.0)
    sign = "+" if chg >= 0 else ""
    return f"{row['ticker']}: {sym}{row['price']:,.2f} ({sign}{chg:.2f}%)"


def _ml_signal(ticker: str) -> str | None:
    try:
        from ai_trading_strategy import add_technical_indicators, fetch_data, train_and_predict

        df, resolved = fetch_data(ticker, "2y")
        df = add_technical_indicators(df)
        df_test, _ = train_and_predict(df)
        latest = df_test.iloc[-1]
        prob = float(latest["Prob_Up"])
        if prob > 0.55:
            signal = "BULLISH"
        elif prob < 0.45:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"
        return f"{resolved}: prob_up={prob:.1%} → {signal}"
    except Exception as exc:
        return f"{ticker}: ML signal unavailable ({exc})"


def gather(tickers: list[str], *, include_ml: bool = True, ml_limit: int = 2) -> str:
    if not tickers:
        tickers = DEFAULT_WATCHLIST[:12]

    sections: list[str] = []

    prices = fetch_prices(tickers)
    if prices:
        lines = [_fmt_price(r) for r in prices if not r.get("error")]
        if lines:
            sections.append("[Live prices]\n" + "\n".join(lines))

    news = fetch_news(NEWS_FEEDS, MAX_NEWS_PER_FEED, min(MAX_TOTAL_NEWS, 40))
    if news:
        headlines = [f"- [{n['source']}] {n['title']}" for n in news[:25]]
        sections.append("[Market news feeds]\n" + "\n".join(headlines))

    policy_lines: list[str] = []
    for ticker in tickers[:3]:
        base = ticker.replace(".NS", "").replace(".BO", "")
        items = fetch_policy_news(ticker)
        if items:
            policy_lines.append(f"{ticker} policy headlines:")
            for item in items[:4]:
                policy_lines.append(f"  - {item['title']}")
    if policy_lines:
        sections.append("[Policy & regulatory news]\n" + "\n".join(policy_lines))

    if include_ml:
        ml_lines: list[str] = []
        for ticker in tickers[:ml_limit]:
            line = _ml_signal(ticker)
            if line:
                ml_lines.append(line)
        if ml_lines:
            sections.append("[AI trading signals (Random Forest backtest model)]\n" + "\n".join(ml_lines))

    return "\n\n".join(sections)


def main() -> int:
    tickers = [t.strip().upper() for t in sys.argv[1:] if t.strip()]
    ml = "--no-ml" not in sys.argv
    if "--no-ml" in sys.argv:
        tickers = [t for t in tickers if t != "--no-ml"]
    text = gather(tickers, include_ml=ml)
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
