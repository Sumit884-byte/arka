"""Metallurgy lookups — bundled alloys, AlloyFYI API, heat-treatment flows."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; Arka/1.0)"
ALLOYFYI_SEARCH = "https://alloyfyi.com/api/v1/search/"
ALLOYFYI_DETAIL = "https://alloyfyi.com/api/v1/alloys/{slug}/"

_ALLOYS_CACHE: dict[str, Any] | None = None
_HEAT_CACHE: dict[str, Any] | None = None


def _skill_root() -> Path:
    return Path(__file__).resolve().parent


def load_alloys_index() -> dict[str, Any]:
    global _ALLOYS_CACHE
    if _ALLOYS_CACHE is not None:
        return _ALLOYS_CACHE
    path = _skill_root() / "alloys.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid alloys.json")
    _ALLOYS_CACHE = data
    return data


def load_heat_treatments() -> dict[str, Any]:
    global _HEAT_CACHE
    if _HEAT_CACHE is not None:
        return _HEAT_CACHE
    path = _skill_root() / "heat_treatments.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid heat_treatments.json")
    _HEAT_CACHE = data
    return data


def _normalize_topic(text: str) -> str:
    t = re.sub(r"[^\w\s-]", " ", text.lower())
    return " ".join(t.split())


def match_alloy(query: str) -> dict[str, Any] | None:
    q = _normalize_topic(query)
    if not q:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for entry in load_alloys_index().get("alloys") or []:
        if not isinstance(entry, dict):
            continue
        candidates = [entry.get("id", ""), entry.get("name", "")]
        candidates.extend(entry.get("aliases") or [])
        for raw in candidates:
            alias = _normalize_topic(str(raw))
            if not alias:
                continue
            if alias == q or alias in q or q in alias:
                score = len(alias)
                if best is None or score > best[0]:
                    best = (score, entry)
    return best[1] if best else None


def match_heat_treatment(topic: str) -> dict[str, Any] | None:
    topic_norm = _normalize_topic(topic)
    if not topic_norm:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for entry in load_heat_treatments().get("treatments") or []:
        if not isinstance(entry, dict):
            continue
        candidates = [entry.get("id", ""), entry.get("title", "")]
        candidates.extend(entry.get("aliases") or [])
        for raw in candidates:
            alias = _normalize_topic(str(raw))
            if not alias:
                continue
            if alias == topic_norm or alias in topic_norm or topic_norm in alias:
                score = len(alias)
                if best is None or score > best[0]:
                    best = (score, entry)
    return best[1] if best else None


def _section_lines(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    lines = [f"## {title}"]
    lines.extend(f"{i}. {item}" for i, item in enumerate(items, 1))
    return lines


def format_heat_treatment_flow(entry: dict[str, Any]) -> str:
    title = str(entry.get("title") or entry.get("id") or "Heat treatment")
    blocks: list[str] = [f"## {title}"]
    blocks.extend(_section_lines("Materials", list(entry.get("materials") or [])))
    blocks.extend(_section_lines("Safety", list(entry.get("safety") or [])))
    blocks.extend(_section_lines("Steps", list(entry.get("steps") or [])))
    refs = list(entry.get("references") or [])
    if refs:
        blocks.append("## References")
        blocks.extend(f"{i}. {url}" for i, url in enumerate(refs, 1))
    source = str(entry.get("source") or "Arka metallurgy heat-treatment index")
    blocks.append(f"\n*Source: {source}*")
    return "\n".join(blocks).strip()


def format_alloy(entry: dict[str, Any], *, source: str = "bundled") -> str:
    lines = [entry.get("name", "Alloy")]
    family = entry.get("family")
    if family:
        lines.append(f"Family: {family}")

    comp = entry.get("composition") or {}
    if comp:
        lines.append("\nComposition:")
        for elem, pct in comp.items():
            lines.append(f"  {elem}: {pct}")

    props = entry.get("properties") or {}
    if props:
        lines.append("\nProperties:")
        labels = {
            "density_g_cm3": "Density (g/cm³)",
            "tensile_strength_mpa": "Tensile strength (MPa)",
            "yield_strength_mpa": "Yield strength (MPa)",
            "elongation_percent": "Elongation (%)",
            "hardness_brinell": "Hardness (HB)",
            "melting_point_c": "Melting point (°C)",
            "compressive_strength_mpa": "Compressive strength (MPa)",
        }
        for key, label in labels.items():
            val = props.get(key)
            if val is not None:
                lines.append(f"  {label}: {val}")

    apps = entry.get("applications") or []
    if apps:
        lines.append("\nApplications: " + ", ".join(apps))

    notes = entry.get("notes")
    if notes:
        lines.append(f"\nNotes: {notes}")

    lines.append(f"\nSource: {source}")
    return "\n".join(lines)


def _http_json(url: str, *, timeout: float = 20.0) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def fetch_alloyfyi(query: str) -> dict[str, Any] | None:
    """Search AlloyFYI and return first alloy detail record."""
    q = urllib.parse.quote(query.strip())
    search = _http_json(f"{ALLOYFYI_SEARCH}?q={q}")
    if not search:
        return None
    results = search.get("results") or []
    if not results:
        return None
    slug = (results[0].get("slug") or "").strip()
    if not slug:
        return None
    return _http_json(ALLOYFYI_DETAIL.format(slug=urllib.parse.quote(slug)))


def format_alloyfyi(data: dict[str, Any]) -> str:
    lines = [data.get("name") or "Alloy"]
    if data.get("family_name"):
        lines.append(f"Family: {data['family_name']}")
    comp = data.get("composition") or {}
    if comp:
        lines.append("\nComposition:")
        for k, v in comp.items():
            if v and str(v).strip() not in ("–", "-"):
                lines.append(f"  {k}: {v}")
    prop_bits: list[str] = []
    for key, label in (
        ("tensile_strength_mpa", "Tensile (MPa)"),
        ("yield_strength_mpa", "Yield (MPa)"),
        ("elongation_percent", "Elongation (%)"),
        ("hardness_brinell", "HB"),
        ("density_g_cm3", "Density (g/cm³)"),
        ("melting_point_c", "Melting (°C)"),
    ):
        val = data.get(key)
        if val is not None and str(val).strip():
            prop_bits.append(f"{label}: {val}")
    if prop_bits:
        lines.append("\nProperties: " + " · ".join(prop_bits))
    apps = data.get("applications") or []
    if apps:
        lines.append("\nApplications: " + ", ".join(str(a) for a in apps[:8]))
    desc = (data.get("description") or data.get("summary") or "").strip()
    if desc:
        lines.append("")
        lines.append(desc[:800] + ("…" if len(desc) > 800 else ""))
    lines.append("\nSource: AlloyFYI API (https://alloyfyi.com)")
    return "\n".join(lines)


def lookup_alloy(query: str, *, mode: str = "properties") -> str:
    entry = match_alloy(query)
    if entry:
        return format_alloy(entry)

    remote = fetch_alloyfyi(query)
    if remote:
        return format_alloyfyi(remote)

    return (
        f"No match for alloy: {query}\n"
        "Try: 304, 316, brass, bronze, 6061-T6, 4140, Ti-6Al-4V.\n"
        "Source: Arka metallurgy catalog (offline) / AlloyFYI when online"
    )


def lookup_composition(query: str) -> str:
    entry = match_alloy(query)
    if entry:
        comp = entry.get("composition") or {}
        name = entry.get("name", query)
        if not comp:
            return f"No composition data for {name}"
        lines = [f"Composition of {name}:"]
        for elem, pct in comp.items():
            lines.append(f"  {elem}: {pct}")
        lines.append("\nSource: Arka metallurgy catalog")
        return "\n".join(lines)

    remote = fetch_alloyfyi(query)
    if remote and remote.get("composition"):
        return format_alloyfyi(remote)

    return lookup_alloy(query, mode="composition")


def lookup_heat_treatment(topic: str) -> str:
    entry = match_heat_treatment(topic)
    if entry:
        return format_heat_treatment_flow(entry)
    return (
        f"No bundled heat-treatment flow for: {topic}\n"
        "Try: aluminum 6061, 4140 quench and temper, 304 anneal, brass stress relief.\n"
        "Or: arka flow heat treatment of <alloy> (LLM fallback)"
    )


def resolve_bundled_heat_flow(topic: str) -> tuple[str, str] | None:
    entry = match_heat_treatment(topic)
    if not entry:
        return None
    return format_heat_treatment_flow(entry), "bundled"
