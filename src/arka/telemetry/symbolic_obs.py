"""Observability helpers for symbolic / deterministic routing and skill execution."""

from __future__ import annotations

import contextvars
from typing import Any

_route_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "arka_route_context",
    default=None,
)

# Skills that typically invoke an LLM during execution (not routing-only).
_LLM_SKILL_HEADS = frozenset(
    {
        "agent_ask",
        "ask",
        "contextual_answer",
        "contextual-answer",
        "context_answer",
        "with_context",
        "council",
        "cool_build",
        "data_ask",
        "deep_web_answer",
        "describe_image",
        "describe_screen",
        "describe_video",
        "design_from_screenshot",
        "design-screenshot",
        "designshot",
        "fact_check",
        "flow",
        "frontend_loop",
        "frontend-review",
        "frontend_review",
        "fun_fact",
        "game_studio",
        "hackathon",
        "ideate",
        "interesting_fact",
        "jules",
        "md_doc",
        "multi_llm",
        "multi-llm",
        "nudge",
        "arka-nudge",
        "arka_nudge",
        "orchestrate",
        "platform_howto",
        "prompt_optimize",
        "prompt-optimizer",
        "qa_engineering",
        "qa-engineering",
        "qa",
        "script_understanding",
        "self_build",
        "self-build",
        "self_improve",
        "self-improve",
        "society",
        "super_replica",
        "super-replica",
        "teammate_review",
        "trivia",
        "ui_copy",
        "ui-copy",
        "visual_diagnose",
        "visual_inspection",
        "web_answer",
    }
)


def normalize_skill_head(skill: str) -> str:
    head = (skill or "").strip().split(maxsplit=1)[0]
    return head.lower().replace("-", "_")


def skill_uses_llm(head: str) -> bool:
    return normalize_skill_head(head) in _LLM_SKILL_HEADS


def execution_kind(
    *,
    head: str = "",
    route_decision: str = "",
    route_source: str = "",
    skill_kind: str = "skill",
) -> str:
    if skill_kind == "shell":
        return "shell"
    decision = (route_decision or "").lower()
    source = (route_source or "").lower()
    if decision == "fish":
        return "fish"
    if decision == "llm" or source == "llm":
        return "llm_routed"
    if skill_uses_llm(head):
        return "llm_skill"
    return "deterministic"


def llm_used_for_execution(
    *,
    head: str = "",
    route_decision: str = "",
    route_source: str = "",
) -> bool:
    kind = execution_kind(head=head, route_decision=route_decision, route_source=route_source)
    return kind in {"llm_routed", "llm_skill"}


def route_obs_attrs(
    route_result: Any,
    *,
    decision: str,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    head = normalize_skill_head(getattr(route_result, "skill", "") or "")
    rule = getattr(route_result, "rule", "") or ""
    source = getattr(route_result, "source", "") or ""
    kind = getattr(route_result, "kind", "skill") or "skill"
    exec_kind = execution_kind(
        head=head,
        route_decision=decision,
        route_source=source,
        skill_kind=kind,
    )
    attrs: dict[str, Any] = {
        "arka.route.source": source[:40],
        "arka.route.skill": (getattr(route_result, "skill", "") or "")[:500],
        "arka.route.decision": decision[:40],
        "arka.execution.kind": exec_kind,
        "arka.llm.used": llm_used_for_execution(
            head=head,
            route_decision=decision,
            route_source=source,
        ),
    }
    if rule:
        attrs["arka.route.rule"] = rule[:120]
    if latency_ms is not None:
        attrs["arka.route.latency_ms"] = round(latency_ms, 2)
    return attrs


def skill_obs_attrs(
    *,
    skill: str,
    route_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = route_context or get_route_context() or {}
    head = normalize_skill_head(skill)
    decision = str(ctx.get("decision", ""))
    source = str(ctx.get("source", ""))
    exec_kind = execution_kind(
        head=head,
        route_decision=decision,
        route_source=source,
        skill_kind=str(ctx.get("kind", "skill")),
    )
    attrs: dict[str, Any] = {
        "arka.execution.kind": exec_kind,
        "arka.llm.used": llm_used_for_execution(
            head=head,
            route_decision=decision,
            route_source=source,
        ),
    }
    if ctx.get("rule"):
        attrs["arka.route.rule"] = str(ctx["rule"])[:120]
    if decision:
        attrs["arka.route.decision"] = decision[:40]
    if source:
        attrs["arka.route.source"] = source[:40]
    return attrs


def set_route_context(
    route_result: Any,
    *,
    decision: str,
) -> None:
    _route_context.set(
        {
            "skill": getattr(route_result, "skill", "") or "",
            "source": getattr(route_result, "source", "") or "",
            "kind": getattr(route_result, "kind", "skill") or "skill",
            "rule": getattr(route_result, "rule", "") or "",
            "decision": decision,
        }
    )


def get_route_context() -> dict[str, Any] | None:
    return _route_context.get()


def clear_route_context() -> None:
    _route_context.set(None)


def finish_route_obs(
    span_obj: Any,
    route_result: Any,
    *,
    decision: str,
    start: float,
) -> None:
    """Attach route attrs, record metrics, emit correlated log, stash route context."""
    try:
        from arka.telemetry import mark_ok
        from arka.telemetry.metrics import record_routing_decision
        from arka.telemetry.tracing import duration_ms, set_span_attributes
    except ImportError:
        return

    elapsed = duration_ms(start)
    route_result.decision = decision
    attrs = route_obs_attrs(route_result, decision=decision, latency_ms=elapsed)
    if span_obj is not None:
        set_span_attributes(span_obj, attrs)
        mark_ok(span_obj)

    head = normalize_skill_head(getattr(route_result, "skill", "") or "")
    record_routing_decision(
        decision=decision,
        source=getattr(route_result, "source", "") or "",
        latency_ms=elapsed,
        execution_kind=attrs["arka.execution.kind"],
        llm_used=bool(attrs["arka.llm.used"]),
        rule=getattr(route_result, "rule", "") or "",
        skill=head,
    )
    set_route_context(route_result, decision=decision)

    try:
        from arka.telemetry.logs import emit_log

        rule = getattr(route_result, "rule", "") or ""
        rule_note = f" rule={rule}" if rule else ""
        emit_log(
            (
                f"route {decision} → {getattr(route_result, 'skill', '')[:120]}"
                f" ({elapsed:.1f}ms{rule_note})"
            ),
            level="info",
            attributes={
                **attrs,
                "arka.event": "route.decision",
            },
        )
    except ImportError:
        pass


def annotate_request_span(route_result: Any | None) -> None:
    """Attach route metadata to the active arka.request span when present."""
    try:
        from opentelemetry import trace

        from arka.telemetry.tracing import set_span_attributes
    except ImportError:
        return

    span_obj = trace.get_current_span()
    if span_obj is None:
        return

    if route_result is None:
        set_span_attributes(
            span_obj,
            {
                "arka.request.routed": False,
                "arka.execution.kind": "llm_skill",
                "arka.llm.used": True,
            },
        )
        return

    decision = getattr(route_result, "decision", "") or ""
    if not decision:
        source = getattr(route_result, "source", "") or ""
        if source == "llm":
            decision = "llm"
        elif source == "fish":
            decision = "fish"
        else:
            decision = "symbolic"
        route_result.decision = decision

    set_route_context(route_result, decision=decision)
    attrs = route_obs_attrs(route_result, decision=decision)
    attrs["arka.request.routed"] = True
    attrs["arka.request.skill"] = (getattr(route_result, "skill", "") or "")[:500]
    set_span_attributes(span_obj, attrs)
