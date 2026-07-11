#!/usr/bin/env python3
"""Benchmark-based orchestration — compare providers/models and route by scores."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from arka.llm.fallback import LlmFallbackEngine, normalize_task, parse_chain
from arka.llm.skill_models import set_skill_model
from arka.llm.skill_profiles import known_task_profiles


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def benchmarks_dir() -> Path:
    from arka.paths import config_dir

    return config_dir() / "benchmarks"


def results_path() -> Path:
    from arka.paths import config_dir

    return config_dir() / "benchmark-results.json"


def bundled_default_suite() -> Path:
    from arka.paths import package_dir

    return package_dir() / "llm" / "templates" / "benchmark-default.yaml"


def default_suite_path() -> Path:
    return benchmarks_dir() / "default.yaml"


def is_benchmark_orchestrate_enabled() -> bool:
    raw = (os.environ.get("ARKA_BENCHMARK_ORCHESTRATE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass
class BenchmarkCandidate:
    provider: str = ""
    model: str = ""
    orchestrator: str = ""

    @property
    def key(self) -> str:
        if self.orchestrator:
            return f"orchestrator:{self.orchestrator}"
        return f"{self.provider}/{self.model}"

    def chain_entry(self) -> tuple[str, str] | None:
        if self.provider and self.model:
            return (self.provider.lower(), self.model)
        return None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BenchmarkCandidate:
        return cls(
            provider=str(raw.get("provider") or "").strip().lower(),
            model=str(raw.get("model") or raw.get("model_id") or "").strip(),
            orchestrator=str(raw.get("orchestrator") or "").strip().lower(),
        )


@dataclass
class BenchmarkTask:
    id: str
    profile: str
    prompt: str
    eval: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BenchmarkTask:
        return cls(
            id=str(raw.get("id") or "").strip(),
            profile=str(raw.get("profile") or "default").strip().lower(),
            prompt=str(raw.get("prompt") or "").strip(),
            eval=dict(raw.get("eval") or {}),
        )


@dataclass
class BenchmarkSuite:
    name: str
    description: str = ""
    candidates: list[BenchmarkCandidate] = field(default_factory=list)
    tasks: list[BenchmarkTask] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BenchmarkSuite:
        return cls(
            name=str(raw.get("name") or "default").strip(),
            description=str(raw.get("description") or "").strip(),
            candidates=[BenchmarkCandidate.from_dict(c) for c in raw.get("candidates") or []],
            tasks=[BenchmarkTask.from_dict(t) for t in raw.get("tasks") or []],
        )


@dataclass
class TaskRunResult:
    task_id: str
    profile: str
    candidate: str
    provider: str
    model: str
    orchestrator: str
    success: bool
    score: float
    latency_ms: float
    response: str = ""
    error: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_suite(name: str | None = None) -> BenchmarkSuite:
    suite_name = (name or "default").strip() or "default"
    path = benchmarks_dir() / f"{suite_name}.yaml"
    if not path.is_file():
        path = benchmarks_dir() / f"{suite_name}.yml"
    if not path.is_file() and suite_name == "default":
        ensure_default_suite()
        path = default_suite_path()
    if not path.is_file():
        raise FileNotFoundError(f"benchmark suite not found: {suite_name}")
    return BenchmarkSuite.from_dict(_load_yaml(path))


def ensure_default_suite() -> Path:
    benchmarks_dir().mkdir(parents=True, exist_ok=True)
    dest = default_suite_path()
    if dest.is_file():
        return dest
    src = bundled_default_suite()
    if src.is_file():
        shutil.copy2(src, dest)
    return dest


def list_suites() -> list[str]:
    ensure_default_suite()
    names: list[str] = []
    for path in sorted(benchmarks_dir().glob("*")):
        if path.suffix.lower() in {".yaml", ".yml"}:
            names.append(path.stem)
    return names


def load_results() -> dict[str, Any]:
    path = results_path()
    if not path.is_file():
        return {"updated_at": "", "suites": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated_at": "", "suites": {}}
    if not isinstance(data, dict):
        return {"updated_at": "", "suites": {}}
    data.setdefault("suites", {})
    return data


def save_results(data: dict[str, Any]) -> Path:
    path = results_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _iso_now()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def evaluate_response(text: str, criteria: dict[str, Any]) -> bool:
    body = (text or "").strip()
    if not criteria:
        return bool(body)
    if min_len := criteria.get("min_length"):
        if len(body) < int(min_len):
            return False
    if needle := criteria.get("contains"):
        if str(needle).lower() not in body.lower():
            return False
    if needles := criteria.get("contains_any"):
        if isinstance(needles, str):
            needles = [needles]
        if not any(str(n).lower() in body.lower() for n in needles):
            return False
    if pattern := criteria.get("regex"):
        if not re.search(str(pattern), body, flags=re.I):
            return False
    return True


def score_run(*, success: bool, latency_ms: float, max_latency_ms: float) -> float:
    if not success:
        return 0.0
    if max_latency_ms <= 0:
        return 1.0
    latency_ratio = min(1.0, max(0.0, latency_ms / max_latency_ms))
    return round(1.0 - (0.35 * latency_ratio), 4)


def _mock_complete(candidate: BenchmarkCandidate, task: BenchmarkTask) -> tuple[str, float, str]:
    """Deterministic offline responses for tests and --dry-run."""
    key = candidate.key
    latency = 50.0 + (hash(key + task.id) % 120)
    if candidate.orchestrator:
        text = f"[{candidate.orchestrator}] handled {task.profile}: {task.prompt[:40]}"
        return text, latency, ""
    if task.id == "chat_qa":
        return "42", latency, ""
    if task.id == "route_hint":
        return "google", latency, ""
    if task.id == "agent_code":
        return "def add(a, b): return a + b", latency, ""
    text = f"ok ({candidate.provider}/{candidate.model})"
    return text, latency, ""


CompleteFn = Callable[[BenchmarkCandidate, BenchmarkTask], tuple[str, float, str]]


def _live_complete(candidate: BenchmarkCandidate, task: BenchmarkTask) -> tuple[str, float, str]:
    if candidate.orchestrator:
        return _run_orchestrator(candidate, task)
    entry = candidate.chain_entry()
    if not entry:
        return "", 0.0, "missing provider/model"
    provider, model_id = entry
    engine = LlmFallbackEngine(task=task.profile, chain=[entry])
    started = time.perf_counter()
    result = engine.complete(
        system="You are a concise assistant. Follow the user instruction exactly.",
        user=task.prompt,
        temperature=0.0,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    if result.text:
        return result.text.strip(), latency_ms, ""
    return "", latency_ms, result.error or "empty response"


def _run_orchestrator(candidate: BenchmarkCandidate, task: BenchmarkTask) -> tuple[str, float, str]:
    orch = candidate.orchestrator
    started = time.perf_counter()
    try:
        if orch == "fugu":
            from arka.integrations.fugu import fugu_complete

            text = fugu_complete(task.prompt)
        else:
            return "", 0.0, f"unsupported orchestrator: {orch}"
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - started) * 1000.0
        return "", latency_ms, str(exc)
    latency_ms = (time.perf_counter() - started) * 1000.0
    return (text or "").strip(), latency_ms, ""


def run_suite(
    suite: BenchmarkSuite,
    *,
    dry_run: bool = False,
    complete_fn: CompleteFn | None = None,
) -> dict[str, Any]:
    runner = complete_fn or (_mock_complete if dry_run else _live_complete)
    runs: list[TaskRunResult] = []
    latencies: list[float] = []

    for task in suite.tasks:
        for candidate in suite.candidates:
            text, latency_ms, error = runner(candidate, task)
            if latency_ms > 0:
                latencies.append(latency_ms)
            success = bool(text) and evaluate_response(text, task.eval)
            runs.append(
                TaskRunResult(
                    task_id=task.id,
                    profile=task.profile,
                    candidate=candidate.key,
                    provider=candidate.provider,
                    model=candidate.model,
                    orchestrator=candidate.orchestrator,
                    success=success,
                    score=0.0,
                    latency_ms=round(latency_ms, 2),
                    response=text[:500],
                    error=error,
                )
            )

    max_latency = max(latencies) if latencies else 1.0
    for run in runs:
        run.score = score_run(success=run.success, latency_ms=run.latency_ms, max_latency_ms=max_latency)

    rankings = build_rankings(runs)
    return {
        "suite": suite.name,
        "ran_at": _iso_now(),
        "dry_run": dry_run,
        "runs": [asdict(r) for r in runs],
        "rankings": rankings,
    }


def build_rankings(runs: list[TaskRunResult]) -> dict[str, list[dict[str, Any]]]:
    by_profile: dict[str, dict[str, dict[str, Any]]] = {}
    for run in runs:
        bucket = by_profile.setdefault(run.profile, {})
        row = bucket.setdefault(
            run.candidate,
            {
                "candidate": run.candidate,
                "provider": run.provider,
                "model": run.model,
                "orchestrator": run.orchestrator,
                "score_total": 0.0,
                "score_count": 0,
                "latency_ms": 0.0,
                "successes": 0,
                "attempts": 0,
            },
        )
        row["score_total"] += run.score
        row["score_count"] += 1
        row["latency_ms"] += run.latency_ms
        row["successes"] += int(run.success)
        row["attempts"] += 1

    out: dict[str, list[dict[str, Any]]] = {}
    for profile, candidates in by_profile.items():
        ranked: list[dict[str, Any]] = []
        for row in candidates.values():
            count = max(1, row["score_count"])
            ranked.append(
                {
                    "candidate": row["candidate"],
                    "provider": row["provider"],
                    "model": row["model"],
                    "orchestrator": row["orchestrator"],
                    "score": round(row["score_total"] / count, 4),
                    "latency_ms": round(row["latency_ms"] / count, 2),
                    "success_rate": round(row["successes"] / max(1, row["attempts"]), 4),
                }
            )
        ranked.sort(key=lambda item: (-item["score"], item["latency_ms"]))
        out[profile] = ranked
    return out


def store_suite_run(suite_name: str, payload: dict[str, Any]) -> Path:
    data = load_results()
    suites = data.setdefault("suites", {})
    suites[suite_name] = {
        "last_run": payload,
        "rankings": payload.get("rankings") or {},
    }
    return save_results(data)


def rankings_for_profile(profile: str, *, suite_name: str | None = None) -> list[dict[str, Any]]:
    data = load_results()
    suites = data.get("suites") or {}
    if suite_name:
        suite_data = suites.get(suite_name) or {}
        return list((suite_data.get("rankings") or {}).get(profile) or [])
    merged: dict[str, dict[str, Any]] = {}
    for suite_data in suites.values():
        for row in (suite_data.get("rankings") or {}).get(profile) or []:
            key = row.get("candidate") or ""
            prev = merged.get(key)
            if not prev or row.get("score", 0) > prev.get("score", 0):
                merged[key] = dict(row)
    ranked = list(merged.values())
    ranked.sort(key=lambda item: (-item.get("score", 0), item.get("latency_ms", 0)))
    return ranked


def benchmark_chain_entries(task: str, *, top_n: int = 3) -> list[tuple[str, str]]:
    profile = normalize_task(task)
    rows = rankings_for_profile(profile)
    out: list[tuple[str, str]] = []
    for row in rows[:top_n]:
        provider = str(row.get("provider") or "").strip().lower()
        model = str(row.get("model") or "").strip()
        if provider and model:
            out.append((provider, model))
    return out


def apply_rankings(
    *,
    profiles: list[str] | None = None,
    suite_name: str | None = None,
    dry_run: bool = False,
) -> list[tuple[str, str]]:
    targets = profiles or sorted(known_task_profiles())
    applied: list[tuple[str, str]] = []
    for profile in targets:
        rows = rankings_for_profile(profile, suite_name=suite_name)
        if not rows:
            continue
        winner = rows[0]
        provider = str(winner.get("provider") or "").strip()
        model = str(winner.get("model") or "").strip()
        orchestrator = str(winner.get("orchestrator") or "").strip()
        if orchestrator and not (provider and model):
            continue
        if not provider or not model:
            continue
        spec = f"{provider}/{model}"
        applied.append((profile, spec))
        if not dry_run:
            set_skill_model(profile, spec)
    return applied


def format_rankings_text(*, profile: str | None = None) -> str:
    data = load_results()
    suites = data.get("suites") or {}
    if not suites:
        return "No benchmark results yet. Run: arka benchmark run --dry-run"
    lines = [f"Benchmark results (updated {data.get('updated_at') or 'unknown'})"]
    for suite_name, suite_data in sorted(suites.items()):
        rankings = suite_data.get("rankings") or {}
        lines.append(f"\nSuite: {suite_name}")
        profiles = [profile] if profile else sorted(rankings.keys())
        for prof in profiles:
            rows = rankings.get(prof) or []
            if not rows:
                continue
            lines.append(f"  {prof}:")
            for idx, row in enumerate(rows[:5], start=1):
                label = row.get("candidate") or f"{row.get('provider')}/{row.get('model')}"
                lines.append(
                    f"    {idx}. {label}  score={row.get('score')}  "
                    f"latency={row.get('latency_ms')}ms  success={row.get('success_rate')}"
                )
    return "\n".join(lines)


def parse_candidate_specs(raw: list[str]) -> list[BenchmarkCandidate]:
    out: list[BenchmarkCandidate] = []
    for item in raw:
        text = (item or "").strip()
        if not text:
            continue
        if text.startswith("orchestrator:"):
            out.append(BenchmarkCandidate(orchestrator=text.split(":", 1)[1].strip()))
            continue
        entries = parse_chain(text)
        for provider, model_id in entries:
            out.append(BenchmarkCandidate(provider=provider, model=model_id))
    return out
