"""Weather and rainfall forecasts via Open-Meteo (satellite-assimilated)."""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

from arka.charts.prediction import ForecastSeries, _linear_forecast


def _geocode(city: str) -> tuple[float, float, str] | None:
    from arka.agent.chat import resolve_weather_coords

    resolved = resolve_weather_coords(city or None)
    if not resolved:
        return None
    lat, lon, label = resolved
    return float(lat), float(lon), label


def _fetch_daily(lat: float, lon: float, *, past_days: int, forecast_days: int) -> dict:
    from arka.agent.chat import _open_meteo_get

    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,precipitation_sum,precipitation_probability_max",
        "timezone": "auto",
        "past_days": max(1, min(past_days, 92)),
        "forecast_days": max(1, min(forecast_days, 16)),
    })
    return _open_meteo_get(f"https://api.open-meteo.com/v1/forecast?{params}")


def _split_daily(
    payload: dict,
    *,
    metric: str,
) -> tuple[list[datetime], list[float], list[datetime], list[float], str] | None:
    daily = payload.get("daily") or {}
    dates_raw = daily.get("time") or []
    if metric == "precip":
        values = daily.get("precipitation_sum") or []
        unit = "mm"
    else:
        values = daily.get("temperature_2m_max") or []
        unit = "°C"
    if not dates_raw or not values:
        return None

    today = datetime.now(timezone.utc).date()
    hist_dates: list[datetime] = []
    hist_values: list[float] = []
    fut_dates: list[datetime] = []
    fut_values: list[float] = []

    for d, v in zip(dates_raw, values):
        if v is None:
            continue
        try:
            dt = datetime.fromisoformat(str(d)).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        val = float(v)
        if dt.date() <= today:
            hist_dates.append(dt)
            hist_values.append(val)
        else:
            fut_dates.append(dt)
            fut_values.append(val)

    if len(hist_dates) < 3:
        return None
    return hist_dates, hist_values, fut_dates, fut_values, unit


def build_weather_forecast(
    query: str,
    *,
    days: int = 7,
    metric: str = "temp",
    use_isro_note: bool = False,
) -> ForecastSeries | None:
    from arka.predict.domains import extract_location

    loc = extract_location(query) or query.strip()
    geo = _geocode(loc)
    if geo is None:
        return None
    lat, lon, label = geo

    past = min(30, max(7, days))
    try:
        payload = _fetch_daily(lat, lon, past_days=past, forecast_days=min(days, 16))
    except Exception:
        return None

    split = _split_daily(payload, metric=metric)
    if split is None:
        return None
    hist_dates, hist_values, fut_dates, fut_values, unit = split

    if fut_dates:
        band_lo = [max(0.0, v * 0.75) for v in fut_values]
        band_hi = [v * 1.25 for v in fut_values]
        f_dates, f_vals = fut_dates, fut_values
        method = "Open-Meteo daily forecast"
    else:
        f_dates, f_vals, band_lo, band_hi, method = _linear_forecast(
            hist_dates, hist_values, min(days, 16)
        )

    source = "Open-Meteo (satellite-assimilated global model)"
    if use_isro_note or metric == "precip":
        source += "; ISRO MOSDAC GSMaP archives with MOSDAC_USER/PASSWORD"
    method = f"{method} · {source}"

    if metric == "precip":
        wet = sum(f_vals[: min(7, len(f_vals))])
        signal = "WET" if wet > 10 else "DRY"
        prob = min(0.95, max(0.05, wet / 50))
    else:
        recent = hist_values[-1] if hist_values else 0
        future_avg = sum(f_vals[: min(7, len(f_vals))]) / max(1, min(7, len(f_vals)))
        prob = 0.5 + max(-0.4, min(0.4, (future_avg - recent) / max(abs(recent), 1) * 0.5))
        signal = "WARMER" if future_avg > recent + 0.5 else "COOLER" if future_avg < recent - 0.5 else "STEADY"

    metric_label = "Rainfall" if metric == "precip" else "Temperature max"
    return ForecastSeries(
        label=f"{label} {metric_label}",
        hist_dates=hist_dates,
        hist_values=hist_values,
        forecast_dates=f_dates,
        forecast_values=f_vals,
        band_low=band_lo,
        band_high=band_hi,
        prob_up=prob,
        signal=signal,
        method=method,
        currency=unit,
    )


def format_weather_text(query: str, *, days: int = 7) -> str:
    from arka.agent.chat import fetch_weather_forecast
    from arka.predict.domains import extract_location

    loc = extract_location(query)
    return fetch_weather_forecast(days, city=loc or None)
