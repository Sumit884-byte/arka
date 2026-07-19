"""Astronomy lookups — bundled catalog, moon phase, ISS passes (Open Notify)."""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; Arka/1.0)"
OPEN_NOTIFY_BASE = "http://api.open-notify.org"
SYNODIC_MONTH = 29.530588853

_OBJECTS_CACHE: dict[str, Any] | None = None


def _skill_root() -> Path:
    return Path(__file__).resolve().parent


def load_objects_index() -> dict[str, Any]:
    global _OBJECTS_CACHE
    if _OBJECTS_CACHE is not None:
        return _OBJECTS_CACHE
    path = _skill_root() / "objects.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid objects.json")
    _OBJECTS_CACHE = data
    return data


def _normalize_name(text: str) -> str:
    t = re.sub(r"[^\w\s-]", " ", text.lower())
    return " ".join(t.split())


def match_object(query: str) -> dict[str, Any] | None:
    """Return bundled object entry matching name or alias."""
    q = _normalize_name(query)
    if not q:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for entry in load_objects_index().get("objects") or []:
        if not isinstance(entry, dict):
            continue
        candidates = [entry.get("id", ""), entry.get("name", "")]
        candidates.extend(entry.get("aliases") or [])
        for raw in candidates:
            alias = _normalize_name(str(raw))
            if not alias:
                continue
            if alias == q or alias in q or q in alias:
                score = len(alias)
                if best is None or score > best[0]:
                    best = (score, entry)
    return best[1] if best else None


def list_catalog(kind: str = "all") -> list[dict[str, Any]]:
    """List bundled planets/galaxies together without an LLM call."""
    key = (kind or "all").lower().strip()
    if key not in {"all", "planets", "galaxies"}:
        raise ValueError("kind must be all, planets, or galaxies")
    rows = []
    for entry in load_objects_index().get("objects") or []:
        typ = str(entry.get("type") or "").lower()
        if key == "planets" and "planet" not in typ:
            continue
        if key == "galaxies" and "galaxy" not in typ:
            continue
        if key == "all" and "planet" not in typ and "galaxy" not in typ:
            continue
        rows.append(entry)
    return rows


def format_catalog(kind: str = "all") -> str:
    rows = list_catalog(kind)
    title = {"all": "Planets and galaxies", "planets": "Planets", "galaxies": "Galaxies"}[kind]
    lines = [f"{title} ({len(rows)}):"]
    for row in rows:
        lines.append(f"- {row.get('name', row.get('id', 'unknown'))} — {row.get('type', 'object')}")
    lines.append("Source: Arka astronomy catalog (use astronomy what <name> for details)")
    return "\n".join(lines)


def julian_date(dt: datetime) -> float:
    dt = dt.astimezone(timezone.utc)
    y = dt.year
    m = dt.month
    d = (
        dt.day
        + (dt.hour + dt.minute / 60 + dt.second / 3600 + dt.microsecond / 3.6e9) / 24
    )
    if m <= 2:
        y -= 1
        m += 12
    a = int(y / 100)
    b = 2 - a + int(a / 4)
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def moon_phase(dt: datetime | None = None) -> dict[str, Any]:
    """Compute lunar phase from synodic month (Meeus-style approximation)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    jd = julian_date(dt)
    days_since_new = (jd - 2451549.5) % SYNODIC_MONTH
    fraction = days_since_new / SYNODIC_MONTH
    illumination = round(
        (1 - math.cos(2 * math.pi * fraction)) / 2 * 100, 1
    )

    if fraction < 0.03 or fraction >= 0.97:
        name = "New Moon"
        emoji = "🌑"
    elif fraction < 0.22:
        name = "Waxing Crescent"
        emoji = "🌒"
    elif fraction < 0.28:
        name = "First Quarter"
        emoji = "🌓"
    elif fraction < 0.47:
        name = "Waxing Gibbous"
        emoji = "🌔"
    elif fraction < 0.53:
        name = "Full Moon"
        emoji = "🌕"
    elif fraction < 0.72:
        name = "Waning Gibbous"
        emoji = "🌖"
    elif fraction < 0.78:
        name = "Last Quarter"
        emoji = "🌗"
    else:
        name = "Waning Crescent"
        emoji = "🌘"

    next_new = dt + timedelta(days=SYNODIC_MONTH - days_since_new)
    next_full_days = (
        (0.5 - fraction) % 1.0
    ) * SYNODIC_MONTH
    next_full = dt + timedelta(days=next_full_days)

    return {
        "phase_name": name,
        "emoji": emoji,
        "illumination_percent": illumination,
        "age_days": round(days_since_new, 1),
        "datetime_utc": dt.strftime("%Y-%m-%d %H:%M UTC"),
        "next_new_moon_utc": next_new.strftime("%Y-%m-%d %H:%M UTC"),
        "next_full_moon_utc": next_full.strftime("%Y-%m-%d %H:%M UTC"),
    }


def _http_json(url: str, *, timeout: float = 15.0) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def resolve_coordinates(location: str = "") -> tuple[float, float, str]:
    """Resolve lat/lon from explicit coords, city name, saved context, or IP."""
    loc = location.strip()
    if loc:
        m = re.match(r"^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$", loc)
        if m:
            return float(m.group(1)), float(m.group(2)), f"{m.group(1)}, {m.group(2)}"

    if loc:
        try:
            from geopy.geocoders import Nominatim  # type: ignore

            geo = Nominatim(user_agent=USER_AGENT)
            hit = geo.geocode(loc, timeout=10)
            if hit is not None:
                return float(hit.latitude), float(hit.longitude), str(hit.address)
        except Exception:
            pass

    try:
        from arka.agent.chat import get_live_location

        ctx = get_live_location()
        coords = (ctx.get("coords") or "").strip()
        if coords and "," in coords:
            lat_s, lon_s = coords.split(",", 1)
            label = str(ctx.get("location_string") or ctx.get("city") or coords)
            return float(lat_s), float(lon_s), label
    except Exception:
        pass

    return 28.6139, 77.2090, "Delhi, India (default)"


def fetch_iss_position() -> dict[str, Any] | None:
    return _http_json(f"{OPEN_NOTIFY_BASE}/iss-now.json")


def fetch_iss_passes(
    lat: float, lon: float, *, passes: int = 5
) -> dict[str, Any] | None:
    params = urllib.parse.urlencode(
        {"lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "n": passes}
    )
    return _http_json(f"{OPEN_NOTIFY_BASE}/iss-pass.json?{params}")


def format_object(entry: dict[str, Any], *, source: str = "bundled") -> str:
    lines = [f"{entry.get('name', 'Object')}"]
    obj_type = entry.get("type")
    if obj_type:
        lines.append(f"Type: {obj_type}")
    constellation = entry.get("constellation")
    if constellation and constellation != "—":
        lines.append(f"Constellation: {constellation}")
    mag = entry.get("magnitude")
    if mag is not None:
        lines.append(f"Apparent magnitude: {mag}")
    dist = entry.get("distance_ly")
    if dist is not None and dist:
        if dist >= 1000:
            lines.append(f"Distance: ~{dist / 1000:.2f} million ly")
        else:
            lines.append(f"Distance: ~{dist} ly")
    spec = entry.get("spectral_type")
    if spec and spec != "—":
        lines.append(f"Spectral type: {spec}")
    ra = entry.get("ra")
    dec = entry.get("dec")
    if ra and ra != "—":
        lines.append(f"Coordinates (J2000): RA {ra}, Dec {dec}")
    desc = entry.get("description")
    if desc:
        lines.append("")
        lines.append(str(desc))
    lines.append(f"\nSource: {source}")
    return "\n".join(lines)


def lookup_object(query: str) -> str:
    entry = match_object(query)
    if entry:
        return format_object(entry, source="Arka astronomy catalog")

    return (
        f"No bundled match for: {query}\n"
        "Try a bright star (Sirius, Betelgeuse), planet (Mars, Jupiter), "
        "or constellation (Orion).\n"
        "Source: Arka astronomy catalog"
    )


def format_moon_report(dt: datetime | None = None) -> str:
    info = moon_phase(dt)
    lines = [
        f"Moon phase {info['emoji']} {info['phase_name']}",
        f"Date/time: {info['datetime_utc']}",
        f"Illumination: {info['illumination_percent']}%",
        f"Lunar age: {info['age_days']} days since new moon",
        f"Next full moon: {info['next_full_moon_utc']}",
        f"Next new moon: {info['next_new_moon_utc']}",
        "\nSource: local synodic calculation (Jean Meeus / Astronomical Algorithms)",
    ]
    return "\n".join(lines)


def format_iss_report(location: str = "") -> str:
    lat, lon, label = resolve_coordinates(location)
    lines = [f"ISS visibility for {label} ({lat:.4f}, {lon:.4f})"]

    pos = fetch_iss_position()
    if pos and pos.get("message") == "success":
        iss = pos.get("iss_position") or {}
        ts = pos.get("timestamp")
        when = (
            datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if ts
            else "now"
        )
        lines.append(
            f"\nCurrent position ({when}): "
            f"lat {iss.get('latitude', '?')}, lon {iss.get('longitude', '?')}"
        )
    else:
        lines.append("\nCurrent position: unavailable (offline or Open Notify down)")

    passes = fetch_iss_passes(lat, lon)
    if passes and passes.get("message") == "success":
        rows = passes.get("response") or []
        if rows:
            lines.append(f"\nUpcoming passes ({len(rows)}):")
            for i, row in enumerate(rows, 1):
                risetime = row.get("risetime")
                duration = row.get("duration")
                if risetime:
                    t = datetime.fromtimestamp(int(risetime), tz=timezone.utc)
                    dur = f"{duration}s" if duration else "?"
                    lines.append(
                        f"  {i}. {t.strftime('%a %Y-%m-%d %H:%M UTC')} — duration {dur}"
                    )
        else:
            lines.append("\nNo upcoming passes in the next few orbits.")
    else:
        lines.append(
            "\nPass times: unavailable offline. "
            "Bundled catalog still works; retry when online."
        )

    lines.append("\nSource: Open Notify API (http://open-notify.org)")
    return "\n".join(lines)
