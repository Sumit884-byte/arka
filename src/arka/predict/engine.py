"""Unified future prediction — stocks, weather, ISRO rainfall, satellites, time series."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from arka.charts.prediction import ForecastSeries, build_forecast, parse_forecast_days
from arka.predict.domains import detect_domain, extract_data_file, extract_location


@dataclass
class PredictResult:
    domain: str
    text: str
    forecast: ForecastSeries | None = None
    chart_path: Path | None = None


def run_future(
    query: str,
    *,
    domain: str = "auto",
    days: int | None = None,
    chart: bool = False,
    output: Path | None = None,
    history_range: str = "1y",
) -> PredictResult:
    query = query.strip()
    if not query:
        return PredictResult("general", "Provide a topic to predict, e.g. rainfall in Mumbai next 2 weeks.")

    dom = detect_domain(query) if domain == "auto" else domain
    horizon = days if days is not None else parse_forecast_days(query)

    if dom == "timeseries":
        from arka.predict.providers.timeseries import build_timeseries_forecast

        path = extract_data_file(query)
        fc = build_timeseries_forecast(path, days=horizon)
        if fc is None:
            return PredictResult(dom, f"Could not forecast from file: {path}")
        text = f"Time-series forecast for {path} ({horizon}d trend)."
        return _maybe_chart(dom, text, fc, chart, output, query)

    if dom == "kaggle":
        from arka.predict.providers.kaggle import build_kaggle_forecast

        try:
            fc, summary = build_kaggle_forecast(query, days=horizon)
        except Exception as exc:
            return PredictResult(dom, f"Kaggle forecast failed: {exc}")
        return _maybe_chart(dom, summary, fc, chart, output, fc.label)

    if dom == "satellite":
        from arka.predict.providers.satellite import format_satellite_passes

        return PredictResult(dom, format_satellite_passes(query))

    if dom == "rainfall":
        from arka.predict.providers.isro import isro_rainfall_context
        from arka.predict.providers.weather import build_weather_forecast, format_weather_text

        fc = build_weather_forecast(query, days=horizon, metric="precip", use_isro_note=True)
        context = isro_rainfall_context(query)
        wx = format_weather_text(query, days=min(horizon, 16))
        text = f"{context}\n\n{wx}"
        if fc is None:
            return PredictResult(dom, text)
        return _maybe_chart(
            dom,
            text,
            fc,
            chart,
            output,
            f"Rainfall forecast — {extract_location(query) or 'location'}",
        )

    if dom == "weather":
        from arka.predict.providers.weather import build_weather_forecast, format_weather_text

        fc = build_weather_forecast(query, days=horizon, metric="temp")
        text = format_weather_text(query, days=min(horizon, 16))
        if fc is None:
            return PredictResult(dom, text)
        return _maybe_chart(
            dom,
            text,
            fc,
            chart,
            output,
            f"Weather forecast — {extract_location(query) or 'location'}",
        )

    if dom == "stock":
        from arka.charts.prediction import extract_prediction_tickers

        tickers = extract_prediction_tickers(query)
        if not tickers:
            return PredictResult(dom, "No ticker found for stock prediction.")
        fc = build_forecast(tickers[0], history_range=history_range, horizon_days=horizon)
        if fc is None:
            return PredictResult(dom, f"No price data for {tickers[0]}.")
        text = (
            f"Stock forecast {tickers[0]}: {fc.signal} (P(up) {fc.prob_up:.0%}). "
            f"Method: {fc.method}."
        )
        return _maybe_chart(
            dom,
            text,
            fc,
            chart,
            output,
            f"{fc.label} — {horizon}d forecast ({fc.signal})",
        )

    # general — try weather if location present, else LLM predictions talent
    loc = extract_location(query)
    if loc and re.search(r"(?i)\b(?:rain|weather|temp|monsoon|forecast)\b", query):
        return run_future(query, domain="weather", days=days, chart=chart, output=output)

    try:
        from arka.stock.predictions import run_prediction

        answer = run_prediction(query, domain="auto", deep=False)
        return PredictResult("general", answer)
    except Exception as exc:
        return PredictResult(
            "general",
            "Could not run general prediction. Try a specific domain:\n"
            "  • weather/rainfall: predict rainfall in Mumbai next 2 weeks\n"
            "  • stock: predict AAPL stock price chart\n"
            "  • satellite: ISS pass over Delhi\n"
            "  • kaggle: predict future from kaggle owner/dataset --chart\n"
            "  • ISRO: configure MOSDAC_USER/PASSWORD for archive access\n"
            f"({exc})",
        )


def _maybe_chart(
    domain: str,
    text: str,
    fc: ForecastSeries,
    chart: bool,
    output: Path | None,
    title: str,
) -> PredictResult:
    if not chart:
        return PredictResult(domain, text, forecast=fc)
    from arka.charts.plot import default_output, open_image
    from arka.charts.prediction import plot_prediction_chart

    slug = re.sub(r"[^a-z0-9]+", "-", f"{domain}-{fc.label}".lower())[:48]
    out = output.expanduser() if output else default_output(slug)
    saved = plot_prediction_chart(fc, title=title, output=out)
    open_image(saved)
    return PredictResult(domain, text, forecast=fc, chart_path=saved)


def nl_to_future_argv(text: str) -> list[str] | None:
    from arka.predict.domains import wants_future_prediction

    if not wants_future_prediction(text):
        return None

    # Stock + chart still goes through chart predict for backwards compat
    from arka.charts.prediction import nl_to_predict_argv, wants_prediction_chart

    if wants_prediction_chart(text):
        stock_argv = nl_to_predict_argv(text)
        if stock_argv:
            return stock_argv

    argv = ["future", text]
    days = parse_forecast_days(text)
    if days != 30 or re.search(r"\d+\s*(?:day|week|month|year)s?\b", text, re.I):
        argv.extend(["--days", str(days)])
    dom = detect_domain(text)
    if dom != "general":
        argv.extend(["--domain", dom])
    if re.search(r"(?i)\b(?:chart|graph|plot|visuali[sz]e)\b", text):
        argv.append("--chart")
    return argv
