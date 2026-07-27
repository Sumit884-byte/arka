"""Future prediction from Kaggle dataset time series."""

from __future__ import annotations

import re
from pathlib import Path

_KAGGLE_URL = re.compile(
    r"kaggle\.com/datasets/([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)",
    re.I,
)
_KAGGLE_SLUG = re.compile(
    r"(?i)\bkaggle(?:\s+dataset|\s+datasets)?\s+([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)\b"
)


def extract_kaggle_slug(text: str) -> str:
    m = _KAGGLE_URL.search(text)
    if m:
        return m.group(1)
    m = _KAGGLE_SLUG.search(text)
    if m:
        return m.group(1)
    return ""


def _cache_dir(slug: str) -> Path:
    safe = slug.replace("/", "__")
    root = Path.home() / ".cache" / "arka" / "kaggle-predict"
    return root / safe


def pick_timeseries_file(root: Path) -> Path | None:
    from arka.charts.tabular import load_rows, resolve_columns

    if root.is_file() and root.suffix.lower() in {".csv", ".tsv", ".json"}:
        return root

    candidates: list[Path] = []
    for ext in ("*.csv", "*.tsv", "*.json"):
        candidates.extend(root.rglob(ext))
    if not candidates:
        return None

    best: tuple[int, Path] | None = None
    for path in candidates:
        if path.name.startswith(".") or "sample" in path.name.lower():
            continue
        try:
            rows = load_rows(path)
            if len(rows) < 5:
                continue
            _, val_col = resolve_columns(rows)
            numeric = 0
            for row in rows[:50]:
                raw = row.get(val_col)
                if raw is None:
                    continue
                try:
                    float(str(raw).replace(",", ""))
                    numeric += 1
                except ValueError:
                    pass
            score = numeric * 1000 + len(rows)
            if best is None or score > best[0]:
                best = (score, path)
        except Exception:
            continue
    return best[1] if best else candidates[0]


def ensure_kaggle_dataset(slug: str, *, refresh: bool = False) -> Path:
    from arka.integrations.kaggle import download_dataset, sanitize_dataset_slug

    safe = sanitize_dataset_slug(slug)
    out = _cache_dir(safe)
    if not refresh:
        existing = pick_timeseries_file(out)
        if existing is not None:
            return existing

    out.mkdir(parents=True, exist_ok=True)
    download_dataset(safe, output_dir=out, unzip=True, open_browser=False)
    picked = pick_timeseries_file(out)
    if picked is None:
        raise RuntimeError(f"No CSV/TSV/JSON time series found in Kaggle dataset {safe}")
    return picked


def build_kaggle_forecast(
    query: str,
    *,
    days: int = 30,
    slug: str = "",
    value_col: str = "",
) -> tuple[object, str]:
    from arka.predict.providers.timeseries import build_timeseries_forecast

    dataset = slug or extract_kaggle_slug(query)
    if not dataset:
        raise ValueError("No Kaggle dataset slug (expected owner/name or kaggle.com/datasets/… URL)")

    path = ensure_kaggle_dataset(dataset)
    fc = build_timeseries_forecast(path, days=days, value_col=value_col)
    if fc is None:
        raise RuntimeError(f"Could not build forecast from {path}")

    slug_display = dataset
    fc.label = f"{slug_display} ({path.name})"
    fc.method = f"{fc.method} · Kaggle {slug_display}"
    summary = (
        f"Kaggle dataset {slug_display}\n"
        f"  series file: {path}\n"
        f"  forecast: {days}d linear trend from historical column"
    )
    return fc, summary
