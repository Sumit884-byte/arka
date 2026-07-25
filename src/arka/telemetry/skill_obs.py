"""OpenTelemetry helpers for skill dispatch — spans, metrics, correlated logs."""

from __future__ import annotations

from typing import Any

from arka.telemetry.tracing import duration_ms, mark_error, mark_ok, set_span_attributes


def finish_skill_dispatch(
    span_obj: Any,
    *,
    skill: str,
    exit_code: int,
    start: float,
    skill_line: str = "",
) -> float:
    """Attach duration/exit attrs, record metrics, and emit a correlated log."""
    elapsed = duration_ms(start)
    success = exit_code == 0
    attrs: dict[str, Any] = {
        "arka.skill.name": skill[:120],
        "arka.skill.duration_ms": elapsed,
        "arka.skill.exit_code": exit_code,
        "arka.skill.success": success,
    }
    if skill_line:
        attrs["arka.skill.line"] = skill_line[:500]

    try:
        from arka.telemetry.symbolic_obs import clear_route_context, skill_obs_attrs

        attrs.update(skill_obs_attrs(skill=skill))
    except ImportError:
        pass

    if span_obj is not None:
        set_span_attributes(span_obj, attrs)
        if success:
            mark_ok(span_obj)
        else:
            mark_error(span_obj, f"exit {exit_code}")

    try:
        from arka.telemetry.metrics import record_skill_dispatch

        record_skill_dispatch(
            skill=skill,
            duration_ms=elapsed,
            exit_code=exit_code,
            execution_kind=str(attrs.get("arka.execution.kind", "")),
            llm_used=attrs.get("arka.llm.used"),
        )
    except ImportError:
        pass

    try:
        from arka.telemetry.logs import emit_log

        exec_kind = attrs.get("arka.execution.kind", "unknown")
        emit_log(
            f"skill {skill} ({exec_kind}) exit {exit_code} ({elapsed:.1f}ms)",
            level="info" if success else "warn",
            attributes={
                **attrs,
                "arka.event": "skill.dispatch",
            },
        )
    except ImportError:
        pass

    try:
        from arka.telemetry.symbolic_obs import clear_route_context

        clear_route_context()
    except ImportError:
        pass

    return elapsed
