"""Detect prediction domain from natural language."""

from __future__ import annotations

import re
from pathlib import Path

_EXCHANGE_TICKER = re.compile(
    r"\b([A-Z][A-Z0-9&.-]{0,20}\.(?:NS|BO|L|HK|KS|TO|AX|LON|SW|PA|DE|MI))\b",
    re.I,
)
_DATA_FILE = re.compile(r"(?i)(['\"]?)([^\s'\"]+\.(?:csv|tsv|json))\1")

_ISRO_WORDS = re.compile(
    r"(?i)\b(?:isro|mosdac|gsmap|insat|saphir|bhuvan|imd\s+satellite|satellite\s+rain(?:fall)?)\b"
)
_RAIN_WORDS = re.compile(
    r"(?i)\b(?:rain(?:fall)?|monsoon|precipitation|precip|wet\s+spell|dry\s+spell)\b"
)
_WEATHER_WORDS = re.compile(
    r"(?i)\b(?:weather|temperature|temp|forecast|humidity|heatwave|cold\s+wave|cyclone|storm)\b"
)
_SATELLITE_WORDS = re.compile(
    r"(?i)\b(?:iss|international\s+space\s+station|satellite\s+pass|space\s+station\s+pass)\b"
)
_STOCK_WORDS = re.compile(
    r"(?i)\b(?:stock|share|ticker|equity|nifty|sensex|nse|bse|portfolio|price)\b"
)
_FUTURE_WORDS = re.compile(
    r"(?i)\b(?:predict(?:ion|ed)?|forecast(?:ed)?|future|outlook|next\s+\d+|"
    r"next\s+week|next\s+month|will\s+it|going\s+to)\b"
)
_KAGGLE_WORDS = re.compile(r"(?i)\bkaggle\b")


def extract_data_file(text: str) -> str:
    m = _DATA_FILE.search(text)
    if not m:
        return ""
    path = m.group(2).strip()
    if path.startswith("~"):
        return str(Path(path).expanduser())
    return path


def extract_location(text: str) -> str:
    """Best-effort city/place from a forecast query."""
    t = text.strip()
    for pat in (
        r"(?i)\b(?:in|at|for|over)\s+([A-Za-z][A-Za-z\s,.-]{1,40}?)(?:\s+(?:next|for|this|over)\b|$|[?.!,])",
        r"(?i)\b(?:weather|rain(?:fall)?|forecast|monsoon)\s+(?:in|at|for)\s+([A-Za-z][A-Za-z\s,.-]{1,40}?)(?:\s+(?:next|for)\b|$|[?.!,])",
        r"(?i)\b(?:iss|space\s+station)\s+(?:pass(?:es)?|over)\s+(?:for\s+)?([A-Za-z][A-Za-z\s,.-]{1,40}?)(?:\s|$|[?.!,])",
    ):
        m = re.search(pat, t)
        if m:
            loc = m.group(1).strip(" ,.-")
            if loc and len(loc) > 1:
                return loc
    return ""


def has_stock_ticker(text: str) -> bool:
    from arka.charts.prediction import extract_prediction_tickers

    return bool(extract_prediction_tickers(text))


def extract_kaggle_slug(text: str) -> str:
    from arka.predict.providers.kaggle import extract_kaggle_slug as _slug

    return _slug(text)


def detect_domain(text: str) -> str:
    """Return stock|rainfall|weather|satellite|timeseries|kaggle|general."""
    if not text.strip():
        return "general"

    if extract_data_file(text):
        return "timeseries"

    if _KAGGLE_WORDS.search(text) and (
        _FUTURE_WORDS.search(text)
        or re.search(r"(?i)\b(?:chart|graph|plot|timeseries|time\s+series|trend)\b", text)
        or extract_kaggle_slug(text)
    ):
        return "kaggle"

    if _SATELLITE_WORDS.search(text) and not _STOCK_WORDS.search(text):
        return "satellite"

    if _ISRO_WORDS.search(text) or (
        _RAIN_WORDS.search(text) and not has_stock_ticker(text)
    ):
        return "rainfall"

    if _WEATHER_WORDS.search(text) and not has_stock_ticker(text):
        return "weather"

    if has_stock_ticker(text) or (
        _STOCK_WORDS.search(text) and _FUTURE_WORDS.search(text)
    ):
        return "stock"

    if _FUTURE_WORDS.search(text):
        return "general"

    return "general"


def wants_future_prediction(text: str) -> bool:
    if not text.strip():
        return False
    if detect_domain(text) != "general":
        return True
    return bool(_FUTURE_WORDS.search(text))
