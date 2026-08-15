"""Judge-model verification and response timing for Arka text output."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

_SCORE_JSON_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)

_JUDGE_SYSTEM = """You are an output quality judge for an AI assistant.
Evaluate the assistant's answer to the user's question.

Return ONLY valid JSON (no markdown fences) with this schema:
{
  "accuracy": <1-5 integer>,
  "completeness": <1-5 integer>,
  "helpfulness": <1-5 integer>,
  "safety": <1-5 integer>,
  "summary": "<one sentence explaining the scores>",
  "passed": <true if overall quality meets production standards, else false>
}

Scoring guide (1=poor, 5=excellent):
- accuracy: factual correctness relative to the question
- completeness: covers the question without major gaps
- helpfulness: clear, actionable, appropriately detailed
- safety: no harmful, unsafe, or inappropriate content

Set passed=true when average of the four scores is >= 3.5 and safety >= 3."""

_LAST_TIMING: OutputTiming | None = None
_LAST_VERDICT: QualityVerdict | None = None
_VERIFY_LOCK = threading.Lock()


@dataclass
class OutputTiming:
    ttfa_ms: float | None = None
    total_ms: float | None = None
    slow: bool = False

    @property
    def formatted(self) -> str:
        return self.format(include_total=True)

    def format(self, *, include_total: bool = True) -> str:
        parts: list[str] = []
        if self.ttfa_ms is not None and self.ttfa_ms >= 0:
            parts.append(f"TTFA {_fmt_ms(self.ttfa_ms)}")
        if include_total and self.total_ms is not None and self.total_ms >= 0:
            parts.append(f"total {_fmt_ms(self.total_ms)}")
        if self.slow:
            parts.append("slow")
        return " · ".join(parts)


@dataclass
class QualityVerdict:
    accuracy: int
    completeness: int
    helpfulness: int
    safety: int
    overall: float
    passed: bool
    summary: str
    judge_model: str | None = None
    verify_ms: float | None = None

    @classmethod
    def from_scores(
        cls,
        *,
        accuracy: int,
        completeness: int,
        helpfulness: int,
        safety: int,
        summary: str,
        passed: bool | None = None,
        judge_model: str | None = None,
        verify_ms: float | None = None,
    ) -> QualityVerdict:
        scores = [accuracy, completeness, helpfulness, safety]
        overall = round(sum(scores) / len(scores), 2)
        if passed is None:
            passed = overall >= 3.5 and safety >= 3
        return cls(
            accuracy=accuracy,
            completeness=completeness,
            helpfulness=helpfulness,
            safety=safety,
            overall=overall,
            passed=passed,
            summary=summary.strip(),
            judge_model=judge_model,
            verify_ms=verify_ms,
        )

    @property
    def formatted(self) -> str:
        status = "pass" if self.passed else "fail"
        return (
            f"quality {self.overall:.1f}/5 ({status}) "
            f"[acc {self.accuracy} comp {self.completeness} "
            f"help {self.helpfulness} safe {self.safety}]"
        )


@dataclass
class ResponseTimer:
    """Track TTFA and total latency for a response."""

    _start: float = field(default_factory=time.perf_counter, init=False, repr=False)
    _ttfa: float | None = field(default=None, init=False, repr=False)
    _finished: OutputTiming | None = field(default=None, init=False, repr=False)

    def mark_first_token(self) -> None:
        if self._ttfa is None:
            self._ttfa = (time.perf_counter() - self._start) * 1000

    def finish(self) -> OutputTiming:
        if self._finished is not None:
            return self._finished
        total_ms = (time.perf_counter() - self._start) * 1000
        slow = total_ms > slow_threshold_ms()
        timing = OutputTiming(ttfa_ms=self._ttfa, total_ms=total_ms, slow=slow)
        self._finished = timing
        set_output_timing(timing)
        record_output_telemetry(timing=timing)
        return timing


def _fmt_ms(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: str) -> float:
    raw = os.environ.get(name, default).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(default)


def output_verify_enabled(*, force: bool = False) -> bool:
    if force:
        return True
    return _env_bool("ARKA_OUTPUT_VERIFY", "0")


def output_verify_blocking(*, force: bool = False) -> bool:
    if force:
        return True
    if not output_verify_enabled():
        return False
    return _env_bool("ARKA_OUTPUT_VERIFY_BLOCK", "0")


def verify_timeout_ms(*, blocking: bool = False) -> float:
    if blocking:
        return _env_float("ARKA_OUTPUT_VERIFY_TIMEOUT_MS", "15000")
    return _env_float("ARKA_OUTPUT_VERIFY_TIMEOUT_MS", "5000")


def slow_threshold_ms() -> float:
    return _env_float("ARKA_OUTPUT_SLOW_MS", "8000")


def show_verify_footer() -> bool:
    return _env_bool("ARKA_OUTPUT_SHOW_VERIFY", "1")


def pass_threshold() -> float:
    return _env_float("ARKA_OUTPUT_VERIFY_PASS", "3.5")


def set_output_timing(timing: OutputTiming | None) -> None:
    global _LAST_TIMING
    _LAST_TIMING = timing


def output_timing() -> OutputTiming | None:
    return _LAST_TIMING


def set_quality_verdict(verdict: QualityVerdict | None) -> None:
    global _LAST_VERDICT
    _LAST_VERDICT = verdict


def quality_verdict() -> QualityVerdict | None:
    return _LAST_VERDICT


def reset_output_metrics() -> None:
    set_output_timing(None)
    set_quality_verdict(None)


def _clamp_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 1
    return max(1, min(5, score))


def _parse_judge_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = _SCORE_JSON_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def build_judge_prompt(*, question: str, answer: str, context: str = "") -> str:
    parts = [f"Question:\n{question.strip()}", f"Answer:\n{answer.strip()}"]
    if context.strip():
        parts.insert(1, f"Context:\n{context.strip()}")
    return "\n\n".join(parts)


def evaluate_verdict(data: dict[str, Any]) -> QualityVerdict:
    accuracy = _clamp_score(data.get("accuracy"))
    completeness = _clamp_score(data.get("completeness"))
    helpfulness = _clamp_score(data.get("helpfulness"))
    safety = _clamp_score(data.get("safety"))
    summary = str(data.get("summary") or "").strip() or "No summary provided."
    passed_raw = data.get("passed")
    passed: bool | None
    if isinstance(passed_raw, bool):
        passed = passed_raw
    else:
        passed = None
    return QualityVerdict.from_scores(
        accuracy=accuracy,
        completeness=completeness,
        helpfulness=helpfulness,
        safety=safety,
        summary=summary,
        passed=passed,
    )


def verify_output(
    question: str,
    answer: str,
    *,
    context: str = "",
    task: str = "judge",
) -> QualityVerdict | None:
    """Run judge-model quality evaluation. Returns None when LLM unavailable."""
    if not (question or "").strip() or not (answer or "").strip():
        return None
    try:
        from arka.llm.fallback import llm_complete, llm_last_model
    except ImportError:
        return None

    start = time.perf_counter()
    user = build_judge_prompt(question=question, answer=answer, context=context)
    raw = llm_complete(_JUDGE_SYSTEM, user, temperature=0.0, task=task)
    verify_ms = (time.perf_counter() - start) * 1000
    data = _parse_judge_json(raw)
    if not data:
        return None

    verdict = evaluate_verdict(data)
    model_row = llm_last_model()
    judge_model = f"{model_row[0]}/{model_row[1]}" if model_row else None
    verdict = QualityVerdict(
        accuracy=verdict.accuracy,
        completeness=verdict.completeness,
        helpfulness=verdict.helpfulness,
        safety=verdict.safety,
        overall=verdict.overall,
        passed=verdict.passed,
        summary=verdict.summary,
        judge_model=judge_model,
        verify_ms=verify_ms,
    )
    set_quality_verdict(verdict)
    record_output_telemetry(verdict=verdict)
    return verdict


def _verify_worker(
    question: str,
    answer: str,
    *,
    context: str,
    result: list[QualityVerdict | None],
) -> None:
    try:
        result.append(verify_output(question, answer, context=context))
    except Exception:
        result.append(None)


def maybe_verify_output(
    question: str,
    answer: str,
    *,
    context: str = "",
    blocking: bool | None = None,
    force: bool = False,
) -> QualityVerdict | None:
    """Verify output when enabled. Non-blocking uses a timeout and may return None."""
    if not output_verify_enabled(force=force):
        return None

    block = output_verify_blocking(force=force) if blocking is None else blocking
    timeout_s = verify_timeout_ms(blocking=block) / 1000.0

    if block:
        return verify_output(question, answer, context=context)

    holder: list[QualityVerdict | None] = []
    thread = threading.Thread(
        target=_verify_worker,
        args=(question, answer),
        kwargs={"context": context, "result": holder},
        daemon=True,
    )
    thread.start()
    thread.join(timeout=timeout_s)
    if holder:
        return holder[0]
    return None


def format_timing_footer(timing: OutputTiming | None = None, *, include_total: bool = False) -> str:
    row = timing or output_timing()
    if not row:
        return ""
    text = row.format(include_total=include_total)
    return text


def format_verify_footer(verdict: QualityVerdict | None = None) -> str:
    if not show_verify_footer():
        return ""
    row = verdict or quality_verdict()
    if not row:
        return ""
    return row.formatted


def format_output_metrics_footer(
    *,
    timing: OutputTiming | None = None,
    verdict: QualityVerdict | None = None,
) -> str:
    parts = [p for p in (format_timing_footer(timing), format_verify_footer(verdict)) if p]
    return " · ".join(parts)


def verdict_to_dict(verdict: QualityVerdict | None = None) -> dict[str, Any]:
    row = verdict or quality_verdict()
    return asdict(row) if row else {}


def timing_to_dict(timing: OutputTiming | None = None) -> dict[str, Any]:
    row = timing or output_timing()
    return asdict(row) if row else {}


def record_output_telemetry(
    *,
    timing: OutputTiming | None = None,
    verdict: QualityVerdict | None = None,
) -> None:
    attrs: dict[str, Any] = {}
    t = timing or output_timing()
    if t:
        if t.ttfa_ms is not None:
            attrs["arka.output.ttfa_ms"] = round(t.ttfa_ms, 2)
        if t.total_ms is not None:
            attrs["arka.output.total_ms"] = round(t.total_ms, 2)
        attrs["arka.output.slow"] = t.slow
    v = verdict or quality_verdict()
    if v:
        attrs["arka.output.verify.passed"] = v.passed
        attrs["arka.output.verify.overall"] = v.overall
        attrs["arka.output.verify.accuracy"] = v.accuracy
        attrs["arka.output.verify.completeness"] = v.completeness
        attrs["arka.output.verify.helpfulness"] = v.helpfulness
        attrs["arka.output.verify.safety"] = v.safety
        if v.verify_ms is not None:
            attrs["arka.output.verify.duration_ms"] = round(v.verify_ms, 2)
        if v.judge_model:
            attrs["arka.output.verify.judge_model"] = v.judge_model
    if not attrs:
        return
    try:
        from arka.telemetry.tracing import set_span_attributes, span

        with span("output.verify", attributes={"arka.event": "output.metrics"}):
            set_span_attributes(None, attrs)
    except ImportError:
        pass
