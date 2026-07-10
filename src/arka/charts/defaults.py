"""User-configured default data points per chart kind (~/.config/arka/charts.yaml)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

CHART_KINDS: tuple[str, ...] = (
    "scatter",
    "bar",
    "pie",
    "histogram",
    "pareto",
    "grouped_bar",
    "line",
)

# Fields allowed per kind when setting defaults via CLI.
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "scatter": ("data", "title", "xlabel", "ylabel"),
    "bar": ("data", "title", "ylabel"),
    "pie": ("data", "title"),
    "histogram": ("data", "title", "xlabel", "binned", "bins"),
    "pareto": ("data", "title"),
    "grouped_bar": ("categories", "series", "title", "ylabel", "source"),
    "line": ("tickers", "range", "title"),
}


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        legacy = Path.home() / ".config" / "fish"
        if (legacy / ".env").is_file():
            return legacy
        return Path.home() / ".config" / "arka"


def charts_config_path(*, for_write: bool = False) -> Path:
    """Resolve chart defaults file (user override → existing file → default path)."""
    override = (os.environ.get("ARKA_CHARTS_CONFIG") or "").strip()
    if override:
        return Path(override).expanduser()
    base = _config_dir()
    if for_write:
        return base / "charts.yaml"
    for name in ("charts.yaml", "charts.yml", "charts.json"):
        path = base / name
        if path.is_file():
            return path
    return base / "charts.yaml"


def _load_yaml(text: str) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("YAML config requires PyYAML (pip install pyyaml)") from exc
    return yaml.safe_load(text)


def _dump_yaml(data: dict) -> str:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("YAML config requires PyYAML (pip install pyyaml)") from exc
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def load_charts_config(*, reload: bool = False) -> dict[str, Any]:
    """Return full config document (always includes a ``defaults`` mapping)."""
    path = charts_config_path()
    if not path.is_file():
        return {"defaults": {}}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"defaults": {}}

    data: Any = None
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            data = _load_yaml(text)
        except ValueError:
            return {"defaults": {}}
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"defaults": {}}

    if not isinstance(data, dict):
        return {"defaults": {}}
    defaults = data.get("defaults")
    if not isinstance(defaults, dict):
        data["defaults"] = {}
    return data


def save_charts_config(data: dict[str, Any]) -> Path:
    """Persist config; prefers YAML at charts.yaml, falls back to charts.json."""
    base = _config_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = charts_config_path(for_write=True)
    payload = deepcopy(data)
    if not isinstance(payload.get("defaults"), dict):
        payload["defaults"] = {}

    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            path.write_text(_dump_yaml(payload) + "\n", encoding="utf-8")
            return path
        except ValueError:
            path = base / "charts.json"

    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def list_defaults() -> dict[str, dict[str, Any]]:
    cfg = load_charts_config()
    raw = cfg.get("defaults") or {}
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for kind, entry in raw.items():
            if isinstance(entry, dict):
                out[str(kind)] = dict(entry)
    return out


def get_kind_defaults(kind: str) -> dict[str, Any] | None:
    kind = (kind or "").strip().lower()
    entry = list_defaults().get(kind)
    if not entry:
        return None
    return entry


def set_kind_defaults(kind: str, fields: dict[str, Any]) -> Path:
    kind = (kind or "").strip().lower()
    if kind not in CHART_KINDS:
        raise ValueError(f"Unknown chart kind {kind!r}; expected one of: {', '.join(CHART_KINDS)}")

    allowed = set(KIND_FIELDS.get(kind, ()))
    cleaned: dict[str, Any] = {}
    for key, val in fields.items():
        if key not in allowed:
            continue
        if val is None:
            continue
        if isinstance(val, str):
            val = val.strip()
            if not val:
                continue
        cleaned[key] = val

    if kind == "line" and "tickers" in cleaned:
        tickers = cleaned["tickers"]
        if isinstance(tickers, str):
            cleaned["tickers"] = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
        elif isinstance(tickers, list):
            cleaned["tickers"] = [str(t).strip() for t in tickers if str(t).strip()]

    if kind == "grouped_bar" and "series" in cleaned:
        series = cleaned["series"]
        if isinstance(series, str):
            cleaned["series"] = [series]
        elif isinstance(series, list):
            cleaned["series"] = [str(s) for s in series if str(s).strip()]

    if not cleaned:
        raise ValueError(f"No valid fields to set for {kind}; allowed: {', '.join(KIND_FIELDS[kind])}")

    cfg = load_charts_config()
    defaults = cfg.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}
        cfg["defaults"] = defaults
    prev = defaults.get(kind)
    merged = dict(prev) if isinstance(prev, dict) else {}
    merged.update(cleaned)
    defaults[kind] = merged
    return save_charts_config(cfg)


def clear_kind_defaults(kind: str) -> Path | None:
    kind = (kind or "").strip().lower()
    if kind not in CHART_KINDS:
        raise ValueError(f"Unknown chart kind {kind!r}")
    cfg = load_charts_config()
    defaults = cfg.get("defaults")
    if not isinstance(defaults, dict) or kind not in defaults:
        return None
    defaults.pop(kind, None)
    return save_charts_config(cfg)


def config_help_snippet() -> str:
    path = charts_config_path(for_write=True)
    return (
        f"Chart defaults live in {path} (override with ARKA_CHARTS_CONFIG). "
        "Example YAML:\n"
        "  defaults:\n"
        "    scatter:\n"
        '      data: "100:200,120:190,170:280"\n'
        '      xlabel: "Ad Spend"\n'
        '      ylabel: "Revenue"\n'
        "Manage via: chart defaults list | show KIND | set KIND --data '…' | unset KIND"
    )
