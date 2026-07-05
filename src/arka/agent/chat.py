#!/usr/bin/env python3
"""Arka chat engine: deep web RAG, intent routing, location, weather, maps, calc, session."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import arka.paths as _ap

    _ap.load_env_file()
    CACHE_DIR = _ap.cache_dir()
except ImportError:
    CACHE_DIR = Path.home() / ".cache" / "fish-agent"

MAPS_DIR = CACHE_DIR / "maps"
SESSION_FILE = CACHE_DIR / "chat_session.json"
CONTEXT_FILE = CACHE_DIR / "chat_context.json"
QUEUE_FILE = CACHE_DIR / "deep_queue.json"
QUEUE_RESULTS_FILE = CACHE_DIR / "deep_queue_results.json"

YEAR = datetime.now().year
CURRENT_DATE = datetime.now().strftime("%B %d, %Y")

SEARCH_KEYWORDS = [
    "latest", "recent", "now", "today", "current", "live",
    "2023", "2024", "2025", "2026",
    "hackathon", "conference", "release", "update", "changelog",
    "event", "news", "announcement",
    "stock", "price", "value", "market", "crypto",
    "ipl", "t20", "cricket", "match", "score", "winner", "championship",
    "fifa", "nfl", "nba", "wimbledon", "olympics",
    "documentation", "api", "tutorial", "guide", "weather",
]

ERROR_KEYWORDS = [
    "Error", "Exception", "Traceback", "AttributeError",
    "ImportError", "ModuleNotFoundError", "TypeError", "ValueError",
    "SyntaxError", "KeyError", "RuntimeError", "FileNotFoundError",
]

DECISION_PROMPT = f"""You are a decision engine. Today is {CURRENT_DATE}.
Output exactly one line:
CALC: <sympy expression>  — math, equations, integrals, derivatives
SEARCH: <short query>       — live/recent data, news, scores, prices, current events
ANSWER: <brief>             — timeless facts, no web needed
Do not explain."""

ASSISTANT_SYSTEM = f"""You are a direct, concise assistant. Today is {CURRENT_DATE}. Year: {YEAR}.
- If using web search results, start with: [FROM SEARCH]
- If answering from general knowledge only, start with: [FROM MEMORY]
- For simple questions: 2-4 short sentences; state the direct answer first.
- For "top N" or numbered-list requests: give all N items, one per line.
- When reusing items from chat memory, keep their full descriptions — do not shorten to names only.
- Never copy tables, nav menus, or page chrome from search results.
- Suitable for spoken text-to-speech: no markdown unless essential.
- Do not mention knowledge cutoffs."""


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def ensure_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: object) -> object:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data: object) -> None:
    ensure_cache()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_context() -> dict:
    ctx = load_json(CONTEXT_FILE, {})
    if not isinstance(ctx, dict):
        ctx = {}
    ctx.setdefault("pincode", None)
    ctx.setdefault("city", "Unknown")
    ctx.setdefault("coords", None)
    ctx.setdefault("location_string", None)
    return ctx


def save_context(ctx: dict) -> None:
    save_json(CONTEXT_FILE, ctx)


def load_session() -> list[dict]:
    data = load_json(SESSION_FILE, {"messages": []})
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        return data["messages"]
    return []


def save_session(messages: list[dict]) -> None:
    save_json(SESSION_FILE, {"messages": messages[-20:]})


def session_reset() -> None:
    save_session([])
    save_context({"pincode": None, "city": "Unknown", "coords": None, "location_string": None})


def session_append(role: str, content: str) -> None:
    msgs = load_session()
    msgs.append({"role": role, "content": content})
    save_session(msgs)
    if role == "user" and content.strip():
        try:
            from arka.agent.core import memory_auto_detect

            memory_auto_detect(content, quiet=True)
        except ImportError:
            pass


def extract_pin(text: str) -> str | None:
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None


WMO_WEATHER: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def wmo_label(code: int | float | None) -> str:
    if code is None:
        return "Unknown"
    return WMO_WEATHER.get(int(code), f"Code {int(code)}")


TOMORROW_RE = re.compile(
    r"\bto+morrow'?s?\b|\btomm?orrows?'?s?\b|\btommorow'?s?\b|\btomorow'?s?\b",
    re.I,
)


def parse_forecast_target(text: str) -> str | None:
    """Return 'tomorrow' or 'today' when the question names a single day."""
    if TOMORROW_RE.search(text):
        return "tomorrow"
    if re.search(r"\btoday'?s?\b", text, re.I):
        return "today"
    return None


def parse_forecast_days(text: str, default: int = 0) -> int:
    """Parse '5 day forecast', 'next 7 days' from natural language."""
    if parse_forecast_target(text):
        return 0
    low = text.lower()
    m = re.search(r"\b(\d{1,2})\s*(?:-?\s*)?(?:day|days)\b", low)
    if m:
        return max(1, min(16, int(m.group(1))))
    if re.search(r"\bnext\s+week\b|\b(?:this\s+)?week(?:\'s)?\s+forecast\b", low):
        return 7
    if re.search(r"\bforecast\b|\bnext\s+few\s+days\b", low) and default <= 0:
        return 3
    return default


WEATHER_DETAIL_RE = re.compile(
    r"(?i)\b("
    r"in\s+detail|detailed|full\s+detail|more\s+detail|"
    r"hourly|hour[\s-]by[\s-]hour|each\s+hour|every\s+hour|"
    r"breakdown|explain\s+everything|full\s+forecast"
    r")\b",
)


def parse_weather_detail_mode(text: str) -> bool:
    """True when user wants hourly / full day breakdown."""
    return bool(WEATHER_DETAIL_RE.search(text))


def _weather_overall_kind(code: int | float | None, label: str) -> str:
    low = label.lower()
    c = int(code) if code is not None else -1
    if c in {95, 96, 99} or "thunder" in low:
        return "Stormy"
    if c in {71, 73, 75, 77, 85, 86} or "snow" in low:
        return "Snowy"
    if c in {51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82} or "rain" in low or "drizzle" in low:
        return "Rainy"
    if c in {45, 48} or "fog" in low:
        return "Foggy"
    if c == 3 or "overcast" in low:
        return "Cloudy"
    if c == 2 or "partly" in low:
        return "Partly cloudy"
    if c in {0, 1} or "clear" in low:
        return "Sunny"
    return label.split(" with ")[0].split(" and ")[0] or "Mixed"


def _weather_intensity(pop: float, mm: float, label: str) -> str:
    low = label.lower()
    if "heavy" in low or "violent" in low:
        return "strong"
    if "thunder" in low and (pop >= 50 or mm >= 5):
        return "strong"
    if pop >= 70 or mm >= 10:
        return "strong"
    if pop >= 40 or mm >= 2:
        return "moderate"
    if pop >= 15 or mm >= 0.3 or "drizzle" in low or "light rain" in low:
        return "light"
    return "light" if pop > 0 or mm > 0 else ""


def geocode_place(name: str) -> tuple[float, float, str] | None:
    name = name.strip()
    if not name:
        return None
    geo_url = (
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode({"name": name, "count": 1, "language": "en", "format": "json"})
    )
    try:
        req = urllib.request.Request(geo_url, headers={"User-Agent": "arka-chat/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            geo = json.loads(resp.read().decode())
        results = geo.get("results") or []
        if not results:
            return None
        hit = results[0]
        label = ", ".join(
            x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x
        )
        return float(hit["latitude"]), float(hit["longitude"]), label
    except Exception:
        return None


def resolve_weather_coords(city: str | None = None) -> tuple[float, float, str] | None:
    if city and city.strip():
        found = geocode_place(city.strip())
        if found:
            return found
    ctx = get_live_location()
    coords = ctx.get("coords")
    if coords and "," in str(coords):
        lat, lon = str(coords).split(",", 1)
        label = ctx.get("location_string") or ctx.get("city") or coords
        return float(lat.strip()), float(lon.strip()), str(label)
    city_name = ctx.get("city", "")
    if city_name and city_name != "Unknown":
        found = geocode_place(str(city_name))
        if found:
            return found
    return None


def _open_meteo_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "arka-chat/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _clean_location_label(label: str) -> str:
    return re.sub(r"\s*\(IP:[^)]*\)", "", label).strip()


def _weather_emoji(code: int | float | None) -> str:
    c = int(code) if code is not None else -1
    if c in {0, 1}:
        return "☀"
    if c == 2:
        return "⛅"
    if c == 3:
        return "☁"
    if c in {45, 48}:
        return "🌫"
    if c in {51, 53, 55, 61, 63, 80, 81}:
        return "🌧"
    if c in {65, 82, 66, 67}:
        return "🌧"
    if c in {71, 73, 75, 77, 85, 86}:
        return "❄"
    if c in {95, 96, 99}:
        return "⛈"
    return "·"


def _weather_tip(cond: str, pop: float, mm: float, hi: float | None, lo: float | None) -> str:
    low = cond.lower()
    if "thunder" in low or pop >= 70:
        return "Storms likely — carry an umbrella and avoid open areas if thunder starts."
    if pop >= 50 or mm >= 2:
        return "Rain likely at times — keep an umbrella handy."
    if hi is not None and hi >= 35:
        return "Hot day — stay hydrated and limit midday sun."
    if lo is not None and lo <= 10:
        return "Chilly — layer up especially in the morning and evening."
    if "clear" in low or "mainly clear" in low:
        return "Mostly fair weather — good day to be outdoors."
    if "fog" in low:
        return "Fog possible — take care if driving early or late."
    return "Check the hourly outlook if you are planning outdoor plans."


def _fmt_temp(val: object) -> str:
    if val is None or val == "?":
        return "—"
    try:
        return f"{float(val):.0f}°"
    except (TypeError, ValueError):
        return str(val)


def fetch_day_brief(lat: float, lon: float, label: str, *, day_offset: int = 0) -> str:
    """Short single-day outlook: overall condition, intensity, temps, rain — no hourly."""
    day_offset = max(0, min(1, int(day_offset)))
    need_days = day_offset + 1
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
        "daily": (
            "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max"
        ),
        "timezone": "auto",
        "forecast_days": need_days,
    })
    try:
        data = _open_meteo_get(f"https://api.open-meteo.com/v1/forecast?{params}")
    except Exception as exc:
        return f"Weather forecast failed: {exc}"

    place = _clean_location_label(label)
    cw = data.get("current_weather") or {}
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if len(dates) <= day_offset:
        return f"No forecast for that day in {place}."

    day_date = dates[day_offset]
    try:
        from datetime import date as date_cls
        nice_date = date_cls.fromisoformat(day_date).strftime("%a %d %b")
    except ValueError:
        nice_date = day_date

    hi = (daily.get("temperature_2m_max") or [None])[day_offset]
    lo = (daily.get("temperature_2m_min") or [None])[day_offset]
    day_code = (daily.get("weathercode") or [None])[day_offset]
    day_pop = float((daily.get("precipitation_probability_max") or [0])[day_offset] or 0)
    day_mm = float((daily.get("precipitation_sum") or [0])[day_offset] or 0)
    day_label = wmo_label(day_code)
    kind = _weather_overall_kind(day_code, day_label)
    intensity = _weather_intensity(day_pop, day_mm, day_label)

    title = "Tomorrow" if day_offset else "Today"
    lines = [f"{title} — {nice_date} — {place}"]

    overall = f"Overall: {kind}"
    if intensity:
        overall += f" ({intensity})"
    overall += f" {_weather_emoji(day_code)} · {_fmt_temp(lo)}–{_fmt_temp(hi)}"
    if day_pop > 0:
        overall += f" · Rain {day_pop:.0f}%"
    if day_mm > 0:
        overall += f" · ~{day_mm:.1f} mm"
    lines.append(overall)

    if day_offset == 0 and cw:
        now_code = cw.get("weathercode")
        lines.append(
            f"Now: {_fmt_temp(cw.get('temperature'))} {_weather_emoji(now_code)} {wmo_label(now_code)}"
        )

    return "\n".join(lines)


def fetch_day_detail(lat: float, lon: float, label: str, *, day_offset: int = 0, hourly_all: bool = False) -> str:
    """Rich single-day outlook (today=0, tomorrow=1): summary + hourly timeline."""
    day_offset = max(0, min(1, int(day_offset)))
    need_days = day_offset + 1
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
        "hourly": (
            "temperature_2m,precipitation_probability,precipitation,weathercode,"
            "windspeed_10m,relativehumidity_2m"
        ),
        "daily": (
            "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,uv_index_max,sunrise,sunset"
        ),
        "timezone": "auto",
        "forecast_days": need_days,
    })
    try:
        data = _open_meteo_get(f"https://api.open-meteo.com/v1/forecast?{params}")
    except Exception as exc:
        return f"Weather forecast failed: {exc}"

    place = _clean_location_label(label)
    cw = data.get("current_weather") or {}
    daily = data.get("daily") or {}
    hourly = data.get("hourly") or {}

    dates = daily.get("time") or []
    if len(dates) <= day_offset:
        return f"No forecast for that day in {_clean_location_label(label)}."

    day_date = dates[day_offset]
    try:
        from datetime import date as date_cls
        nice_date = date_cls.fromisoformat(day_date).strftime("%a %d %b")
    except ValueError:
        nice_date = day_date

    hi = (daily.get("temperature_2m_max") or [None])[day_offset]
    lo = (daily.get("temperature_2m_min") or [None])[day_offset]
    day_code = (daily.get("weathercode") or [None])[day_offset]
    day_pop = (daily.get("precipitation_probability_max") or [0])[day_offset]
    day_mm = (daily.get("precipitation_sum") or [0])[day_offset]
    uv = (daily.get("uv_index_max") or [None])[day_offset]
    sunrise = ((daily.get("sunrise") or [""])[day_offset] or "")[11:16]
    sunset = ((daily.get("sunset") or [""])[day_offset] or "")[11:16]
    day_label = wmo_label(day_code)

    title = "Tomorrow" if day_offset else "Today"
    lines = [f"━━━ {title} — {nice_date} — {place} ━━━", ""]

    if day_offset == 0:
        now_code = cw.get("weathercode")
        now_temp = cw.get("temperature")
        now_wind = cw.get("windspeed")
        now_time = (cw.get("time") or "")[:16].replace("T", " ")
        lines.append(f"Now      {_fmt_temp(now_temp)}  {_weather_emoji(now_code)}  {wmo_label(now_code)}")
        times = hourly.get("time") or []
        humidity = None
        if now_time and times:
            now_key = now_time.replace(" ", "T")
            for i, t in enumerate(times):
                if t.startswith(now_key[:13]) or t == now_key:
                    hums = hourly.get("relativehumidity_2m") or []
                    if i < len(hums):
                        humidity = hums[i]
                    break
        now_bits = []
        if now_wind is not None:
            now_bits.append(f"Wind {float(now_wind):.0f} km/h")
        if humidity is not None:
            now_bits.append(f"Humidity {float(humidity):.0f}%")
        if now_time:
            now_bits.append(f"as of {now_time[11:16] if len(now_time) > 10 else now_time}")
        if now_bits:
            lines.append(f"         {'  ·  '.join(now_bits)}")
        lines.append("")
        summary_head = "Today   "
    else:
        lines.append(
            f"Outlook  {_weather_emoji(day_code)}  {day_label}"
        )
        lines.append("")
        summary_head = "All day "

    lines.append(
        f"{summary_head} High {_fmt_temp(hi)}  ·  Low {_fmt_temp(lo)}  ·  {day_label}"
    )

    rain_bits = []
    if day_pop is not None and float(day_pop) > 0:
        rain_bits.append(f"Rain {float(day_pop):.0f}% likely")
    if day_mm is not None and float(day_mm) > 0:
        rain_bits.append(f"~{float(day_mm):.1f} mm expected")
    if uv is not None:
        rain_bits.append(f"UV {float(uv):.0f}")
    if sunrise and sunset:
        rain_bits.append(f"Sun {sunrise}–{sunset}")
    if rain_bits:
        lines.append(f"         {'  ·  '.join(rain_bits)}")

    h_times = hourly.get("time") or []
    h_temps = hourly.get("temperature_2m") or []
    h_codes = hourly.get("weathercode") or []
    h_pops = hourly.get("precipitation_probability") or []

    day_hours: list[tuple[str, float, int, float]] = []
    for i, t in enumerate(h_times):
        if not t.startswith(day_date):
            continue
        if i >= len(h_temps):
            break
        day_hours.append((
            t,
            h_temps[i],
            h_codes[i] if i < len(h_codes) else 0,
            h_pops[i] if i < len(h_pops) else 0,
        ))

    if day_hours:
        lines.append("")
        if hourly_all:
            lines.append("Hour-by-hour")
            slots = day_hours
        else:
            lines.append("Hourly" if day_offset else "Next hours")
            slots: list[tuple[str, float, int, float]] = []
            for item in day_hours:
                if day_offset == 0:
                    now_prefix = (cw.get("time") or "")[:13]
                    if now_prefix and item[0][:13] < now_prefix:
                        continue
                if not slots:
                    slots.append(item)
                    continue
                h = int(item[0][11:13])
                prev_h = int(slots[-1][0][11:13])
                if h - prev_h >= 3:
                    slots.append(item)
                if len(slots) >= 8:
                    break
            if day_offset == 1 and len(slots) < 4:
                slots = day_hours[::3][:8]
            if len(slots) == 1 and len(day_hours) > 1:
                slots = day_hours[:: max(1, len(day_hours) // 8)][:8]
        for t, temp, code, pop in slots:
            hh = t[11:16]
            pop_s = f"  rain {float(pop):.0f}%" if pop and float(pop) > 0 else ""
            lines.append(
                f"  {hh}   {_fmt_temp(temp)}  {_weather_emoji(code)} {wmo_label(code)}{pop_s}"
            )

    tip = _weather_tip(day_label, float(day_pop or 0), float(day_mm or 0), hi, lo)
    lines.extend(["", f"Tip      {tip}"])
    return "\n".join(lines)


def fetch_one_day_detail(lat: float, lon: float, label: str) -> str:
    return fetch_day_detail(lat, lon, label, day_offset=0)


def fetch_weather_forecast(days: int = 7, *, city: str | None = None) -> str:
    days = max(1, min(16, int(days)))
    resolved = resolve_weather_coords(city)
    if not resolved:
        return "Could not determine location for weather. Try: set_location Kolkata"
    lat, lon, label = resolved

    if days == 1:
        return fetch_one_day_detail(lat, lon, label)

    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": days,
    })
    try:
        data = _open_meteo_get(f"https://api.open-meteo.com/v1/forecast?{params}")
    except Exception as exc:
        return f"Weather forecast failed: {exc}"

    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if not dates:
        return f"No forecast data for {_clean_location_label(label)}."

    place = _clean_location_label(label)
    lines = [f"━━━ {days}-day forecast — {place} ━━━", ""]
    max_t = daily.get("temperature_2m_max") or []
    min_t = daily.get("temperature_2m_min") or []
    codes = daily.get("weathercode") or []
    rain = daily.get("precipitation_sum") or []
    pop = daily.get("precipitation_probability_max") or []

    for i, day in enumerate(dates[:days]):
        hi = max_t[i] if i < len(max_t) else "?"
        lo = min_t[i] if i < len(min_t) else "?"
        cond = wmo_label(codes[i] if i < len(codes) else None)
        emoji = _weather_emoji(codes[i] if i < len(codes) else None)
        mm = rain[i] if i < len(rain) else 0
        prob = pop[i] if i < len(pop) else None
        extra_parts: list[str] = []
        if prob is not None and float(prob) > 0:
            extra_parts.append(f"rain {float(prob):.0f}%")
        if mm is not None and float(mm) > 0:
            extra_parts.append(f"{float(mm):.1f} mm")
        extra = f"  ·  {' · '.join(extra_parts)}" if extra_parts else ""
        lines.append(f"{day}  {emoji} {cond}  ·  {_fmt_temp(lo)}–{_fmt_temp(hi)}{extra}")
    return "\n".join(lines)


def extract_weather_location(question: str) -> str:
    """Best-effort city name from a weather question."""
    q = question.strip()
    q = WEATHER_DETAIL_RE.sub("", q)
    q = re.sub(
        r"(?i)^(?:what(?:'s|\s+is)?|how(?:'s|\s+is)?|tell me)\s+(?:the\s+)?(?:weather|forecast)\s+(?:in|at|for)\s+",
        "",
        q,
    )
    q = re.sub(r"(?i)\b(?:weather|forecast|please|can you|could you)\b", "", q)
    q = re.sub(
        r"(?i)\b(?:for|in|at|on|the|next|this|tomorrow|tommorow|tomorow|today|days?|day|week|will it rain|rain|rainy)\b",
        "",
        q,
    )
    q = re.sub(r"\b\d{1,2}\b", "", q)
    q = re.sub(r"\s+", " ", q).strip(" ,.")
    return q


def fetch_weather(question: str = "", *, days: int = 0, detail: bool | None = None) -> str:
    city = extract_weather_location(question) if question else ""
    target = parse_forecast_target(question)
    forecast_days = days or parse_forecast_days(question)
    want_detail = parse_weather_detail_mode(question) if detail is None else detail

    if target == "tomorrow" or (days == 1 and TOMORROW_RE.search(question)):
        resolved = resolve_weather_coords(city or None)
        if not resolved:
            return "Could not determine location for weather. Try: set_location Kolkata"
        lat, lon, label = resolved
        if want_detail:
            return fetch_day_detail(lat, lon, label, day_offset=1, hourly_all=True)
        return fetch_day_brief(lat, lon, label, day_offset=1)

    if forecast_days == 1 or target == "today":
        resolved = resolve_weather_coords(city or None)
        if not resolved:
            return "Could not determine location for weather."
        lat, lon, label = resolved
        if want_detail:
            return fetch_day_detail(lat, lon, label, day_offset=0, hourly_all=True)
        return fetch_day_brief(lat, lon, label, day_offset=0)

    if forecast_days > 0:
        return fetch_weather_forecast(forecast_days, city=city or None)

    resolved = resolve_weather_coords(city or None)
    if not resolved:
        return "Could not determine location for weather."
    lat, lon, label = resolved
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&current_weather=true&timezone=auto"
    )
    try:
        data = _open_meteo_get(url)
        cw = data.get("current_weather", {})
        code = cw.get("weathercode")
        place = _clean_location_label(label)
        return (
            f"━━━ Now — {place} ━━━\n\n"
            f"Now      {_fmt_temp(cw.get('temperature'))}  {_weather_emoji(code)}  {wmo_label(code)}\n"
            f"         Wind {cw.get('windspeed')} km/h  ·  {(cw.get('time') or '')[:16].replace('T', ' ')}"
        )
    except Exception as exc:
        return f"Weather fetch failed: {exc}"


def _coords_from_geo_data(data: dict) -> str:
    lat = data.get("latitude") if data.get("latitude") is not None else data.get("lat")
    lon = data.get("longitude") if data.get("longitude") is not None else data.get("lon")
    if lat is not None and lon is not None:
        return f"{lat},{lon}"
    return ""


def _fetch_ip_coords() -> str:
    try:
        req = urllib.request.Request("https://ipinfo.io/loc", headers={"User-Agent": "arka-chat/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            coords = resp.read().decode().strip()
            if coords and "," in coords:
                return coords
    except Exception:
        pass
    try:
        req = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "arka-chat/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return _coords_from_geo_data(data)
    except Exception:
        pass
    return ""


def _ensure_coords(ctx: dict) -> dict:
    if ctx.get("coords"):
        return ctx
    coords = _fetch_ip_coords()
    if coords:
        ctx["coords"] = coords
        save_context(ctx)
    return ctx


def get_live_location(force_refresh: bool = False) -> dict:
    ctx = load_context()
    if not force_refresh and ctx.get("location_string"):
        return _ensure_coords(ctx)

    coords = _fetch_ip_coords()
    if coords:
        ctx["coords"] = coords

    public_ip = "Unknown"
    try:
        req = urllib.request.Request("https://ifconfig.me/ip", headers={"User-Agent": "arka-chat/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            public_ip = resp.read().decode().strip()
    except Exception:
        pass

    for url in (
        f"https://ipapi.co/{public_ip}/json/" if public_ip != "Unknown" else "https://ipapi.co/json/",
        f"http://ip-api.com/json/{public_ip}" if public_ip != "Unknown" else "http://ip-api.com/json/",
    ):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "arka-chat/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            if "city" in data or data.get("status") == "success":
                city = data.get("city", "Unknown")
                region = data.get("region") or data.get("regionName", "")
                country = data.get("country_name") or data.get("country", "")
                loc = f"{city}, {region}, {country}".strip(", ")
                ctx["city"] = city
                ctx["location_string"] = f"{loc} (IP: {public_ip})"
                geo = _coords_from_geo_data(data)
                if geo:
                    ctx["coords"] = geo
                save_context(_ensure_coords(ctx))
                return ctx
        except Exception:
            continue

    ctx["location_string"] = f"Unknown (IP: {public_ip})"
    ctx["city"] = "Unknown"
    save_context(ctx)
    return ctx


def set_location_manual(value: str) -> dict:
    ctx = load_context()
    value = value.strip()
    if len(value) == 6 and value.isdigit():
        ctx["pincode"] = value
    else:
        ctx["city"] = value
        ctx["location_string"] = f"{value} (manual)"
        ctx["coords"] = None
    save_context(ctx)
    return ctx


def normalize_question(question: str) -> str:
    q = " ".join(question.split())
    q = re.sub(r"^/+", "", q).strip()
    for prefix in ("deep_web_answer", "web_answer", "web search"):
        if q.lower().startswith(prefix):
            q = q[len(prefix) :].strip()
    return q


def should_ground_location(query: str) -> bool:
    low = query.lower()
    local_hints = (
        "weather", "forecast", "near me", "nearby", "restaurant", "hospital",
        "atm", "pharmacy", "traffic", "local", "pincode", "pin code",
    )
    if any(h in low for h in local_hints):
        return True
    if extract_pin(query):
        return True
    global_hints = (
        "ipl", "cricket", "winner", " won ", "election", "president",
        "world cup", "fifa", "nba", "nfl", "olympics", "wimbledon",
        "stock", "crypto", "bitcoin", "championship", "final score",
    )
    if any(h in low for h in global_hints):
        return False
    if re.search(r"\bwho\s+(won|wins|beat|defeated)\b", low):
        return False
    return False


def ground_search_query(query: str) -> str:
    query = normalize_question(query)
    if not should_ground_location(query):
        return query
    ctx = load_context()
    pin = extract_pin(query) or ctx.get("pincode")
    if pin:
        ctx["pincode"] = pin
        save_context(ctx)
    city = ctx.get("city") or "Unknown"
    suffixes: list[str] = []
    if city != "Unknown" and city.lower() not in query.lower():
        suffixes.append(str(city))
    if pin and str(pin) not in query:
        suffixes.append(str(pin))
    if suffixes:
        return f"{query} in {' '.join(suffixes)}"
    return query


def should_auto_search(text: str) -> bool:
    low = text.lower()
    if detect_list_request(text):
        return True
    return any(re.search(r"\b" + re.escape(kw) + r"\b", low) for kw in SEARCH_KEYWORDS)


def detect_list_request(question: str) -> int | None:
    """Return requested list size (e.g. top 10 → 10), or None."""
    low = question.lower()
    for pat in (
        r"\btop\s+(\d+)\b",
        r"\b(\d+)\s+(?:best|top|places|things|items|cities|destinations|countries|attractions|sites)\b",
        r"\blist\s+(?:of\s+)?(?:the\s+)?(\d+)\b",
    ):
        m = re.search(pat, low)
        if m:
            n = int(m.group(1))
            if 2 <= n <= 50:
                return n
    word_nums = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twelve": 12}
    m = re.search(r"\btop\s+(five|ten|fifteen|twenty|twelve)\b", low)
    if m:
        return word_nums.get(m.group(1), 10)
    if re.search(r"\b(top|best)\s+(places|destinations|cities|spots|things|attractions|sites)\b", low):
        return 10
    return None


def list_answer_instructions(count: int, prior_items: list[str] | None = None) -> str:
    lines = [
        f"\nIMPORTANT: The user asked for exactly {count} items.",
        f"Provide a numbered list from 1 to {count}, one item per line, "
        "with a short phrase per item. Do not stop early or summarize.",
        "Use Recent chat for context (preferences, facts already established).",
    ]
    if prior_items:
        kept = prior_items[:count]
        lines.append(
            f"\nThis conversation already mentioned {len(kept)} relevant item(s). "
            "Keep valid ones from memory, then add new items from search until you reach "
            f"exactly {count} unique items total. Do not repeat only the old partial list."
        )
        lines.append(
            "CRITICAL: For each prior item below, copy the FULL line including its description "
            "(e.g. 'Agra - home to the iconic Taj Mahal'). Never reduce a prior item to just its name."
        )
        lines.append("Prior items from this chat (reuse verbatim, including descriptions):")
        for i, item in enumerate(kept, 1):
            lines.append(f"  {i}. {item}")
        if len(kept) < count:
            lines.append(
                f"Add {count - len(kept)} more distinct items from search results, "
                "each with a brief description in the same style."
            )
    return "\n".join(lines)


_TOPIC_STOP = frozenset({
    "what", "are", "the", "in", "is", "a", "an", "top", "best", "places", "tell", "me",
    "about", "how", "why", "when", "where", "who", "which", "give", "list", "name",
})


def _topic_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _TOPIC_STOP}


def topic_overlap(question: str, text: str) -> bool:
    tq = _topic_tokens(question)
    tt = _topic_tokens(text)
    if not tq or not tt:
        return False
    shared = tq & tt
    if not shared:
        return False
    return len(shared) / min(len(tq), len(tt)) >= 0.25


def extract_list_items(text: str) -> list[str]:
    items: list[str] = []
    body = re.sub(r"^\[(FROM SEARCH|FROM MEMORY)\]\s*", "", text, flags=re.I)
    for line in body.splitlines():
        m = re.match(r"^\s*\d+\.\s+(.+)$", line.strip())
        if m:
            item = re.sub(r"\*\*([^*]+)\*\*", r"\1", m.group(1)).strip()
            item = re.sub(r"^\*\*|\*\*$", "", item).strip()
            if item:
                items.append(item)
    if not items:
        for m in re.finditer(r"\b\d+\.\s+([^.\n]+?)(?=\s+\d+\.\s+|$)", body):
            item = m.group(1).strip()
            if item and len(item) > 2:
                items.append(item)
    return items


def _list_item_name(item: str) -> str:
    return re.split(r"\s[-–—:]+\s", item.strip(), maxsplit=1)[0].strip().lower()


def _prior_items_by_name(prior_items: list[str]) -> dict[str, str]:
    by_name: dict[str, str] = {}
    for item in prior_items:
        name = _list_item_name(item)
        if name and (name not in by_name or len(item) > len(by_name[name])):
            by_name[name] = item.strip()
    return by_name


def merge_prior_list_details(answer: str, prior_items: list[str]) -> str:
    """Restore full descriptions from memory when the model shortens items to names only."""
    if not prior_items or not answer:
        return answer
    by_name = _prior_items_by_name(prior_items)
    if not by_name:
        return answer

    def enrich_item(body: str) -> str:
        body = body.strip()
        key = _list_item_name(body)
        prior = by_name.get(key)
        if not prior:
            return body
        if body.lower() == key or len(body) < len(prior) * 0.75:
            return prior
        return body

    lines = answer.splitlines()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(\s*\d+\.\s+)(.+)$", line)
        if m:
            out.append(m.group(1) + enrich_item(m.group(2)))
        else:
            out.append(line)

    if not any(re.match(r"^\s*\d+\.\s+", ln) for ln in out):
        def repl(match: re.Match[str]) -> str:
            num, body = match.group(1), match.group(2).strip()
            return f"{num}. {enrich_item(body)}"

        merged = re.sub(r"\b(\d+)\.\s+([^.\d]+?)(?=\s+\d+\.\s+|$)", repl, answer)
        if merged != answer:
            return merged
    return "\n".join(out)


def prior_session_context(question: str) -> tuple[list[str], list[dict]]:
    """Return (prior list items, relevant messages) from chat session."""
    history = load_session()
    prior_items: list[str] = []
    relevant: list[dict] = []
    for msg in reversed(history):
        content = msg.get("content") or ""
        if not content:
            continue
        if not topic_overlap(question, content):
            continue
        relevant.insert(0, msg)
        if msg.get("role") == "assistant" and not prior_items:
            found = extract_list_items(content)
            if found:
                prior_items = found
    return prior_items, relevant


def _format_session_message(msg: dict, question: str, *, default_limit: int = 220) -> str:
    content = str(msg.get("content") or "")
    role = msg.get("role", "user")
    related = topic_overlap(question, content)
    limit = 1200 if related and role == "assistant" else (600 if related else default_limit)
    if len(content) > limit:
        content = content[: limit - 3].rstrip() + "..."
    return f"{role}: {content}"


def detect_error(text: str) -> bool:
    return any(kw in text for kw in ERROR_KEYWORDS)


def detect_math(text: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(integrate|integral|derivative|differentiate|solve|simplify|equation|"
            r"sympy|dx\b|dy\b)\b",
            text,
        )
    )


from arka.llm.cli import llm_complete


def get_intent(prompt: str) -> tuple[str, str]:
    prompt = prompt.strip()
    if not prompt:
        return "ANSWER", ""
    if prompt.startswith("/"):
        return "SEARCH", prompt[1:].strip() or prompt
    low = prompt.lower()
    if detect_error(prompt):
        return "ERROR", prompt
    if "weath" in low:
        return "WEATHER", prompt
    if detect_math(prompt):
        return "CALC", prompt
    if detect_list_request(prompt):
        return "SEARCH", prompt
    if should_auto_search(prompt):
        return "SEARCH", prompt
    # Plain conversational phrases — skip LLM intent (avoids bogus CALC/SEARCH)
    if len(prompt.split()) >= 3:
        return "ANSWER", prompt

    decision = llm_complete(DECISION_PROMPT, prompt, temperature=0.0, task="chat")
    if decision:
        for line in decision.splitlines():
            line = line.strip()
            up = line.upper()
            if up.startswith("SEARCH:"):
                return "SEARCH", prompt
            if up.startswith("CALC:") and detect_math(prompt):
                return "CALC", line.split(":", 1)[-1].strip() or prompt
            if up.startswith("ANSWER:"):
                return "ANSWER", prompt

    if should_auto_search(prompt):
        return "SEARCH", prompt
    return "ANSWER", prompt


def duckduckgo_search(query: str, max_results: int = 5) -> list[dict]:
    try:
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
        results = []
        with DDGS() as client:
            for i, row in enumerate(client.text(query, max_results=max_results)):
                results.append({
                    "id": i,
                    "link": row.get("href"),
                    "title": row.get("title", ""),
                    "snippet": row.get("body", ""),
                })
        return results
    except Exception as exc:
        print(f"Search error: {exc}", file=sys.stderr)
        return []


def _score_search_result(query: str, result: dict) -> int:
    q = query.lower()
    title = (result.get("title") or "").lower()
    snippet = (result.get("snippet") or "").lower()
    link = (result.get("link") or "").lower()
    score = 0
    if "wikipedia.org" in link:
        score += 2
    if re.search(r"\bwho\s+(won|wins)\b", q):
        if any(w in title for w in ("final", "winner", "winners")):
            score += 6
        if "final" in link:
            score += 5
        if "won" in snippet or "winner" in snippet:
            score += 3
        if "season" in title and "final" not in title:
            score -= 4
    for word in re.findall(r"[a-z0-9]{4,}", q):
        if word in title:
            score += 1
        if word in snippet:
            score += 1
    if "points table" in title or "tracker" in title:
        score -= 5
    return score


def _looks_like_raw_scrape(text: str) -> bool:
    if not text:
        return True
    if "Points Table" in text or "Top Stories Latest News" in text:
        return True
    if text.count("|") > 12 or "|---|" in text:
        return True
    if len(text) > 400 and text.lstrip().startswith("[FROM SEARCH]"):
        body = text.split("\n", 1)[-1]
        if body.count("|") > 8:
            return True
    return False


def scrape_url(url: str, timeout: int = 12) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; arka-chat/1.0)"}
    try:
        import trafilatura  # type: ignore

        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded)
            if text:
                return text.strip()
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup  # type: ignore

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        return " ".join(p.get_text() for p in soup.find_all("p")).strip()
    except Exception:
        return ""


def scrape_search_results(query: str, min_words: int = 400, hard_limit: int = 8) -> str:
    query = normalize_question(query)
    grounded = ground_search_query(query)
    results = duckduckgo_search(grounded, max_results=hard_limit)
    if not results:
        return ""

    ranked = sorted(results, key=lambda r: _score_search_result(query, r), reverse=True)
    merged: list[str] = []
    seen: set[str] = set()
    for res in ranked[:hard_limit]:
        link = res.get("link") or ""
        if not link or link in seen:
            continue
        seen.add(link)
        title = res.get("title") or link
        snippet = res.get("snippet") or ""
        header = f"Source: {title}\n{snippet}".strip()
        page = scrape_url(link)
        if page:
            merged.append(f"{header}\n\n{page[:3500]}")
        elif snippet:
            merged.append(header)
        if len(" ".join(merged).split()) >= min_words:
            break
    return "\n\n".join(merged)[:12000]


def snippet_lookup(question: str) -> str:
    params = urllib.parse.urlencode({
        "q": question,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1",
    })
    url = f"https://api.duckduckgo.com/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "arka-chat/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return ""
    parts: list[str] = []
    if data.get("Answer"):
        parts.append(str(data["Answer"]))
    if data.get("AbstractText"):
        parts.append(str(data["AbstractText"]))
    for topic in data.get("RelatedTopics") or []:
        if isinstance(topic, dict) and topic.get("Text"):
            parts.append(str(topic["Text"]))
            break
    return "\n".join(parts)[:2000]


def evaluate_math(expression: str) -> str:
    try:
        import sympy
        from sympy import (
            Eq,
            cos,
            diff,
            expand,
            integrate,
            limit,
            log,
            sin,
            simplify,
            solve,
            sqrt,
            symbols,
            tan,
        )

        x, y, z, a, b, c = symbols("x y z a b c")
        local_dict = {
            "x": x, "y": y, "z": z, "a": a, "b": b, "c": c,
            "symbols": symbols, "solve": solve, "simplify": simplify,
            "Eq": Eq, "diff": diff, "integrate": integrate, "limit": limit, "expand": expand,
            "sin": sin, "cos": cos, "tan": tan, "sqrt": sqrt, "log": log,
        }
        cleaned = expression.replace("^", "**")
        result = eval(cleaned, {"__builtins__": {}}, local_dict)  # noqa: S307
        return str(result)
    except Exception as exc:
        return f"Error: {exc}"


def math_from_question(question: str) -> str:
    q = question.strip()
    m = re.search(r"(?i)integrate\s+(.+?)\s+dx\s*$", q)
    if m:
        return evaluate_math(f"integrate({m.group(1).strip()}, x)")
    m = re.search(r"(?i)differentiate\s+(.+?)\s+with respect to x", q)
    if m:
        return evaluate_math(f"diff({m.group(1).strip()}, x)")
    expr = q
    for pat in (
        r"(?i)(?:integral of)\s+(.+)",
        r"(?i)(?:solve|differentiate|simplify)\s+(.+)",
        r"(?i)(?:calculate|compute|eval)\s+(.+)",
    ):
        m = re.search(pat, q)
        if m:
            expr = m.group(1).strip()
            break
    return evaluate_math(expr)


POI_FILTER_TYPES: dict[str, set[str]] = {
    "food": {"restaurant", "cafe", "fast_food", "food_court", "bakery", "bar", "pub", "biergarten", "ice_cream"},
    "restaurant": {"restaurant", "fast_food", "food_court"},
    "cafe": {"cafe", "coffee_shop"},
    "coffee": {"cafe", "coffee_shop"},
    "hospital": {"hospital", "clinic", "doctors", "pharmacy"},
    "pharmacy": {"pharmacy", "chemist"},
    "atm": {"atm"},
    "bank": {"bank", "atm"},
    "hotel": {"hotel", "hostel", "guest_house", "motel"},
    "mall": {"mall", "supermarket", "department_store", "marketplace"},
    "grocery": {"supermarket", "greengrocer", "convenience", "marketplace"},
    "park": {"park", "garden", "playground"},
}


def _haversine_km(u_lat: float, u_lon: float, p_lat: float, p_lon: float) -> float:
    r = 6371.0
    d_lat = math.radians(p_lat - u_lat)
    d_lon = math.radians(p_lon - u_lon)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(u_lat)) * math.cos(math.radians(p_lat)) * math.sin(d_lon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _poi_distance_km(user_coords: str, poi_coords: str) -> float | None:
    if not user_coords or not poi_coords:
        return None
    try:
        u_lat, u_lon = map(float, user_coords.split(","))
        p_lat, p_lon = map(float, poi_coords.split(","))
    except (TypeError, ValueError):
        return None
    try:
        from geopy.distance import geodesic  # type: ignore

        return float(geodesic((u_lat, u_lon), (p_lat, p_lon)).kilometers)
    except Exception:
        try:
            return float(_haversine_km(u_lat, u_lon, p_lat, p_lon))
        except Exception:
            return None


def relative_bearing(user_coords: str, poi_coords: str) -> str:
    dist = _poi_distance_km(user_coords, poi_coords)
    if dist is None:
        return ""
    try:
        u_lat, u_lon = map(float, user_coords.split(","))
        p_lat, p_lon = map(float, poi_coords.split(","))
        d_lon = math.radians(p_lon - u_lon)
        lat1, lat2 = math.radians(u_lat), math.radians(p_lat)
        y = math.sin(d_lon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
        bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
        return f"{dist:.1f}km {dirs[round(bearing / 45)]}"
    except Exception:
        return ""


def _poi_matches_filter(poi: dict, query: str) -> bool:
    query = (query or "").strip().lower()
    if not query:
        return True
    name = str(poi.get("name") or "").lower()
    kind = str(poi.get("type") or "").lower()
    tokens = re.findall(r"[a-z0-9]+", query)
    for token in tokens:
        types = POI_FILTER_TYPES.get(token)
        if types and kind in types:
            return True
        if token == "food" and any(
            x in name for x in ("food", "restaurant", "cafe", "kitchen", "bistro", "dhaba", "biryani")
        ):
            return True
        if token in name or token in kind or token in kind.replace("_", " "):
            return True
    return False


def map_file(city: str) -> Path:
    slug = city.lower().replace(" ", "_")
    return MAPS_DIR / f"{slug}.json"


def load_map(city: str) -> list[dict]:
    path = map_file(city)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    return []


def download_map(city: str) -> list[dict]:
    ensure_cache()
    print(f"Downloading map data for {city}…", file=sys.stderr)
    query = f"""
    [out:json][timeout:25];
    area["name"="{city}"]["admin_level"~"^[45678]$"]->.a;
    (
      nwr(area.a)[amenity];
      nwr(area.a)[historic];
      nwr(area.a)[tourism];
      nwr(area.a)[leisure];
      nwr(area.a)[shop="mall"];
      nwr(area.a)[shop="supermarket"];
    );
    out center 200;
    """
    try:
        url = "https://overpass-api.de/api/interpreter?" + urllib.parse.urlencode({"data": query})
        req = urllib.request.Request(url, headers={"User-Agent": "arka-chat/1.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
        pois: list[dict] = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            name = tags.get("name")
            if not name:
                continue
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            kind = tags.get("amenity") or tags.get("tourism") or tags.get("historic") or "place"
            pois.append({"name": name, "type": kind, "coords": f"{lat},{lon}" if lat and lon else ""})
        map_file(city).write_text(json.dumps(pois, indent=2), encoding="utf-8")
        print(f"Saved {len(pois)} places for {city}", file=sys.stderr)
        return pois
    except Exception as exc:
        print(f"Map download failed: {exc}", file=sys.stderr)
        return []


def parse_nearby_args(rest: list[str]) -> tuple[str, str]:
    """Return (city, category_filter). Empty city → use live location."""
    if not rest:
        return "", ""
    joined = " ".join(rest).strip()
    low = joined.lower()
    filter_tokens = set(POI_FILTER_TYPES) | {
        "eat",
        "places",
        "place",
        "near",
        "nearby",
        "around",
        "close",
    }
    words = joined.split()
    if len(words) == 1 and words[0].lower() in filter_tokens:
        return "", words[0].lower()
    if len(words) >= 2 and words[0][0:1].isupper() and words[0].lower() not in filter_tokens:
        return words[0], " ".join(words[1:])
    return "", joined


def format_nearby(city: str, limit: int = 15, *, query: str = "") -> str:
    ctx = _ensure_coords(get_live_location())
    pois = load_map(city)
    if not pois:
        pois = download_map(city)
    if not pois:
        return (
            f"No offline map for {city}. Download once while online:\n"
            f"  map_download {city}"
        )
    coords = str(ctx.get("coords") or "")
    filtered = [p for p in pois if _poi_matches_filter(p, query)]
    if query and not filtered:
        filtered = pois

    scored: list[tuple[float, dict, str]] = []
    for p in filtered:
        dist_km = _poi_distance_km(coords, str(p.get("coords") or ""))
        dist_label = relative_bearing(coords, str(p.get("coords") or ""))
        scored.append((dist_km if dist_km is not None else 99999.0, p, dist_label))
    scored.sort(key=lambda row: row[0])

    label = f" ({query})" if query else ""
    header = f"Nearby places in {city}{label} — OpenStreetMap offline"
    if coords:
        header += f"\nFrom your location ({ctx.get('location_string', coords)})"
    else:
        header += "\nSet location for distance: location Kolkata (or allow IP geolocation)"
    lines: list[str] = [header, ""]
    for _dist, p, dist_label in scored[:limit]:
        extra = f" — {dist_label}" if dist_label else ""
        lines.append(f"• {p.get('name')} ({p.get('type', 'place')}){extra}")
    if not lines[2:]:
        lines.append("(no matching places in cached map — try: map_download " + city + ")")
    return "\n".join(lines)


def cleanup_response(raw: str, entity: str = "") -> str:
    system = (
        "Clean up this answer for terminal/TTS: remove disclaimers, repetition, markdown clutter. "
        f"Keep [FROM SEARCH] or [FROM MEMORY] prefix if present. Topic: {entity or 'general'}."
    )
    cleaned = llm_complete(system, raw, temperature=0.0, task="chat")
    return cleaned or raw.strip()


def build_session_context(question: str | None = None) -> str:
    ctx = get_live_location()
    parts = [f"User location: {ctx.get('location_string', 'Unknown')}"]
    if ctx.get("pincode"):
        parts.append(f"PIN: {ctx['pincode']}")
    city = ctx.get("city", "Unknown")
    if city != "Unknown":
        pois = load_map(str(city))
        if pois:
            coords = ctx.get("coords")
            sample = []
            for p in pois[:8]:
                dist = relative_bearing(str(coords or ""), p.get("coords", ""))
                sample.append(f"{p.get('name')} ({dist or 'nearby'})")
            parts.append("Nearby (offline map): " + "; ".join(sample))
    history = load_session()
    if history and question:
        prior_items, relevant = prior_session_context(question)
        if prior_items:
            parts.append(
                "Remembered list from this chat: "
                + "; ".join(prior_items[:12])
            )
        if relevant:
            parts.append(
                "Recent chat:\n"
                + "\n".join(_format_session_message(m, question) for m in relevant[-8:])
            )
        else:
            recent = history[-6:]
            parts.append(
                "Recent chat:\n"
                + "\n".join(_format_session_message(m, question) for m in recent)
            )
    elif history:
        recent = history[-6:]
        parts.append(
            "Recent chat:\n"
            + "\n".join(
                f"{m.get('role', 'user')}: {(m.get('content') or '')[:220]}"
                for m in recent
            )
        )
    return "\n".join(parts)


def answer_question(
    question: str,
    *,
    deep: bool = False,
    use_session: bool = True,
    cleanup: bool = True,
) -> tuple[str, str]:
    """Returns (provenance, answer_text). provenance: search|memory|calc|weather|error"""
    question = normalize_question(" ".join(question.split()))
    try:
        from arka.core.security import sanitize_web_context, verify_web_query
    except ImportError:
        verify_web_query = None  # type: ignore[assignment,misc]
        sanitize_web_context = None  # type: ignore[assignment,misc]

    if verify_web_query is not None:
        gate = verify_web_query(question)
        if gate.status == "block":
            msg = f"[BLOCKED] {gate.reason}"
            if use_session:
                session_append("user", question)
                session_append("assistant", msg)
            return "blocked", msg

    action, data = get_intent(question)
    list_n = detect_list_request(question)
    prior_items: list[str] = []
    if use_session:
        prior_items, _ = prior_session_context(question)
    list_extra = list_answer_instructions(list_n, prior_items) if list_n else ""
    memory_hint = (
        "\nBuild on Recent chat and remembered facts when relevant; "
        "do not ignore established context from this conversation."
    )

    if action == "ERROR":
        system = (
            "You are a Linux/Python debugging assistant. Explain the error clearly, "
            "likely cause, and 2-3 concrete fix steps. Start with [FROM MEMORY]."
        )
        user = f"Error report:\n{data}\n\nExplain and suggest fixes."
        answer = llm_complete(system, user, task="chat")
        if use_session:
            session_append("user", question)
            session_append("assistant", answer)
        return "error", answer or "Could not analyze error."

    if action == "CALC":
        result = math_from_question(data)
        system = ASSISTANT_SYSTEM + "\nExplain the math result clearly. Start with [FROM MEMORY]."
        user = f"Question: {question}\nSymPy result: {result}"
        answer = llm_complete(system, user, task="chat")
        if not answer:
            answer = f"[FROM MEMORY] Result: {result}"
        if use_session:
            session_append("user", question)
            session_append("assistant", answer)
        return "calc", answer

    if action == "WEATHER":
        wx = fetch_weather(question)
        system = ASSISTANT_SYSTEM + "\nSummarize weather data conversationally. Start with [FROM MEMORY]."
        user = f"Weather data:\n{wx}\n\nUser asked: {question}"
        answer = llm_complete(system, user, task="chat")
        if not answer:
            answer = f"[FROM MEMORY]\n{wx}"
        if use_session:
            session_append("user", question)
            session_append("assistant", answer)
        return "weather", answer

    context_block = build_session_context(question) if use_session else ""
    web_context = ""

    snippet = snippet_lookup(question)

    if action == "SEARCH" or deep:
        print("Searching web…", file=sys.stderr)
        search_q = ground_search_query(question)
        raw_web = scrape_search_results(search_q)
        if raw_web:
            try:
                from arka.stock.turboquant_rag import retrieve_web_context, use_turboquant

                if use_turboquant():
                    web_context = retrieve_web_context(raw_web, question)
                else:
                    web_context = raw_web
            except Exception:
                web_context = raw_web
        else:
            web_context = ""
        if not web_context:
            web_context = snippet

    if sanitize_web_context is not None:
        if web_context:
            web_context, _san_warnings = sanitize_web_context(web_context)
            if _san_warnings:
                print(
                    f"Sanitized {len(_san_warnings)} suspicious line(s) from web results.",
                    file=sys.stderr,
                )
        if snippet:
            snippet, _ = sanitize_web_context(snippet)

    if web_context:
        system = ASSISTANT_SYSTEM
        length_hint = (list_extra or "\nGive a direct answer using the search results.") + memory_hint
        user = (
            f"{context_block}\n\n"
            f"SEARCH RESULTS:\n---\n{web_context}\n---\n\n"
            f"Question: {question}\n"
            f"{length_hint}\n"
            "Start with [FROM SEARCH]. Do not copy tables or navigation text."
        )
        answer = llm_complete(system, user, task="chat")
        prov = "search"
    else:
        system = ASSISTANT_SYSTEM
        user = f"{context_block}\n\n"
        if snippet:
            user += f"Web snippet:\n{snippet}\n\n"
        length_hint = (list_extra or "\nAnswer clearly and completely.") + memory_hint
        user += f"Question: {question}\n{length_hint}\nStart with [FROM MEMORY] unless snippet was decisive."
        answer = llm_complete(system, user, task="chat")
        prov = "memory"

    if _looks_like_raw_scrape(answer or ""):
        retry_ctx = snippet or (web_context[:2000] if web_context else "")
        if retry_ctx:
            retry_hint = (list_extra or "Answer clearly. Start with [FROM SEARCH].") + memory_hint
            answer = llm_complete(
                ASSISTANT_SYSTEM,
                f"{context_block}\n\nQuestion: {question}\n\nSources:\n{retry_ctx}\n\n{retry_hint}",
                temperature=0.0,
                task="chat",
            )

    if not answer and snippet:
        retry_hint = (list_extra or "Answer clearly. Start with [FROM SEARCH].") + memory_hint
        answer = llm_complete(
            ASSISTANT_SYSTEM,
            f"{context_block}\n\nQuestion: {question}\n\nWeb snippet:\n{snippet}\n\n{retry_hint}",
            temperature=0.0,
            task="chat",
        )
    if not answer and web_context:
        retry_hint = (list_extra or "Extract the answer. Start with [FROM SEARCH].") + memory_hint
        answer = llm_complete(
            ASSISTANT_SYSTEM,
            f"{context_block}\n\nQuestion: {question}\n\nExtract the answer from:\n{web_context[:2500]}\n\n{retry_hint}",
            temperature=0.0,
            task="chat",
        )
    if not answer:
        answer = "Could not generate an answer (check GEMINI_API_KEY, GROQ_API_KEY, or ollama serve)."

    if list_n and answer:
        answer = re.sub(r"\s+Sources:\s*[-–].*$", "", answer, flags=re.I | re.S).strip()
        if prior_items:
            answer = merge_prior_list_details(answer, prior_items)

    if cleanup and len(answer) > 300 and not _looks_like_raw_scrape(answer) and not list_n:
        answer = cleanup_response(answer, question)

    if use_session:
        session_append("user", question)
        session_append("assistant", answer)

    return prov, answer


def queue_add(task: str) -> None:
    q = load_json(QUEUE_FILE, [])
    if not isinstance(q, list):
        q = []
    q.append({"task": task, "added": time.time(), "status": "pending"})
    save_json(QUEUE_FILE, q)


def queue_list() -> list[dict]:
    q = load_json(QUEUE_FILE, [])
    return q if isinstance(q, list) else []


def queue_run_all() -> None:
    q = queue_list()
    results = load_json(QUEUE_RESULTS_FILE, [])
    if not isinstance(results, list):
        results = []
    pending = [item for item in q if item.get("status") == "pending"]
    for item in pending:
        task = item.get("task", "")
        print(f"━━━ Deep queue: {task} ━━━", file=sys.stderr)
        prov, answer = answer_question(task, deep=True, use_session=False, cleanup=True)
        item["status"] = "done"
        item["finished"] = time.time()
        results.append({"task": task, "provenance": prov, "answer": answer, "finished": item["finished"]})
        print(answer)
    save_json(QUEUE_FILE, q)
    save_json(QUEUE_RESULTS_FILE, results[-30:])


def queue_show_results() -> None:
    results = load_json(QUEUE_RESULTS_FILE, [])
    if not isinstance(results, list) or not results:
        print("No completed deep-queue results.")
        return
    for row in results[-5:]:
        print(f"━━━ {row.get('task', '?')} ━━━")
        print(row.get("answer", ""))
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka chat engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("session-reset", help="Clear chat session and location context")

    p_intent = sub.add_parser("intent", help="Print ACTION\\tdata")
    p_intent.add_argument("question")

    p_ask = sub.add_parser("ask", help="Answer a question")
    p_ask.add_argument("question", nargs="+")
    p_ask.add_argument("--deep", action="store_true")
    p_ask.add_argument("--no-session", action="store_true")
    p_ask.add_argument("--no-cleanup", action="store_true")

    p_calc = sub.add_parser("calc", help="SymPy calculation")
    p_calc.add_argument("expression", nargs="+")

    p_loc = sub.add_parser("location", help="Show or set location")
    p_loc.add_argument("value", nargs="?", default="")
    p_loc.add_argument("--refresh", action="store_true")

    p_wx = sub.add_parser("weather", help="Current weather or N-day forecast (Open-Meteo)")
    p_wx.add_argument("query", nargs="*", default=[])
    p_wx.add_argument("-d", "--days", type=int, default=0, help="Forecast length 1–16 days")
    p_wx.add_argument("-l", "--location", default="", help="City or place name")
    p_wx.add_argument("--detail", action="store_true", help="Hour-by-hour breakdown for today/tomorrow")

    p_map = sub.add_parser("map", help="Offline city map")
    p_map_sub = p_map.add_subparsers(dest="map_cmd", required=True)
    p_map_dl = p_map_sub.add_parser("download")
    p_map_dl.add_argument("city")
    p_map_ls = p_map_sub.add_parser("list")
    p_map_ls.add_argument("city", nargs="?", default="")

    p_near = sub.add_parser("nearby", help="List nearby POIs from offline map")
    p_near.add_argument("rest", nargs="*", default=[])

    p_deep = sub.add_parser("deep-context", help="Scrape web context only (stdout)")
    p_deep.add_argument("question", nargs="+")

    p_err = sub.add_parser("error-explain", help="Explain a traceback/error")
    p_err.add_argument("text", nargs="+")

    p_q = sub.add_parser("queue", help="Deep background queue")
    p_q_sub = p_q.add_subparsers(dest="queue_cmd", required=True)
    p_q_sub.add_parser("list")
    p_q_sub.add_parser("run")
    p_q_sub.add_parser("results")
    p_q_add = p_q_sub.add_parser("add")
    p_q_add.add_argument("task", nargs="+")

    args = parser.parse_args()
    ensure_cache()

    if args.cmd == "session-reset":
        session_reset()
        print("Session reset.")
        return 0

    if args.cmd == "intent":
        action, data = get_intent(args.question)
        print(f"{action}\t{data}")
        return 0

    if args.cmd == "ask":
        question = " ".join(args.question)
        _, answer = answer_question(
            question,
            deep=args.deep,
            use_session=not args.no_session,
            cleanup=not args.no_cleanup,
        )
        print(answer)
        return 0

    if args.cmd == "calc":
        print(math_from_question(" ".join(args.expression)))
        return 0

    if args.cmd == "location":
        if args.refresh or not args.value:
            ctx = get_live_location(force_refresh=args.refresh)
            print(ctx.get("location_string", "Unknown"))
            if ctx.get("pincode"):
                print(f"PIN: {ctx['pincode']}")
            return 0
        ctx = set_location_manual(args.value)
        print(f"Location updated: {ctx.get('location_string') or ctx.get('city')}")
        if ctx.get("pincode"):
            print(f"PIN: {ctx['pincode']}")
        return 0

    if args.cmd == "weather":
        query = " ".join(args.query).strip()
        if args.location:
            query = f"{query} {args.location}".strip() if query else args.location
        days = args.days or parse_forecast_days(query)
        detail = True if args.detail else None
        print(fetch_weather(query, days=days, detail=detail))
        return 0

    if args.cmd == "map":
        city = args.city if args.map_cmd == "download" else (args.city or get_live_location().get("city", ""))
        if not city or city == "Unknown":
            print("No city. Use: map download Kolkata", file=sys.stderr)
            return 1
        if args.map_cmd == "download":
            pois = download_map(city)
            print(f"{len(pois)} places saved for {city}")
            return 0
        pois = load_map(city)
        for p in pois[:30]:
            print(f"• {p.get('name')} — {p.get('type', 'place')}")
        return 0

    if args.cmd == "nearby":
        city_arg, query = parse_nearby_args(list(args.rest or []))
        city = city_arg or get_live_location().get("city", "Unknown")
        if city == "Unknown":
            print("Unknown city. Set with: location Kolkata", file=sys.stderr)
            return 1
        print(format_nearby(str(city), query=query))
        return 0

    if args.cmd == "deep-context":
        raw = scrape_search_results(" ".join(args.question))
        try:
            from arka.stock.turboquant_rag import retrieve_web_context, use_turboquant

            if use_turboquant() and raw:
                print(retrieve_web_context(raw, " ".join(args.question)))
            else:
                print(raw)
        except Exception:
            print(raw)
        return 0

    if args.cmd == "error-explain":
        text = " ".join(args.text)
        _, answer = answer_question(text, deep=False, use_session=True)
        print(answer)
        return 0

    if args.cmd == "queue":
        if args.queue_cmd == "add":
            queue_add(" ".join(args.task))
            print("Queued.")
            return 0
        if args.queue_cmd == "list":
            for i, item in enumerate(queue_list(), 1):
                print(f"{i}. [{item.get('status', '?')}] {item.get('task', '')}")
            return 0
        if args.queue_cmd == "run":
            queue_run_all()
            return 0
        if args.queue_cmd == "results":
            queue_show_results()
            return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
