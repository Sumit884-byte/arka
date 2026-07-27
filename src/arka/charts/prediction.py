#!/usr/bin/env python3
"""Stock price prediction charts — historical series plus forecast overlay."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

FORECAST_COLOR = "#f97316"
HIST_COLOR = "#2563eb"
BAND_ALPHA = 0.18
SIGNAL_BULL = "#16a34a"
SIGNAL_BEAR = "#dc2626"
SIGNAL_NEUT = "#64748b"

_EXCHANGE_TICKER = re.compile(
    r"\b([A-Z][A-Z0-9&.-]{0,20}\.(?:NS|BO|L|HK|KS|TO|AX|LON|SW|PA|DE|MI))\b",
    re.I,
)
_PREDICTION_CHART = re.compile(
    r"(?i)"
    r"(?:predict(?:ion|ed)?|forecast(?:ed)?)\s+(?:chart|graph|plot|visuali[sz]e)"
    r"|(?:chart|graph|plot)\s+(?:predict(?:ion|ed)?|forecast)"
    r"|(?:predict|forecast)\s+(?:the\s+)?(?:price|stock|movement|trend|path|trajectory)"
    r"|(?:price|stock)\s+(?:predict(?:ion|ed)?|forecast)"
)
_PREDICT_TICKER = re.compile(
    r"(?:predict|forecast)\s+(?:\$?[A-Z][A-Z0-9.-]{0,11})\b"
)


@dataclass
class ForecastSeries:
    label: str
    hist_dates: list[datetime]
    hist_values: list[float]
    forecast_dates: list[datetime]
    forecast_values: list[float]
    band_low: list[float]
    band_high: list[float]
    prob_up: float
    signal: str
    method: str
    currency: str = ""


def parse_forecast_days(text: str, default: int = 30) -> int:
    low = text.lower()
    m = re.search(r"(\d+)\s*(day|week|month|year)s?\b", low)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        mult = {"day": 1, "week": 7, "month": 30, "year": 365}.get(unit, 30)
        return max(1, min(n * mult, 365))
    if re.search(r"\b(?:next\s+)?week\b", low):
        return 7
    if re.search(r"\b(?:next\s+)?month\b", low):
        return 30
    if re.search(r"\b(?:next\s+)?quarter\b", low):
        return 90
    return default


def wants_prediction_chart(text: str) -> bool:
    if not text.strip():
        return False
    if _PREDICTION_CHART.search(text):
        return True
    if _PREDICT_TICKER.search(text):
        return True
    if re.search(r"(?i)\b(?:predict|prediction|forecast)\b", text) and re.search(
        r"(?i)\b(?:chart|graph|plot|visuali[sz]e)\b", text
    ):
        return True
    tickers = extract_prediction_tickers(text)
    if tickers and re.search(r"(?i)\b(?:predict(?:ion|ed)?|forecast(?:ed)?)\b", text):
        return True
    return False


def extract_prediction_tickers(text: str) -> list[str]:
    from arka.charts.plot import COMPANY_TICKERS, extract_tickers

    found: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        sym = sym.strip().upper()
        if not sym or sym in seen:
            return
        seen.add(sym)
        found.append(sym)

    for m in _EXCHANGE_TICKER.finditer(text):
        add(m.group(1))
    for m in re.finditer(r"\$([A-Za-z][A-Za-z0-9.-]{0,11})", text):
        add(m.group(1))
    for sym in extract_tickers(text):
        if sym not in seen:
            add(sym)
    lower = text.lower()
    for name, sym in COMPANY_TICKERS.items():
        if re.search(rf"\b{re.escape(name)}\b", lower):
            add(sym)
    return found[:3]


def _momentum_signal(values: list[float]) -> tuple[float, str]:
    if len(values) < 10:
        return 0.5, "NEUTRAL"
    window = min(20, len(values) - 1)
    base = values[-window - 1]
    if base <= 0:
        return 0.5, "NEUTRAL"
    chg = (values[-1] - base) / base
    prob = 0.5 + max(-0.45, min(0.45, chg * 2.5))
    if prob > 0.55:
        return prob, "BULLISH"
    if prob < 0.45:
        return prob, "BEARISH"
    return prob, "NEUTRAL"


def _linear_forecast(
    dates: list[datetime],
    values: list[float],
    horizon_days: int,
) -> tuple[list[datetime], list[float], list[float], list[float], str]:
    import numpy as np

    lookback = min(60, len(values))
    y = np.asarray(values[-lookback:], dtype=float)
    x = np.arange(lookback, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    residuals = y - (slope * x + intercept)
    std = float(np.std(residuals)) if len(residuals) > 2 else float(np.std(y) * 0.05)

    last = dates[-1]
    f_dates: list[datetime] = []
    f_vals: list[float] = []
    band_lo: list[float] = []
    band_hi: list[float] = []
    for step in range(1, horizon_days + 1):
        f_dates.append(last + timedelta(days=step))
        pred = float(slope * (lookback - 1 + step) + intercept)
        f_vals.append(pred)
        spread = std * (1.0 + 0.15 * step)
        band_lo.append(pred - spread)
        band_hi.append(pred + spread)

    direction = "up" if slope > 0 else "down" if slope < 0 else "flat"
    method = f"linear trend ({lookback}d, {direction})"
    return f_dates, f_vals, band_lo, band_hi, method


def _try_ml_prob(ticker: str) -> float | None:
    try:
        from arka.paths import stock_project_dir

        proj = stock_project_dir()
        if not proj.is_dir():
            return None
        import sys

        if str(proj) not in sys.path:
            sys.path.insert(0, str(proj))
        from ai_trading_strategy import add_technical_indicators, fetch_data, train_and_predict

        df, _ = fetch_data(ticker, "2y")
        df = add_technical_indicators(df)
        df_test, _ = train_and_predict(df)
        return float(df_test.iloc[-1]["Prob_Up"])
    except Exception:
        return None


def build_forecast(
    symbol: str,
    *,
    history_range: str = "1y",
    horizon_days: int = 30,
) -> ForecastSeries | None:
    from arka.charts.plot import fetch_yahoo_series

    series = fetch_yahoo_series(symbol, history_range)
    if series is None or len(series.values) < 15:
        return None

    prob, signal = _momentum_signal(series.values)
    ml_prob = _try_ml_prob(symbol)
    if ml_prob is not None:
        prob = ml_prob
        if prob > 0.55:
            signal = "BULLISH"
        elif prob < 0.45:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"
        method_prefix = "Random Forest + "
    else:
        method_prefix = ""

    f_dates, f_vals, band_lo, band_hi, method = _linear_forecast(
        series.dates, series.values, horizon_days
    )

    return ForecastSeries(
        label=series.label,
        hist_dates=series.dates,
        hist_values=series.values,
        forecast_dates=f_dates,
        forecast_values=f_vals,
        band_low=band_lo,
        band_high=band_hi,
        prob_up=prob,
        signal=signal,
        method=method_prefix + method,
        currency=series.currency,
    )


def plot_prediction_chart(
    forecast: ForecastSeries,
    *,
    title: str,
    output: Path,
) -> Path:
    from arka.charts.plot import _require_matplotlib

    plt = _require_matplotlib()
    import matplotlib.dates as mdates

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(
        forecast.hist_dates,
        forecast.hist_values,
        color=HIST_COLOR,
        linewidth=2.2,
        label="Historical",
    )
    ax.fill_between(
        forecast.forecast_dates,
        forecast.band_low,
        forecast.band_high,
        color=FORECAST_COLOR,
        alpha=BAND_ALPHA,
        label="Forecast range",
    )
    ax.plot(
        forecast.forecast_dates,
        forecast.forecast_values,
        color=FORECAST_COLOR,
        linewidth=2,
        linestyle="--",
        marker="o",
        markersize=3,
        label="Forecast",
    )
    ax.axvline(forecast.hist_dates[-1], color="#94a3b8", linestyle=":", linewidth=1.2, alpha=0.9)

    if forecast.currency == "mm":
        ylabel = "Rainfall (mm)"
    elif forecast.currency in {"°C", "C"}:
        ylabel = "Temperature (°C)"
    else:
        ylabel = "Price"
        if forecast.currency:
            ylabel += f" ({forecast.currency})"
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Date")
    ax.set_title(title or f"{forecast.label} — price forecast")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    sig_color = {
        "BULLISH": SIGNAL_BULL,
        "BEARISH": SIGNAL_BEAR,
        "NEUTRAL": SIGNAL_NEUT,
    }.get(forecast.signal, SIGNAL_NEUT)
    note = (
        f"{forecast.signal}\n"
        f"P(up) {forecast.prob_up:.0%}\n"
        f"{forecast.method}"
    )
    ax.text(
        0.99,
        0.02,
        note,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor=sig_color, alpha=0.92),
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


def nl_to_predict_argv(text: str) -> list[str] | None:
    if not wants_prediction_chart(text):
        return None

    try:
        from arka.predict.domains import detect_domain

        dom = detect_domain(text)
        if dom in {"weather", "rainfall", "satellite", "timeseries"}:
            argv = ["predict", "--domain", dom, text]
            days = parse_forecast_days(text)
            if days != 30 or re.search(r"\d+\s*(?:day|week|month|year)s?\b", text, re.I):
                argv.extend(["--days", str(days)])
            return argv
    except ImportError:
        pass

    tickers = extract_prediction_tickers(text)
    if not tickers:
        return None
    from arka.charts.plot import parse_range

    argv = ["predict", tickers[0]]
    if len(tickers) > 1:
        argv.extend(tickers[1:])
    days = parse_forecast_days(text)
    if days != 30 or re.search(r"\d+\s*(?:day|week|month|year)s?\b", text, re.I):
        argv.extend(["--days", str(days)])
    history_cue = re.search(
        r"(?i)(?:last|past|over(?:\s+the)?)\s+(?:\d+\s+)?(?:day|days|week|weeks|month|months|year|years)\b"
        r"|\b(?:1d|5d|1mo|3mo|6mo|1y|2y|5y|ytd|max)\b",
        text,
    )
    if history_cue:
        rng = parse_range(text)
        if rng != "3mo":
            argv.extend(["--range", rng])
    title = re.sub(
        r"(?i)\b(?:make|create|show|draw|generate|a|an|the|please|chart|graph|plot|predict(?:ion|ed)?|forecast(?:ed)?|for|of|stock|price|visuali[sz]e)\b",
        " ",
        text,
    )
    title = re.sub(r"\s+", " ", title).strip(" ,.-")
    if title and len(title) > 3:
        argv.extend(["--title", f"{tickers[0]} forecast — {title[:60]}"])
    return argv


def cmd_predict(args: argparse.Namespace) -> int:
    from arka.charts.plot import default_output, open_image

    target = " ".join(getattr(args, "target", []) or []).strip()
    domain = str(getattr(args, "domain", "auto") or "auto").lower()

    if domain == "auto" and target:
        try:
            from arka.predict.domains import detect_domain

            domain = detect_domain(target)
        except ImportError:
            domain = "stock"

    if domain != "stock":
        from arka.predict.engine import run_future

        if not target:
            print(
                "Usage: chart predict --domain weather|rainfall|satellite <query>",
                file=sys.stderr,
            )
            return 1
        result = run_future(
            target,
            domain=domain,
            days=int(args.days),
            chart=True,
            output=Path(args.output).expanduser() if args.output else None,
            history_range=args.range,
        )
        print(result.text)
        if result.chart_path:
            print(f"Saved prediction chart: {result.chart_path}")
            if result.forecast:
                print(f"  Signal: {result.forecast.signal}")
                print(f"  Method: {result.forecast.method}")
        return 0 if result.forecast or result.chart_path else 1

    tickers = extract_prediction_tickers(target) if target else []
    if not tickers:
        print("Usage: chart predict TICKER [--days 30] [--range 1y]", file=sys.stderr)
        print("       chart predict --domain rainfall monsoon in Mumbai --days 14", file=sys.stderr)
        return 1

    sym = tickers[0]
    horizon = int(args.days)
    forecast = build_forecast(sym, history_range=args.range, horizon_days=horizon)
    if forecast is None:
        print(f"No price data for {sym}. Check ticker symbol.", file=sys.stderr)
        return 1

    title = args.title or f"{forecast.label} — {horizon}d forecast ({forecast.signal})"
    slug = re.sub(r"[^a-z0-9]+", "-", f"{forecast.label}-prediction".lower())[:48]
    out = Path(args.output).expanduser() if args.output else default_output(slug)
    saved = plot_prediction_chart(forecast, title=title, output=out)
    print(f"Saved prediction chart: {saved}")
    print(f"  Signal: {forecast.signal} (P(up) {forecast.prob_up:.0%})")
    print(f"  Method: {forecast.method}")
    open_image(saved)
    return 0


def add_predict_subparser(sub) -> None:
    p = sub.add_parser("predict", help="Future prediction chart (stock, weather, rainfall, ISRO, CSV)")
    p.add_argument(
        "target",
        nargs="+",
        help="Ticker symbol or natural-language query (with --domain auto)",
    )
    p.add_argument(
        "--domain",
        default="auto",
        choices=["auto", "stock", "weather", "rainfall", "satellite", "timeseries", "kaggle"],
        help="Prediction domain (auto detects from query)",
    )
    p.add_argument("--days", type=int, default=30, help="Forecast horizon in calendar days")
    p.add_argument("--range", default="1y", help="Historical Yahoo range for stocks")
    p.add_argument("-o", "--output", help="Output PNG path")
    p.add_argument("--title", default="", help="Chart title (stocks)")
    p.set_defaults(func=cmd_predict)
