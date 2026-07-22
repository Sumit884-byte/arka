"""SigNoz dashboard templates and API helpers for Arka observability."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from arka.telemetry.signoz_alerts import signoz_api_key, signoz_ui_url

_DASHBOARDS_DIR = Path(__file__).resolve().parents[3] / "signoz" / "dashboards"
DEFAULT_DASHBOARD = "arka-agent-observability"

_DEFAULT_LOG_FIELDS: list[dict[str, str]] = [
    {"dataType": "string", "type": "", "name": "body"},
    {"dataType": "string", "type": "", "name": "timestamp"},
]


def _normalize_query_data(query_data: dict[str, Any], *, panel_type: str) -> dict[str, Any]:
    """Fill SigNoz builder fields omitted from hand-authored templates."""
    row = dict(query_data)
    aggregate = str(row.get("aggregateOperator") or "count")
    row.setdefault("legend", "")
    row.setdefault("having", [])
    row.setdefault("functions", [])
    row.setdefault("filters", {"items": [], "op": "AND"})
    if aggregate == "noop":
        row.setdefault("reduceTo", "last")
        row.setdefault("pageSize", int(row.get("limit") or 100))
        row.setdefault("offset", 0)
    elif aggregate == "count":
        row.setdefault("reduceTo", "sum")
    else:
        row.setdefault("reduceTo", "avg")

    group_by = row.get("groupBy") or []
    if panel_type == "pie" and len(group_by) == 1:
        key = str((group_by[0] or {}).get("key") or "").strip()
        if key and not row.get("legend"):
            row["legend"] = f"{{{{{key}}}}}"
    return row


def normalize_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure bundled widgets include fields SigNoz expects after JSON import."""
    data = dict(payload)
    widgets: list[dict[str, Any]] = []
    for widget in data.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        panel = str(widget.get("panelTypes") or "")
        normalized = dict(widget)
        query = dict(normalized.get("query") or {})
        builder = dict(query.get("builder") or {})
        query_data = [
            _normalize_query_data(row, panel_type=panel)
            for row in (builder.get("queryData") or [])
            if isinstance(row, dict)
        ]
        builder["queryData"] = query_data
        query["builder"] = builder
        normalized["query"] = query
        if panel == "list":
            normalized.setdefault("selectedLogFields", list(_DEFAULT_LOG_FIELDS))
        widgets.append(normalized)
    data["widgets"] = widgets
    return data


def bundled_dashboard_paths(*, include_stubs: bool = False) -> dict[str, Path]:
    if not _DASHBOARDS_DIR.is_dir():
        return {}
    paths: dict[str, Path] = {}
    for path in sorted(_DASHBOARDS_DIR.glob("*.json")):
        if not include_stubs and path.name.endswith(".stub.json"):
            continue
        slug = path.stem.replace("_", "-")
        if not include_stubs and slug.endswith("-stub"):
            continue
        paths[slug] = path
    return paths


def list_dashboard_templates() -> list[str]:
    return sorted(bundled_dashboard_paths())


def load_dashboard(name: str) -> dict[str, Any]:
    slug = name.strip().replace("_", "-")
    paths = bundled_dashboard_paths(include_stubs=True)
    if slug not in paths:
        known = ", ".join(sorted(paths)) or "(none)"
        raise KeyError(f"Unknown dashboard template {name!r}. Known: {known}")
    with paths[slug].open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Dashboard template {name!r} is not a JSON object")
    return normalize_dashboard(data)


def dashboard_title(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or payload.get("name") or "").strip()
    if title:
        return title
    spec = payload.get("spec")
    if isinstance(spec, dict):
        display = spec.get("display")
        if isinstance(display, dict):
            return str(display.get("name") or "").strip()
    return DEFAULT_DASHBOARD


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
        with urllib.request.urlopen(request, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            if not body.strip():
                return resp.status, None
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SigNoz API {method} {path} failed ({exc.code}): {detail}") from exc


def _unwrap_dashboard_list(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            items = data.get("dashboards") or data.get("items")
            if isinstance(items, list):
                return [row for row in items if isinstance(row, dict)]
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    return []


def fetch_remote_dashboards(*, api_key: str | None = None) -> list[dict[str, Any]]:
    for path in ("/api/v1/dashboards", "/api/v2/dashboards?limit=100"):
        try:
            status, body = _request("GET", path, api_key=api_key)
        except RuntimeError:
            continue
        if status != 200:
            continue
        rows = _unwrap_dashboard_list(body)
        if rows:
            return rows
    return []


def find_existing_dashboard(title: str, *, api_key: str | None = None) -> dict[str, Any] | None:
    target = title.strip().lower()
    for row in fetch_remote_dashboards(api_key=api_key):
        row_title = dashboard_title(row).lower()
        if row_title == target:
            return row
        data = row.get("data")
        if isinstance(data, dict):
            nested = str(data.get("title") or "").strip().lower()
            if nested == target:
                return row
    return None


def _try_mcp_import(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort import via SigNoz MCP when configured."""
    try:
        from arka.integrations.signoz_mcp import query_signoz_mcp, signoz_mcp_configured
    except ImportError:
        return None
    if not signoz_mcp_configured():
        return None

    for tool_name, arguments in (
        ("signoz_import_dashboard", {"dashboard": payload}),
        ("signoz_create_dashboard", {"dashboard": payload, "title": dashboard_title(payload)}),
    ):
        try:
            text = query_signoz_mcp(tool_name, arguments)
        except Exception:
            continue
        if text.strip():
            return {"engine": "mcp", "tool": tool_name, "response": text[:2000]}
    return None


def install_dashboard(
    name: str = DEFAULT_DASHBOARD,
    *,
    dry_run: bool = False,
    replace: bool = False,
    api_key: str | None = None,
    use_mcp: bool = False,
) -> dict[str, Any]:
    payload = load_dashboard(name)
    title = dashboard_title(payload)

    if dry_run:
        return {
            "dry_run": True,
            "dashboard": name,
            "title": title,
            "widgets": len(payload.get("widgets") or []),
            "panels": len((payload.get("spec") or {}).get("panels") or {}),
        }

    existing = find_existing_dashboard(title, api_key=api_key)
    if existing and not replace:
        return {
            "skipped": True,
            "dashboard": name,
            "title": title,
            "id": existing.get("id") or existing.get("uuid"),
            "message": "Dashboard already exists (use --replace to recreate)",
        }

    if existing and replace:
        dashboard_id = existing.get("id") or existing.get("uuid")
        if dashboard_id:
            for path in (f"/api/v1/dashboards/{dashboard_id}", f"/api/v2/dashboards/{dashboard_id}"):
                try:
                    _request("DELETE", path, api_key=api_key)
                    break
                except RuntimeError:
                    continue

    if use_mcp:
        mcp_result = _try_mcp_import(payload)
        if mcp_result:
            return {"created": True, "dashboard": name, "title": title, **mcp_result}

    last_error: RuntimeError | None = None
    for path in ("/api/v1/dashboards", "/api/v2/dashboards"):
        try:
            status, body = _request("POST", path, payload=payload, api_key=api_key)
        except RuntimeError as exc:
            last_error = exc
            continue
        if status in (200, 201):
            created = body.get("data") if isinstance(body, dict) else body
            return {
                "created": True,
                "dashboard": name,
                "title": title,
                "engine": "api",
                "path": path,
                "response": created,
            }

    if last_error is not None:
        raise last_error
    raise RuntimeError("SigNoz dashboard install failed on all API endpoints")


def install_observability_bundle(
    *,
    dry_run: bool = False,
    replace: bool = False,
    alerts: bool = True,
    use_mcp: bool = False,
) -> dict[str, Any]:
    """Install the Arka dashboard and bundled observability alerts."""
    from arka.telemetry.signoz_alerts import create_alert_rule, list_alert_rules

    result: dict[str, Any] = {
        "dashboard": install_dashboard(
            DEFAULT_DASHBOARD,
            dry_run=dry_run,
            replace=replace,
            use_mcp=use_mcp,
        )
    }
    if not alerts:
        return result

    alert_slugs = [
        slug
        for slug in ("agent-error-spike", "skill-dispatch-failures", "llm-p99-latency")
        if slug in list_alert_rules()
    ]
    alert_results: list[dict[str, Any]] = []
    for slug in alert_slugs:
        try:
            alert_results.append(
                create_alert_rule(slug, dry_run=dry_run, replace=replace)
            )
        except (KeyError, RuntimeError) as exc:
            alert_results.append({"alert": slug, "error": str(exc)})
    result["alerts"] = alert_results
    return result


def cmd_dashboard_install(args: argparse.Namespace) -> int:
    name = str(getattr(args, "name", None) or DEFAULT_DASHBOARD)
    dry_run = bool(getattr(args, "dry_run", False))
    replace = bool(getattr(args, "replace", False))
    use_mcp = bool(getattr(args, "mcp", False))
    with_alerts = bool(getattr(args, "alerts", False))

    if not signoz_api_key() and not dry_run and not use_mcp:
        print("Missing SIGNOZ_API_KEY.", file=sys.stderr)
        print("  1. Open SigNoz → Settings → Service Accounts → Add Key", file=sys.stderr)
        print("  2. Add to .env: SIGNOZ_API_KEY=<your-key>", file=sys.stderr)
        print("  Or pass --dry-run to preview the bundled JSON.", file=sys.stderr)
        return 1

    try:
        if with_alerts:
            bundle = install_observability_bundle(
                dry_run=dry_run,
                replace=replace,
                alerts=True,
                use_mcp=use_mcp,
            )
            result = bundle["dashboard"]
            alert_rows = bundle.get("alerts") or []
        else:
            result = install_dashboard(
                name,
                dry_run=dry_run,
                replace=replace,
                use_mcp=use_mcp,
            )
            alert_rows = []
    except (KeyError, RuntimeError, ValueError) as exc:
        print(f"error\t{exc}", file=sys.stderr)
        return 1

    if result.get("dry_run"):
        print(f"dry_run\t{result.get('title', name)}")
        print(f"widgets\t{result.get('widgets', 0)}")
        if alert_rows:
            print(f"alerts\t{len(alert_rows)} bundled rule(s) would be created")
        return 0

    if result.get("skipped"):
        print(f"skipped\t{result.get('title', name)}\t{result.get('id', '')}\t{result.get('message', '')}")
    elif result.get("created"):
        print(f"created\t{result.get('title', name)}")
        engine = result.get("engine", "api")
        print(f"engine\t{engine}")
        ui = signoz_ui_url()
        print(f"ui\t{ui}/dashboard")
    else:
        print(f"result\t{json.dumps(result, ensure_ascii=False)}")

    for row in alert_rows:
        if row.get("dry_run"):
            print(f"alert_dry_run\t{row.get('alert', '?')}")
        elif row.get("skipped"):
            print(f"alert_skipped\t{row.get('alert', '?')}")
        elif row.get("created"):
            print(f"alert_created\t{row.get('alert', '?')}")
        elif row.get("error"):
            print(f"alert_error\t{row.get('alert', '?')}\t{row['error']}", file=sys.stderr)

    return 0


def cmd_dashboard_list(_args: argparse.Namespace) -> int:
    print("bundled\t" + ", ".join(list_dashboard_templates()) or "(none)")
    if not signoz_api_key():
        print("remote\t(skipped — set SIGNOZ_API_KEY to list dashboards in SigNoz)")
        return 0
    try:
        rows = fetch_remote_dashboards()
    except RuntimeError as exc:
        print(f"remote\terror\t{exc}", file=sys.stderr)
        return 1
    for row in rows:
        title = dashboard_title(row)
        dashboard_id = row.get("id") or row.get("uuid") or ""
        print(f"remote\t{title}\t{dashboard_id}")
    return 0
