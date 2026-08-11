"""Future forecast from a local CSV/TSV/JSON time series."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from arka.charts.prediction import ForecastSeries, _linear_forecast


def build_timeseries_forecast(
    path: str | Path,
    *,
    days: int = 30,
    value_col: str = "",
) -> ForecastSeries | None:
    from arka.charts.tabular import load_rows, resolve_columns

    p = Path(path).expanduser()
    if not p.is_file():
        return None
    rows = load_rows(p)
    if not rows:
        return None
    label_col, val_col = resolve_columns(rows, value=value_col or None)
    dates: list[datetime] = []
    values: list[float] = []
    for row in rows:
        raw_label = row.get(label_col)
        raw_val = row.get(val_col)
        if raw_val is None:
            continue
        try:
            val = float(str(raw_val).replace(",", ""))
        except ValueError:
            continue
        dt: datetime | None = None
        if raw_label is not None:
            s = str(raw_label).strip()
            if s.isdigit() and len(s) == 4:
                dt = datetime(int(s), 1, 1, tzinfo=timezone.utc)
            else:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        dt = datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
        if dt is None:
            dt = datetime.now(timezone.utc)
        dates.append(dt)
        values.append(val)

    if len(values) < 5:
        return None

    f_dates, f_vals, band_lo, band_hi, method = _linear_forecast(dates, values, days)
    return ForecastSeries(
        label=p.stem,
        hist_dates=dates,
        hist_values=values,
        forecast_dates=f_dates,
        forecast_values=f_vals,
        band_low=band_lo,
        band_high=band_hi,
        prob_up=0.5,
        signal="TREND",
        method=f"{method} · file {p.name}",
        currency="",
    )
