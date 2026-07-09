"""Optional OpenTelemetry tracing — SigNoz / OTLP compatible, no-op when disabled."""

from __future__ import annotations

import os
import re
import sys
import traceback
from contextlib import contextmanager
from typing import Any, Iterator

from arka.telemetry._otlp import (
    collector_available,
    otlp_export_timeout_millis,
    otlp_export_timeout_seconds,
    register_fast_shutdown_handlers,
    shutdown_timeout_millis,
    signal_endpoint,
    suppress_otel_exporter_logging,
    telemetry_master_enabled,
)

_tracer: Any | None = None
_initialized = False
_enabled: bool | None = None
_warned_missing = False
_processors: list[Any] = []
_MAX_STACKTRACE_CHARS = 8000
_MAX_EXCEPTION_MESSAGE_CHARS = 500


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def record_exception(self, exc: BaseException) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass


def spans_enabled() -> bool:
    global _enabled
    if _enabled is not None:
        return _enabled
    _enabled = telemetry_master_enabled()
    return _enabled


def _resolve_endpoint() -> str:
    return signal_endpoint("traces")


def _safe_attr(value: Any) -> str | int | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if len(text) > 2000:
        return text[:2000] + "..."
    return text


def llm_provider_http_url(provider: str) -> str:
    """Best-effort chat-completions URL for OTel http.url (no secrets)."""
    from arka.llm.providers import get_provider, provider_base_url

    slug = (provider or "").strip().lower()
    if slug == "vllm":
        host = os.environ.get("VLLM_HOST", "127.0.0.1:8000").strip()
        base = os.environ.get("VLLM_API_URL", "").strip()
        if not base:
            base = host if host.startswith("http") else f"http://{host}"
        if not base.startswith("http"):
            base = f"http://{base}"
        base = base.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}/chat/completions"

    if slug == "vllm-cloud":
        from arka.llm.providers import get_provider, provider_base_url

        spec = get_provider("vllm-cloud")
        base = provider_base_url(spec) if spec else ""
        if base:
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            return f"{base}/chat/completions"

    native_urls = {
        "anthropic": "https://api.anthropic.com/v1/messages",
        "openai": "https://api.openai.com/v1/chat/completions",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "ollama": "http://127.0.0.1:11434/api/chat",
    }
    if slug in native_urls:
        return native_urls[slug]

    spec = get_provider(slug)
    if spec and spec.kind in {"openai_compatible", "local_openai"}:
        base = provider_base_url(spec)
        if base:
            return f"{base.rstrip('/')}/chat/completions"

    return f"arka://llm/{slug or 'unknown'}"


def llm_http_span_attributes(provider: str) -> dict[str, Any]:
    url = llm_provider_http_url(provider)
    return {
        "http.method": "POST",
        "http.request.method": "POST",
        "http.url": url,
        "url.full": url,
    }


def parse_http_status_code(source: Any) -> int | None:
    """Extract HTTP status from exceptions or provider error strings."""
    if source is None:
        return None
    try:
        import urllib.error

        if isinstance(source, urllib.error.HTTPError):
            return int(source.code)
    except ImportError:
        pass

    response = getattr(source, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if code is not None:
            try:
                return int(code)
            except (TypeError, ValueError):
                pass

    text = str(source)
    for pattern in (
        r"status code[:\s]+(\d{3})",
        r"HTTP Error (\d{3})",
        r"HTTPStatusError.*?(\d{3})",
        r"response status[:\s]+(\d{3})",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def set_http_span_attributes(
    span_obj: Any,
    *,
    method: str | None = None,
    status_code: int | None = None,
    url: str | None = None,
) -> None:
    if isinstance(span_obj, _NoOpSpan):
        return
    attrs: dict[str, Any] = {}
    if method:
        attrs["http.method"] = method
        attrs["http.request.method"] = method
    if url:
        attrs["http.url"] = url
        attrs["url.full"] = url
    if status_code is not None:
        attrs["http.status_code"] = status_code
        attrs["http.response.status_code"] = status_code
    if attrs:
        set_span_attributes(span_obj, attrs)


def _setup() -> None:
    global _tracer, _initialized, _warned_missing, _enabled
    if _initialized:
        return
    _initialized = True
    if not spans_enabled():
        return

    endpoint = _resolve_endpoint()
    if not collector_available(endpoint):
        _enabled = False
        return

    suppress_otel_exporter_logging()
    register_fast_shutdown_handlers()

    try:
        from arka.telemetry.logs import _setup as setup_logs
        from arka.telemetry.metrics import _setup as setup_metrics

        setup_metrics()
        setup_logs()
    except ImportError:
        pass

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from arka.telemetry._otlp import build_resource
    except ImportError:
        if not _warned_missing:
            _warned_missing = True
            print(
                "arka telemetry: OTEL enabled but opentelemetry packages missing — "
                "pip install 'arka-agent[observability]'",
                file=sys.stderr,
            )
        return

    timeout = otlp_export_timeout_seconds()
    provider = TracerProvider(resource=build_resource())
    exporter = OTLPSpanExporter(endpoint=endpoint, timeout=timeout)
    processor = BatchSpanProcessor(
        exporter,
        export_timeout_millis=otlp_export_timeout_millis(),
        schedule_delay_millis=5000,
    )
    _processors.append(processor)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("arka.agent", "0.1.0")
    import atexit

    atexit.register(shutdown_tracing)


@contextmanager
def span(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    _setup()
    if _tracer is None:
        noop = _NoOpSpan()
        yield noop
        return
    with _tracer.start_as_current_span(name) as current:
        if attributes:
            set_span_attributes(current, attributes)
        try:
            yield current
        except BaseException as exc:
            record_exception(current, exc)
            raise


def set_span_attributes(target: Any, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            target.set_attribute(key, _safe_attr(value))
        except Exception:
            pass


def duration_ms(start: float, end: float | None = None) -> float:
    """Wall-clock milliseconds between perf_counter samples."""
    import time

    finish = end if end is not None else time.perf_counter()
    return round((finish - start) * 1000.0, 2)


def set_timing_attrs(
    target: Any,
    *,
    start: float,
    end: float | None = None,
    ttft_ms: float | None = None,
    streaming: bool | None = None,
) -> None:
    """Attach standard latency attributes used in SigNoz demo panels."""
    attrs: dict[str, Any] = {"arka.llm.duration_ms": duration_ms(start, end)}
    if ttft_ms is not None:
        attrs["arka.llm.ttft_ms"] = round(ttft_ms, 2)
    elif streaming is False:
        attrs["arka.llm.ttft_ms"] = attrs["arka.llm.duration_ms"]
    if streaming is not None:
        attrs["arka.llm.streaming"] = streaming
    set_span_attributes(target, attrs)


def record_span_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    if _tracer is None:
        return
    try:
        from opentelemetry import trace

        current = trace.get_current_span()
        if current is None:
            return
        current.add_event(name, attributes=attributes or {})
    except Exception:
        pass


def trace_status() -> dict[str, str]:
    _setup()
    status = {
        "enabled": str(spans_enabled()).lower(),
        "configured": str(_tracer is not None).lower(),
        "endpoint": _resolve_endpoint() if spans_enabled() else "",
        "service": os.environ.get("OTEL_SERVICE_NAME", "arka").strip() or "arka",
    }
    try:
        from arka.telemetry.logs import logs_status
        from arka.telemetry.metrics import metrics_status

        status.update(metrics_status())
        status.update(logs_status())
    except ImportError:
        pass
    return status


def inject_trace_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    if not spans_enabled() or _tracer is None:
        return env
    try:
        from opentelemetry.propagate import inject

        inject(env)
    except ImportError:
        pass
    return env


def mark_ok(span_obj: Any) -> None:
    if isinstance(span_obj, _NoOpSpan):
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        span_obj.set_status(Status(StatusCode.OK))
    except Exception:
        pass


def exception_attributes(exc: BaseException) -> dict[str, str]:
    """OTel exception semantic convention attributes with full stack trace."""
    stack = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__, limit=50)
    )
    if len(stack) > _MAX_STACKTRACE_CHARS:
        stack = stack[: _MAX_STACKTRACE_CHARS - 3] + "..."
    message = str(exc).strip() or type(exc).__name__
    if len(message) > _MAX_EXCEPTION_MESSAGE_CHARS:
        message = message[: _MAX_EXCEPTION_MESSAGE_CHARS - 3] + "..."
    return {
        "exception.type": type(exc).__name__,
        "exception.message": message,
        "exception.stacktrace": stack,
    }


def record_exception(
    span_obj: Any,
    exc: BaseException,
    *,
    message: str | None = None,
) -> None:
    """Record exception on span with stack trace, error status, and correlated log."""
    if exc is None:
        return
    summary = (message or str(exc) or type(exc).__name__).strip()
    if len(summary) > _MAX_EXCEPTION_MESSAGE_CHARS:
        summary = summary[: _MAX_EXCEPTION_MESSAGE_CHARS - 3] + "..."

    if not isinstance(span_obj, _NoOpSpan):
        try:
            span_obj.record_exception(exc, escaped=False)
        except TypeError:
            try:
                span_obj.record_exception(exc)
            except Exception:
                pass
        except Exception:
            pass
        set_span_attributes(span_obj, exception_attributes(exc))
        try:
            from opentelemetry.trace import Status, StatusCode

            span_obj.set_status(Status(StatusCode.ERROR, summary))
        except Exception:
            pass

    try:
        from arka.telemetry.logs import emit_log
        from arka.telemetry.metrics import record_error

        attrs = exception_attributes(exc)
        attrs["arka.event"] = "exception"
        record_error(component=type(exc).__name__, message=summary)
        emit_log(summary, level="error", attributes=attrs)
    except ImportError:
        pass


def mark_error(span_obj: Any, message: str, *, exc: BaseException | None = None) -> None:
    if exc is not None:
        record_exception(span_obj, exc, message=message)
        return
    if isinstance(span_obj, _NoOpSpan):
        pass
    else:
        try:
            from opentelemetry.trace import Status, StatusCode

            span_obj.set_status(Status(StatusCode.ERROR, message[:500]))
        except Exception:
            pass
    try:
        from arka.telemetry.logs import emit_log
        from arka.telemetry.metrics import record_error

        record_error(component="span", message=message)
        emit_log(message, level="error", attributes={"arka.event": "error"})
    except ImportError:
        pass


def shutdown_tracing() -> None:
    timeout = shutdown_timeout_millis()
    try:
        from arka.telemetry.logs import shutdown_logs
        from arka.telemetry.metrics import shutdown_metrics

        shutdown_metrics()
        shutdown_logs()
    except ImportError:
        pass
    for processor in _processors:
        try:
            if hasattr(processor, "force_flush"):
                processor.force_flush(timeout_millis=timeout)
            if hasattr(processor, "shutdown"):
                processor.shutdown()
        except Exception:
            pass
    _processors.clear()
    if _tracer is None:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=timeout)
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        pass


@contextmanager
def request_span(command: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    try:
        from arka.telemetry.logs import emit_log
        from arka.telemetry.metrics import record_request

        record_request(command=command)
        emit_log(f"request: {command}", level="info", attributes={"arka.command": command[:200]})
    except ImportError:
        pass
    attrs = {"arka.command": command[:500], "arka.track": "01"}
    if attributes:
        attrs.update(attributes)
    with span("arka.request", attributes=attrs) as current:
        try:
            yield current
        except BaseException:
            if not isinstance(current, _NoOpSpan):
                current.set_attribute("arka.exit_code", 1)
            raise
        else:
            if not isinstance(current, _NoOpSpan):
                current.set_attribute("arka.exit_code", 0)
