"""SigNoz alert rule definitions and API helpers for bundled demos."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ALERTS_DIR = Path(__file__).resolve().parents[3] / "signoz" / "alerts"


def signoz_ui_url() -> str:
    return os.environ.get("SIGNOZ_UI_URL", "http://localhost:8080").rstrip("/")


def signoz_api_key() -> str:
    for key in ("SIGNOZ_API_KEY", "SIGNOZ_ACCESS_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def bundled_alert_paths() -> dict[str, Path]:
    if not _ALERTS_DIR.is_dir():
        return {}
    return {path.stem.replace("_", "-"): path for path in sorted(_ALERTS_DIR.glob("*.json"))}


def load_alert_rule(name: str) -> dict[str, Any]:
    slug = name.strip().replace("_", "-")
    paths = bundled_alert_paths()
    if slug not in paths:
        known = ", ".join(sorted(paths)) or "(none)"
        raise KeyError(f"Unknown alert rule {name!r}. Known: {known}")
    with paths[slug].open(encoding="utf-8") as handle:
        return json.load(handle)


def list_alert_rules() -> list[str]:
    return sorted(bundled_alert_paths())


def _request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
) -> tuple[int, Any]:
    key = api_key or signoz_api_key()
    if not key:
        raise RuntimeError(
            "Missing SigNoz API key. Create one in SigNoz UI: Settings → Service Accounts → Add Key, "
            "then set SIGNOZ_API_KEY in your .env"
        )

    url = f"{signoz_ui_url()}{path}"
    data = None
    headers = {
        "SIGNOZ-API-KEY": key,
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            if not body.strip():
                return resp.status, None
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SigNoz API {method} {path} failed ({exc.code}): {detail}") from exc


def fetch_alert_rules(*, api_key: str | None = None) -> list[dict[str, Any]]:
    status, body = _request("GET", "/api/v1/rules", api_key=api_key)
    if status != 200:
        raise RuntimeError(f"Unexpected status {status} listing alert rules")
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return data
    if isinstance(body, list):
        return body
    return []


def find_existing_rule(name: str, *, api_key: str | None = None) -> dict[str, Any] | None:
    for rule in fetch_alert_rules(api_key=api_key):
        if str(rule.get("alert", "")).strip() == name.strip():
            return rule
    return None


def create_alert_rule(
    name: str,
    *,
    dry_run: bool = False,
    replace: bool = False,
    api_key: str | None = None,
) -> dict[str, Any]:
    payload = load_alert_rule(name)
    alert_name = str(payload.get("alert", name))

    if dry_run:
        return {"dry_run": True, "alert": alert_name, "payload": payload}

    existing = find_existing_rule(alert_name, api_key=api_key)
    if existing and not replace:
        return {
            "skipped": True,
            "alert": alert_name,
            "id": existing.get("id"),
            "message": "Alert already exists (use --replace to recreate)",
        }

    status, body = _request("POST", "/api/v1/rules", payload=payload, api_key=api_key)
    if status not in (200, 201):
        raise RuntimeError(f"Unexpected status {status} creating alert rule")
    return {
        "created": True,
        "alert": alert_name,
        "response": body,
    }


def cmd_alert_create(args: argparse.Namespace) -> int:
    names = list_alert_rules() if getattr(args, "all", False) else [args.name]
    if not names:
        print("No bundled alert rules found under signoz/alerts/", file=sys.stderr)
        return 1

    if not signoz_api_key() and not args.dry_run:
        print("Missing SIGNOZ_API_KEY.", file=sys.stderr)
        print("  1. Open SigNoz → Settings → Service Accounts → Add Key", file=sys.stderr)
        print("  2. Add to .env: SIGNOZ_API_KEY=<your-key>", file=sys.stderr)
        return 1

    exit_code = 0
    for slug in names:
        try:
            result = create_alert_rule(
                slug,
                dry_run=bool(args.dry_run),
                replace=bool(args.replace),
            )
        except (KeyError, RuntimeError) as exc:
            print(f"error\t{slug}\t{exc}", file=sys.stderr)
            exit_code = 1
            continue

        if result.get("dry_run"):
            print(f"dry_run\t{result['alert']}")
            print(json.dumps(result["payload"], indent=2))
            continue
        if result.get("skipped"):
            print(f"skipped\t{result['alert']}\t{result.get('id', '')}\t{result['message']}")
            continue
        print(f"created\t{result['alert']}")
        ui = signoz_ui_url()
        print(f"ui\t{ui}/alerts")

    return exit_code


def cmd_alert_list(_args: argparse.Namespace) -> int:
    print("bundled\t" + ", ".join(list_alert_rules()) or "(none)")
    if not signoz_api_key():
        print("remote\t(skipped — set SIGNOZ_API_KEY to list rules in SigNoz)")
        return 0
    try:
        rules = fetch_alert_rules()
    except RuntimeError as exc:
        print(f"remote\terror\t{exc}", file=sys.stderr)
        return 1
    for rule in rules:
        alert = rule.get("alert", "?")
        rule_id = rule.get("id", "")
        severity = (rule.get("labels") or {}).get("severity", "")
        print(f"remote\t{alert}\t{rule_id}\t{severity}")
    return 0
