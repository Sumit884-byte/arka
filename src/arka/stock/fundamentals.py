#!/usr/bin/env python3
"""Stock fundamentals: debt/equity, ROE, P/E, margins, and peer quality comparison."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from arka.paths import load_env_file, stock_project_dir

    load_env_file()
except ImportError:
    stock_project_dir = lambda: Path(  # noqa: E731
        __import__("os").environ.get(
            "STOCK_PROJECT", Path.home() / "Projects/python/products/stock_analysis"
        )
    ).expanduser()

STOCK_PROJECT = stock_project_dir()

FUNDAMENTAL_FIELDS = (
    "debtToEquity",
    "returnOnEquity",
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "currentRatio",
    "quickRatio",
    "profitMargins",
    "operatingMargins",
    "revenueGrowth",
    "earningsGrowth",
    "dividendYield",
    "beta",
    "totalDebt",
    "totalCash",
    "marketCap",
    "enterpriseValue",
    "freeCashflow",
)

# Yahoo reports debtToEquity as percentage (e.g. 36.6 = 36.6%)
FIELD_LABELS = {
    "debtToEquity": "D/E %",
    "returnOnEquity": "ROE %",
    "trailingPE": "P/E",
    "forwardPE": "Fwd P/E",
    "priceToBook": "P/B",
    "currentRatio": "Curr ratio",
    "quickRatio": "Quick ratio",
    "profitMargins": "Profit margin %",
    "operatingMargins": "Op margin %",
    "revenueGrowth": "Rev growth %",
    "earningsGrowth": "EPS growth %",
    "dividendYield": "Div yield %",
    "beta": "Beta",
}


@dataclass
class FundamentalRow:
    ticker: str
    metrics: dict
    quality_score: float
    flags: list[str]


def _python_candidates() -> list[Path]:
    candidates: list[Path] = []
    for rel in (".venv/bin/python3", "venv/bin/python3"):
        p = STOCK_PROJECT / rel
        if p.is_file():
            candidates.append(p)
    candidates.append(Path(sys.executable))
    return candidates


def fetch_fundamentals_batch(tickers: list[str]) -> dict[str, dict]:
    """Fetch Yahoo Finance fundamentals (stock_analysis venv or current Python)."""
    if not tickers:
        return {}
    fields_json = json.dumps(list(FUNDAMENTAL_FIELDS))
    tickers_json = json.dumps([t.upper() for t in tickers])
    code = f"""
import json, yfinance as yf
tickers = {tickers_json}
fields = {fields_json}
out = {{}}
for t in tickers:
    try:
        info = yf.Ticker(t).info or {{}}
        out[t] = {{f: info.get(f) for f in fields}}
    except Exception:
        out[t] = {{}}
print(json.dumps(out))
"""
    for py in _python_candidates():
        try:
            proc = subprocess.run(
                [str(py), "-c", code],
                cwd=str(STOCK_PROJECT if STOCK_PROJECT.is_dir() else Path.cwd()),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                raw = json.loads(proc.stdout.strip())
                return {k: v for k, v in raw.items() if v}
        except Exception:
            continue
    return {}


def _fmt_pct(val: float | None, *, decimal_input: bool = True) -> str:
    if val is None:
        return "—"
    if decimal_input and abs(val) <= 1.5:
        return f"{val * 100:.1f}%"
    return f"{val:.1f}%"


def _fmt_num(val: float | None, decimals: int = 2) -> str:
    if val is None:
        return "—"
    if abs(val) >= 1_000_000_000_000:
        return f"{val / 1_000_000_000_000:.2f}T"
    if abs(val) >= 1_000_000_000:
        return f"{val / 1_000_000_000:.2f}B"
    if abs(val) >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    return f"{val:.{decimals}f}"


def _quality_score(metrics: dict) -> tuple[float, list[str]]:
    """Higher = healthier balance sheet + profitability (rule-based, not advice)."""
    score = 50.0
    flags: list[str] = []

    roe = metrics.get("returnOnEquity")
    if roe is not None:
        score += min(max(roe * 100, 0), 20)
        if roe > 0.18:
            flags.append("strong ROE")
        elif roe < 0.05:
            flags.append("weak ROE")

    de = metrics.get("debtToEquity")
    if de is not None:
        if de < 30:
            score += 15
            flags.append("low leverage")
        elif de < 80:
            score += 5
        elif de > 150:
            score -= 15
            flags.append("high debt")
        elif de > 100:
            score -= 8
            flags.append("elevated debt")

    cr = metrics.get("currentRatio")
    if cr is not None:
        if cr >= 1.5:
            score += 8
        elif cr < 1.0:
            score -= 10
            flags.append("liquidity risk")

    pe = metrics.get("trailingPE")
    if pe is not None:
        if 8 <= pe <= 28:
            score += 5
        elif pe > 45:
            score -= 5
            flags.append("rich valuation")

    pm = metrics.get("profitMargins")
    if pm is not None and pm > 0.15:
        score += 5

    rev_g = metrics.get("revenueGrowth")
    if rev_g is not None and rev_g > 0.1:
        score += 5
        flags.append("revenue growth")

    eg = metrics.get("earningsGrowth")
    if eg is not None and eg < -0.2:
        score -= 8
        flags.append("earnings decline")

    return round(max(0, min(100, score)), 1), flags


def build_fundamental_rows(tickers: list[str]) -> list[FundamentalRow]:
    data = fetch_fundamentals_batch(tickers)
    rows: list[FundamentalRow] = []
    for ticker in tickers:
        t = ticker.upper()
        metrics = data.get(t, {})
        if not metrics or not any(v is not None for v in metrics.values()):
            continue
        qs, flags = _quality_score(metrics)
        rows.append(FundamentalRow(ticker=t, metrics=metrics, quality_score=qs, flags=flags))
    rows.sort(key=lambda r: r.quality_score, reverse=True)
    return rows


def format_fundamentals_table(tickers: list[str], *, title: str = "") -> str:
    rows = build_fundamental_rows(tickers)
    if not rows:
        return "(Fundamentals unavailable — check stock_analysis venv and tickers.)"

    lines = []
    if title:
        lines.append(title)
        lines.append("")

    lines.extend([
        "| Rank | Ticker | D/E % | ROE % | P/E | P/B | Curr ratio | Profit % | Rev gr % | Quality | Notes |",
        "|------|--------|-------|-------|-----|-----|------------|----------|----------|---------|-------|",
    ])
    for i, row in enumerate(rows, 1):
        m = row.metrics
        de = _fmt_num(m.get("debtToEquity"), 1)
        roe = _fmt_pct(m.get("returnOnEquity"))
        pe = _fmt_num(m.get("trailingPE"), 1)
        pb = _fmt_num(m.get("priceToBook"), 2)
        cr = _fmt_num(m.get("currentRatio"), 2)
        pm = _fmt_pct(m.get("profitMargins"))
        rg = _fmt_pct(m.get("revenueGrowth"))
        notes = ", ".join(row.flags[:2]) if row.flags else "—"
        lines.append(
            f"| {i} | {row.ticker} | {de} | {roe} | {pe} | {pb} | {cr} | {pm} | {rg} | **{row.quality_score}** | {notes} |"
        )

    best = rows[0]
    worst = rows[-1]
    lines.extend([
        "",
        f"**Best fundamentals (quality score):** {best.ticker} ({best.quality_score}/100)",
        f"**Weakest fundamentals in set:** {worst.ticker} ({worst.quality_score}/100)",
        "",
        "**Reading guide:**",
        "- **D/E %** — lower generally = less leverage (Yahoo format; compare within same sector).",
        "- **ROE %** — return on equity; higher = more efficient use of shareholder capital.",
        "- **P/E** — price/earnings; compare vs sector median, not in isolation.",
        "- **Curr ratio** — current assets ÷ liabilities; below 1.0 = liquidity stress.",
        "- **Quality score** — rule-based blend of leverage, ROE, liquidity, growth (not a buy rating).",
    ])
    return "\n".join(lines)


def format_fundamentals_report(
    tickers: list[str] | None = None,
    query: str = "",
) -> tuple[str, list[str]]:
    """Full fundamentals section for predictions context."""
    from arka.stock.competition_funding import resolve_peer_groups

    tickers = tickers or []
    tradable = [t.upper() for t in tickers if t and not t.startswith("^")]
    groups = resolve_peer_groups(tickers, query)

    lines = ["## Fundamental analysis (Yahoo Finance, delayed)"]

    if tradable:
        lines.append("")
        lines.append(format_fundamentals_table(tradable, title="### Requested tickers — key ratios"))
    elif not groups:
        lines.append("")
        lines.append(
            format_fundamentals_table(
                ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS"],
                title="### Default watchlist — key ratios",
            )
        )

    for sector, peers in list(groups.items())[:3]:
        sector_tickers = [p for p in peers if not p.startswith("^")][:8]
        if not sector_tickers:
            continue
        if tradable and set(sector_tickers) <= set(tradable):
            continue
        lines.append("")
        lines.append(format_fundamentals_table(sector_tickers, title=f"### {sector} — peer set"))

    if len(tradable) == 1:
        t = tradable[0]
        data = fetch_fundamentals_batch([t]).get(t, {})
        if data:
            lines.append("")
            lines.append(f"### {t} — extended metrics")
            for key in FUNDAMENTAL_FIELDS:
                val = data.get(key)
                if val is None:
                    continue
                label = FIELD_LABELS.get(key, key)
                if key in {
                    "returnOnEquity", "profitMargins", "operatingMargins",
                    "revenueGrowth", "earningsGrowth", "dividendYield",
                }:
                    disp = _fmt_pct(val)
                elif key in {"totalDebt", "totalCash", "marketCap", "enterpriseValue", "freeCashflow"}:
                    disp = _fmt_num(val)
                else:
                    disp = _fmt_num(val, 2)
                lines.append(f"- **{label}:** {disp}")

    return "\n".join(lines), ["fundamentals-yahoo"]


def print_fundamentals_terminal(tickers: list[str]) -> None:
    from arka.stock.ui import banner, bullet, note, section, table, tag

    tradable = [t.upper() for t in tickers if t and not t.startswith("^")]
    rows_data = build_fundamental_rows(tradable or ["RELIANCE.NS", "TCS.NS", "INFY.NS"])
    banner("Fundamental analysis", subtitle="Yahoo Finance · delayed · rule-based quality score")

    if not rows_data:
        note("Fundamentals unavailable — check tickers and network.")
        return

    section("Key ratios")
    table_rows = []
    for i, row in enumerate(rows_data, 1):
        m = row.metrics
        flags = ", ".join(row.flags[:2]) if row.flags else "—"
        table_rows.append([
            str(i),
            row.ticker,
            _fmt_num(m.get("debtToEquity"), 1),
            _fmt_pct(m.get("returnOnEquity")),
            _fmt_num(m.get("trailingPE"), 1),
            _fmt_pct(m.get("profitMargins")),
            tag(f"{row.quality_score:.0f}", "good" if row.quality_score >= 70 else "warn" if row.quality_score >= 55 else "bad"),
            flags,
        ])
    table(
        ["#", "Ticker", "D/E%", "ROE", "P/E", "Margin", "Quality", "Notes"],
        table_rows,
        aligns=["r", "l", "r", "r", "r", "r", "c", "l"],
    )

    best, worst = rows_data[0], rows_data[-1]
    section("Summary")
    bullet(f"Best quality: {best.ticker} ({best.quality_score}/100)")
    bullet(f"Weakest in set: {worst.ticker} ({worst.quality_score}/100)")
    note("Quality score blends leverage, ROE, liquidity, growth — not a buy rating.")


def is_fundamentals_query(query: str) -> bool:
    low = query.lower()
    return bool(re.search(
        r"\b(debt.?to.?equity|d/e|leverage|balance sheet|fundamental|p/e|pe ratio|"
        r"roe|return on equity|book value|current ratio|profit margin|valuation|"
        r"financial ratio|financial health)\b",
        low,
    ))


def main() -> int:
    import argparse
    import sys

    from arka.stock.ui import use_terminal_ui

    p = argparse.ArgumentParser(description="Stock fundamentals comparison")
    p.add_argument("tickers", nargs="+", help="Ticker symbols")
    p.add_argument("--query", default="")
    p.add_argument("--plain", action="store_true")
    args = p.parse_args()
    if args.plain:
        import os
        os.environ["STOCK_PLAIN"] = "1"
    if use_terminal_ui():
        print_fundamentals_terminal(args.tickers)
    else:
        report, _ = format_fundamentals_report(args.tickers, args.query)
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
