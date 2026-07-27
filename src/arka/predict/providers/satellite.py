"""Satellite pass predictions (ISS via Open Notify)."""

from __future__ import annotations

from arka.predict.domains import extract_location


def _astro_lib():
    try:
        from arka.skills.astronomy import lib as astro

        return astro
    except ImportError:
        from arka.agent.astronomy import _load_lib

        return _load_lib()


def format_satellite_passes(query: str) -> str:
    loc = extract_location(query)
    astro = _astro_lib()
    return astro.format_iss_report(loc or "")
