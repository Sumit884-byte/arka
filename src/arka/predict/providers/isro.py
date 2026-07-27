"""ISRO MOSDAC integration — search metadata; rainfall charts via Open-Meteo fallback."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MOSDAC_SEARCH_HINT = "https://mosdac.gov.in/downloadapi-manual"
KNOWN_DATASETS = {
    "gsmap_rain": {
        "name": "GSMaP_ISRO Rain",
        "dataset_id": "GSMaP_ISRO_RAIN",
        "description": "IMD gauge-adjusted satellite rainfall (0.1°, hourly, global, 2000+)",
    },
    "saphir_rain": {
        "name": "Bayesian MT-SAPHIR rainfall",
        "dataset_id": "MT_SAPHIR_RAIN",
        "description": "Microwave sounder rainfall (tropical, SAC/ISRO)",
    },
}


def mosdac_configured() -> bool:
    return bool(os.environ.get("MOSDAC_USER", "").strip() and os.environ.get("MOSDAC_PASSWORD", "").strip())


def mosdac_status() -> str:
    if mosdac_configured():
        return f"MOSDAC credentials set — use mdapi client for HDF5 archives ({MOSDAC_SEARCH_HINT})"
    return (
        "MOSDAC not configured. Set MOSDAC_USER and MOSDAC_PASSWORD in .env for ISRO satellite archive "
        f"downloads ({MOSDAC_SEARCH_HINT}). Charts use Open-Meteo satellite-assimilated rainfall forecasts."
    )


def search_mosdac(dataset_id: str, *, start: str = "", end: str = "", count: int = 5) -> list[dict[str, Any]]:
    """Best-effort MOSDAC OpenAPI search when credentials are present."""
    if not mosdac_configured():
        return []
    base = os.environ.get("MOSDAC_API_BASE", "https://mosdac.gov.in").rstrip("/")
    params: dict[str, str] = {"datasetId": dataset_id, "count": str(min(count, 100))}
    if start:
        params["startTime"] = start
    if end:
        params["endTime"] = end
    url = f"{base}/api/datasets/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "arka-predict/1.0"},
        method="GET",
    )
    user = os.environ.get("MOSDAC_USER", "")
    password = os.environ.get("MOSDAC_PASSWORD", "")
    import base64

    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return payload.get("results") or payload.get("data") or []
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        pass
    return []


def isro_rainfall_context(query: str) -> str:
    lines = ["[ISRO / MOSDAC rainfall context]", mosdac_status()]
    for key, meta in KNOWN_DATASETS.items():
        lines.append(f"- {meta['name']}: {meta['description']}")
    if mosdac_configured():
        ds = os.environ.get("MOSDAC_DATASET_ID", KNOWN_DATASETS["gsmap_rain"]["dataset_id"])
        hits = search_mosdac(ds, count=3)
        if hits:
            lines.append(f"Recent MOSDAC files for {ds}: {len(hits)} match(es)")
        else:
            lines.append(f"MOSDAC search for {ds}: no results (check dataset ID / API base)")
    return "\n".join(lines)
