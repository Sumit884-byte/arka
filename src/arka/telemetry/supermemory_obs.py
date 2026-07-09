"""OpenTelemetry helpers for Supermemory API and local memory fallback."""

from __future__ import annotations

from typing import Any

API_BASE = "https://api.supermemory.ai"


def supermemory_api_url(path: str) -> str:
    return f"{API_BASE.rstrip('/')}{path}"


def supermemory_api_attrs(
    method: str,
    path: str,
    *,
    container: str = "",
) -> dict[str, Any]:
    url = supermemory_api_url(path)
    op = path.strip("/").replace("/", ".") or "root"
    attrs: dict[str, Any] = {
        "arka.supermemory.path": path,
        "arka.supermemory.operation": op,
        "http.method": method.upper(),
        "http.request.method": method.upper(),
        "http.url": url,
        "url.full": url,
        "server.address": "api.supermemory.ai",
    }
    if container:
        attrs["arka.supermemory.container"] = container
    return attrs


def record_supermemory_request(*, operation: str, success: bool = True) -> None:
    try:
        from arka.telemetry.metrics import record_supermemory_op

        record_supermemory_op(operation=operation, backend="api", success=success)
    except ImportError:
        pass


def record_supermemory_op(
    *,
    operation: str,
    backend: str,
    success: bool = True,
    hits: int = 0,
) -> None:
    try:
        from arka.telemetry.metrics import record_supermemory_op as _record

        _record(operation=operation, backend=backend, success=success, hits=hits)
    except ImportError:
        pass


def emit_supermemory_log(
    message: str,
    *,
    level: str = "info",
    operation: str = "",
    backend: str = "",
    hits: int | None = None,
    success: bool | None = None,
) -> None:
    try:
        from arka.telemetry.logs import emit_log

        attrs: dict[str, Any] = {"arka.component": "supermemory"}
        if operation:
            attrs["arka.supermemory.operation"] = operation
        if backend:
            attrs["arka.supermemory.backend"] = backend
        if hits is not None:
            attrs["arka.supermemory.hits"] = hits
        if success is not None:
            attrs["arka.supermemory.success"] = success
        emit_log(message, level=level, attributes=attrs)
    except ImportError:
        pass


def supermemory_status_lines() -> list[tuple[str, str]]:
    """Key/value lines for `arka signoz status` and diagnostics."""
    try:
        from arka.integrations.supermemory import (
            MEMORY_FILE,
            _api_key,
            _container_tag,
            _mode,
            _should_try_api,
            load_json,
        )
    except ImportError:
        return [("supermemory", "module_unavailable")]

    mode = _mode()
    key_set = bool(_api_key())
    items = load_json(MEMORY_FILE, [])
    count = len(items) if isinstance(items, list) else 0
    lines = [
        ("supermemory_mode", mode),
        ("supermemory_api_key", "set" if key_set else "not_set"),
        ("supermemory_container", _container_tag()),
        ("supermemory_local_entries", str(count)),
        ("supermemory_api_enabled", str(_should_try_api()).lower()),
    ]
    if mode == "local":
        lines.append(("supermemory_backend", "local"))
    elif key_set:
        lines.append(("supermemory_backend", "api+local" if mode == "auto" else "api"))
    else:
        lines.append(("supermemory_backend", "local_fallback"))
    return lines
