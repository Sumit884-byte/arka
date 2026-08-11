#!/usr/bin/env python3
"""Apple Foundation Models (Apple Intelligence) — on-device LLM via apple-fm-sdk."""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import urllib.error
import urllib.request
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL_ID = "apple-fm-system"
DEFAULT_CLI_BASE_URL = "http://127.0.0.1:8765/v1"
DEFAULT_CLI_PORT = "8765"

_SDK_MODULE: Any | None = None
_SDK_IMPORT_TRIED = False


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(name: str, default: str = "1") -> bool:
    return _env(name, default).lower() in {"1", "true", "yes", "on"}


def is_darwin() -> bool:
    return platform.system() == "Darwin"


def macos_version_tuple() -> tuple[int, ...] | None:
    """Return macOS version components, e.g. (26, 0, 0), or None off Darwin."""
    if not is_darwin():
        return None
    raw = platform.mac_ver()[0]
    if not raw:
        return None
    parts: list[int] = []
    for token in raw.split("."):
        try:
            parts.append(int(token))
        except ValueError:
            break
    return tuple(parts) if parts else None


def macos_meets_requirement(min_major: int = 26) -> bool:
    ver = macos_version_tuple()
    if not ver:
        return False
    return ver[0] >= min_major


def apple_fm_enabled() -> bool:
    """True when Apple FM integration is not explicitly disabled."""
    if not is_darwin():
        return False
    if _env("APPLE_FM_ENABLED") in {"0", "false", "no", "off"}:
        return False
    if _env("APPLE_FM_ENABLED") in {"1", "true", "yes", "on"}:
        return True
    return macos_meets_requirement()


def _load_sdk() -> Any | None:
    global _SDK_MODULE, _SDK_IMPORT_TRIED
    if _SDK_IMPORT_TRIED:
        return _SDK_MODULE
    _SDK_IMPORT_TRIED = True
    if not is_darwin() or not macos_meets_requirement():
        return None
    try:
        import apple_fm_sdk as fm  # type: ignore[import-untyped]

        _SDK_MODULE = fm
    except ImportError:
        _SDK_MODULE = None
    return _SDK_MODULE


def sdk_installed() -> bool:
    return _load_sdk() is not None


def cli_base_url() -> str:
    url = _env("APPLE_FM_CLI_BASE_URL") or _env("APPLE_FM_CLI_URL")
    if url:
        base = url.rstrip("/")
        return base if base.endswith("/v1") else f"{base}/v1"
    host = _env("APPLE_FM_CLI_HOST", "127.0.0.1")
    port = _env("APPLE_FM_CLI_PORT", DEFAULT_CLI_PORT)
    return f"http://{host}:{port}/v1"


def _http_ok(url: str, *, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def cli_server_reachable() -> bool:
    """True when an apple-fm-cli (or compatible) OpenAI server responds."""
    if not is_darwin():
        return False
    models_url = f"{cli_base_url()}/models"
    return _http_ok(models_url)


@dataclass(frozen=True)
class AppleFmModel:
    """Sentinel passed to LlmFallbackEngine — not an agno model."""

    model_id: str
    temperature: float
    max_tokens: int | None = None


@dataclass(frozen=True)
class AppleFmStatus:
    platform_ok: bool
    macos_version: str
    enabled: bool
    sdk_installed: bool
    model_available: bool
    unavailable_reason: str = ""
    cli_reachable: bool = False
    cli_base_url: str = ""
    backend: str = "none"  # sdk | cli | none

    @property
    def available(self) -> bool:
        return self.model_available or self.cli_reachable

    def summary(self) -> str:
        if self.model_available:
            return "Apple Intelligence ready (native SDK)"
        if self.cli_reachable:
            return f"Apple Intelligence ready via CLI server ({self.cli_base_url})"
        if not self.platform_ok:
            return "Requires macOS 26+ on Apple Silicon with Apple Intelligence"
        if not self.enabled:
            return "Disabled (set APPLE_FM_ENABLED=1 to enable)"
        if not self.sdk_installed:
            hint = "pip install apple-fm-sdk"
            if self.unavailable_reason:
                return f"SDK not ready: {self.unavailable_reason}. Install: {hint}"
            return f"SDK not installed. Install: {hint}"
        if self.unavailable_reason:
            return f"Unavailable: {self.unavailable_reason}"
        return "Apple Intelligence not available on this Mac"


def check_availability(*, force: bool = False) -> AppleFmStatus:
    """Probe native SDK and optional apple-fm-cli server."""
    del force  # reserved for future cache invalidation
    ver_tuple = macos_version_tuple()
    ver_str = ".".join(str(v) for v in ver_tuple) if ver_tuple else "n/a"
    platform_ok = is_darwin() and macos_meets_requirement()
    enabled = apple_fm_enabled()
    installed = sdk_installed()
    cli_url = cli_base_url()
    cli_ok = cli_server_reachable() if enabled and is_darwin() else False

    model_available = False
    reason = ""
    backend = "none"

    if platform_ok and enabled and installed:
        fm = _load_sdk()
        try:
            model = fm.SystemLanguageModel()
            is_available, unavailable = model.is_available()
            if is_available:
                model_available = True
                backend = "sdk"
            elif unavailable is not None:
                reason = str(getattr(unavailable, "name", unavailable))
            else:
                reason = "model unavailable"
        except Exception as exc:
            reason = str(exc)[:200]

    if not model_available and cli_ok:
        backend = "cli"

    if not platform_ok and is_darwin():
        reason = reason or "macOS 26+ required"
    elif not is_darwin():
        reason = reason or "not macOS"

    return AppleFmStatus(
        platform_ok=platform_ok,
        macos_version=ver_str,
        enabled=enabled,
        sdk_installed=installed,
        model_available=model_available,
        unavailable_reason=reason,
        cli_reachable=cli_ok,
        cli_base_url=cli_url if cli_ok else "",
        backend=backend,
    )


def provider_available() -> bool:
    if not apple_fm_enabled():
        return False
    status = check_availability()
    return status.available


def apple_fm_model_ids() -> list[str]:
    explicit = [m.strip() for m in _env("APPLE_FM_MODELS").split(",") if m.strip()]
    pref = _env("AI_PREFERRED_MODEL") if (_env("AI_PREFERRED_PROVIDER") or _env("LLM_PROVIDER")).lower() in {
        "apple-fm",
        "apple_fm",
        "apple",
    } else ""
    models = [pref] if pref else []
    models.extend(explicit or [DEFAULT_MODEL_ID])
    out: list[str] = []
    for mid in models:
        if mid and mid not in out:
            out.append(mid)
    return out


def _generation_options(fm: Any, *, temperature: float, max_tokens: int | None) -> Any | None:
    if max_tokens is None and temperature == 0.2:
        return None
    kwargs: dict[str, Any] = {}
    if temperature != 0.2:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["maximum_response_tokens"] = max_tokens
    if not kwargs:
        return None
    return fm.GenerationOptions(**kwargs)


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Nested event loop — run in a fresh loop on a thread would be heavy; sync path only.
    if loop.is_running():
        raise RuntimeError("apple-fm completion cannot run inside a running event loop")
    return asyncio.run(coro)


async def _complete_async(
    system: str,
    user: str,
    *,
    temperature: float,
    max_tokens: int | None,
) -> str:
    fm = _load_sdk()
    if fm is None:
        raise RuntimeError("apple-fm-sdk is not installed")
    model = fm.SystemLanguageModel()
    is_available, reason = model.is_available()
    if not is_available:
        detail = str(getattr(reason, "name", reason) if reason else "unavailable")
        raise RuntimeError(f"Apple Intelligence unavailable: {detail}")

    options = _generation_options(fm, temperature=temperature, max_tokens=max_tokens)
    session = fm.LanguageModelSession(instructions=system or None, model=model)
    response = await session.respond(user, options=options)
    return str(response).strip()


async def _stream_async(
    system: str,
    user: str,
    *,
    temperature: float,
    max_tokens: int | None,
) -> AsyncIterator[str]:
    fm = _load_sdk()
    if fm is None:
        raise RuntimeError("apple-fm-sdk is not installed")
    model = fm.SystemLanguageModel()
    is_available, reason = model.is_available()
    if not is_available:
        detail = str(getattr(reason, "name", reason) if reason else "unavailable")
        raise RuntimeError(f"Apple Intelligence unavailable: {detail}")

    options = _generation_options(fm, temperature=temperature, max_tokens=max_tokens)
    session = fm.LanguageModelSession(instructions=system or None, model=model)
    prev = ""
    async for chunk in session.stream_response(user, options=options):
        text = str(chunk)
        if text.startswith(prev):
            delta = text[len(prev) :]
            prev = text
        else:
            delta = text
            prev += text
        if delta:
            yield delta


def complete(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    """Sync completion via native SDK."""
    return _run_async(
        _complete_async(system, user, temperature=temperature, max_tokens=max_tokens)
    )


def stream_complete(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Yield text deltas from native SDK streaming."""
    out: queue.Queue[str | None] = queue.Queue()

    async def producer() -> None:
        try:
            async for delta in _stream_async(
                system, user, temperature=temperature, max_tokens=max_tokens
            ):
                out.put(delta)
        except Exception as exc:
            out.put(f"[LLM error: {exc}]")
        finally:
            out.put(None)

    def runner() -> None:
        try:
            asyncio.run(producer())
        except Exception as exc:
            out.put(f"[LLM error: {exc}]")
            out.put(None)

    threading.Thread(target=runner, daemon=True).start()
    while True:
        item = out.get()
        if item is None:
            break
        yield item


def status_lines() -> list[str]:
    """Key/value lines for ``arka model status`` / ``arka llm apple-fm status``."""
    status = check_availability()
    lines = [
        "backend\tapple-fm",
        f"platform_ok\t{str(status.platform_ok).lower()}",
        f"macos_version\t{status.macos_version}",
        f"enabled\t{str(status.enabled).lower()}",
        f"sdk_installed\t{str(status.sdk_installed).lower()}",
        f"model_available\t{str(status.model_available).lower()}",
        f"cli_reachable\t{str(status.cli_reachable).lower()}",
        f"configured\t{str(status.available).lower()}",
        f"active_backend\t{status.backend}",
    ]
    if status.cli_base_url:
        lines.append(f"cli_base_url\t{status.cli_base_url}")
    if status.unavailable_reason:
        lines.append(f"reason\t{status.unavailable_reason}")
    lines.append(f"summary\t{status.summary()}")
    if not status.sdk_installed and status.platform_ok and status.enabled:
        lines.append("install_hint\tpip install 'arka-agent[apple-fm]'  # or: pip install apple-fm-sdk")
    if not status.model_available and status.platform_ok and status.enabled:
        lines.append(
            "cli_hint\tapple-fm-cli server --host 127.0.0.1 --port "
            f"{_env('APPLE_FM_CLI_PORT', DEFAULT_CLI_PORT)}  # then set APPLE_FM_CLI_BASE_URL"
        )
    return lines


def print_unavailable_message(*, file: Any = None) -> None:
    status = check_availability()
    print(status.summary(), file=file or sys.stderr)
