"""YAML-driven agent harness — route, skill, and agent smoke tasks."""

from __future__ import annotations

import io
import json
import os
import shutil
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arka.llm.benchmarks import evaluate_response


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def harnesses_dir() -> Path:
    from arka.paths import config_dir

    return config_dir() / "harnesses"


def results_path() -> Path:
    from arka.paths import config_dir

    return config_dir() / "harness-results.json"


def bundled_default_suite() -> Path:
    from arka.paths import package_dir

    return package_dir() / "agent" / "templates" / "harness-default.yaml"


def default_suite_path() -> Path:
    return harnesses_dir() / "default.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@dataclass
class HarnessTask:
    id: str
    prompt: str
    backend: str = "route"
    expect_route: str = ""
    eval: dict[str, Any] = field(default_factory=dict)
    dry_response: str = ""
    timeout_s: int = 120

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HarnessTask:
        return cls(
            id=str(raw.get("id") or "").strip(),
            prompt=str(raw.get("prompt") or "").strip(),
            backend=str(raw.get("backend") or "route").strip().lower(),
            expect_route=str(raw.get("expect_route") or "").strip().lower(),
            eval=dict(raw.get("eval") or {}),
            dry_response=str(raw.get("dry_response") or "").strip(),
            timeout_s=int(raw.get("timeout_s") or 120),
        )


@dataclass
class HarnessSuite:
    name: str
    description: str = ""
    tasks: list[HarnessTask] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HarnessSuite:
        return cls(
            name=str(raw.get("name") or "default").strip(),
            description=str(raw.get("description") or "").strip(),
            tasks=[HarnessTask.from_dict(t) for t in raw.get("tasks") or []],
        )


@dataclass
class HarnessTaskResult:
    task_id: str
    backend: str
    passed: bool
    exit_code: int
    wall_ms: float
    route_skill: str = ""
    response: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_default_suite() -> Path:
    harnesses_dir().mkdir(parents=True, exist_ok=True)
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
    for path in sorted(harnesses_dir().glob("*")):
        if path.suffix.lower() in {".yaml", ".yml"}:
            names.append(path.stem)
    return names


def load_suite(name: str | None = None) -> HarnessSuite:
    suite_name = (name or "default").strip() or "default"
    path = harnesses_dir() / f"{suite_name}.yaml"
    if not path.is_file():
        path = harnesses_dir() / f"{suite_name}.yml"
    if not path.is_file() and suite_name == "default":
        ensure_default_suite()
        path = default_suite_path()
    if not path.is_file():
        raise FileNotFoundError(f"harness suite not found: {suite_name}")
    return HarnessSuite.from_dict(_load_yaml(path))


def _skill_head(line: str) -> str:
    return (line or "").strip().split()[0].lower().replace("-", "_")


def _route_prompt(prompt: str) -> tuple[str, str]:
    from arka.router import route

    decision = route(prompt)
    skill = (decision.skill or "").strip()
    return skill, _skill_head(skill)


def _run_skill_line(line: str) -> tuple[str, int]:
    from arka.dispatch import run_skill

    buf = io.StringIO()
    os.environ["ARKA_CAPTURE_STDIO"] = "1"
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            code = run_skill(line)
    finally:
        os.environ.pop("ARKA_CAPTURE_STDIO", None)
    return buf.getvalue(), int(code or 0)


def _run_agent_prompt(prompt: str) -> tuple[str, int]:
    from arka.integrations.remote_server import iter_agent_remote

    parts: list[str] = []
    code = 1
    for chunk, exit_code in iter_agent_remote(prompt, channel="harness", chat_id="harness"):
        if exit_code is not None:
            code = int(exit_code)
            break
        if chunk:
            parts.append(chunk)
    return "".join(parts), code


def _route_matches(skill_line: str, expect_route: str) -> bool:
    if not expect_route:
        return bool(skill_line.strip())
    head = _skill_head(skill_line)
    want = expect_route.strip().lower().replace("-", "_")
    return want == head or want in head or head.startswith(want)


def run_task(task: HarnessTask, *, dry_run: bool = False) -> HarnessTaskResult:
    started = time.perf_counter()
    backend = task.backend or "route"
    route_skill = ""
    response = ""
    error = ""
    exit_code = 0

    try:
        if dry_run and task.dry_response:
            response = task.dry_response
            route_skill = "dry-run"
        elif backend == "route":
            route_skill, _head = _route_prompt(task.prompt)
            response = route_skill
            if task.expect_route and not _route_matches(route_skill, task.expect_route):
                error = f"expected route {task.expect_route!r}, got {route_skill!r}"
        elif backend == "skill":
            route_skill, _head = _route_prompt(task.prompt)
            line = route_skill or task.prompt
            if dry_run:
                response = task.dry_response or f"[dry-run] would run skill: {line}"
            else:
                response, exit_code = _run_skill_line(line)
        elif backend == "agent":
            if dry_run:
                response = task.dry_response or f"[dry-run] would run agent: {task.prompt}"
            else:
                response, exit_code = _run_agent_prompt(task.prompt)
                route_skill = "agent"
        else:
            error = f"unknown backend: {backend}"
            exit_code = 1
    except Exception as exc:
        error = str(exc)
        exit_code = 1

    wall_ms = round((time.perf_counter() - started) * 1000, 2)
    passed = not error and exit_code == 0
    if passed and task.expect_route and backend == "route":
        passed = _route_matches(route_skill, task.expect_route)
    if passed and task.eval:
        passed = evaluate_response(response, task.eval)
    if error:
        passed = False

    return HarnessTaskResult(
        task_id=task.id,
        backend=backend,
        passed=passed,
        exit_code=exit_code,
        wall_ms=wall_ms,
        route_skill=route_skill,
        response=response[:4000],
        error=error,
    )


def run_suite(suite: HarnessSuite, *, dry_run: bool = False) -> dict[str, Any]:
    results = [run_task(task, dry_run=dry_run).to_dict() for task in suite.tasks]
    passed = sum(1 for row in results if row.get("passed"))
    failed = len(results) - passed
    return {
        "suite": suite.name,
        "description": suite.description,
        "dry_run": dry_run,
        "at": _iso_now(),
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "tasks": results,
    }


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


def store_suite_run(suite_name: str, payload: dict[str, Any]) -> Path:
    data = load_results()
    suites = data.setdefault("suites", {})
    runs = suites.setdefault(suite_name, [])
    if not isinstance(runs, list):
        runs = suites[suite_name] = []
    runs.append(payload)
    suites[suite_name] = runs[-20:]
    return save_results(data)


def format_results_text(*, suite_name: str | None = None) -> str:
    data = load_results()
    suites = data.get("suites") or {}
    if not suites:
        return "No harness results yet. Run: arka harness run [--dry-run]"
    lines = [f"Harness results (updated {data.get('updated_at') or '—'})"]
    names = [suite_name] if suite_name else sorted(suites.keys())
    for name in names:
        if not name or name not in suites:
            continue
        runs = suites[name]
        if not runs:
            continue
        latest = runs[-1]
        lines.append(
            f"\n{name}: {latest.get('passed', 0)}/{latest.get('total', 0)} passed "
            f"({'dry-run' if latest.get('dry_run') else 'live'})"
        )
        for row in latest.get("tasks") or []:
            mark = "ok" if row.get("passed") else "FAIL"
            lines.append(
                f"  [{mark}] {row.get('task_id')} ({row.get('backend')}, {row.get('wall_ms')}ms)"
            )
            if row.get("error"):
                lines.append(f"       error: {row['error']}")
    return "\n".join(lines)


def harness_payload(
    *,
    action: str = "run",
    suite: str = "default",
    dry_run: bool = False,
    task_id: str = "",
) -> dict[str, Any]:
    action = (action or "run").strip().lower()
    if action == "init":
        path = ensure_default_suite()
        return {"ok": True, "action": "init", "path": str(path)}
    if action == "list":
        return {"ok": True, "action": "list", "suites": list_suites()}
    if action == "show":
        return {
            "ok": True,
            "action": "show",
            "report": format_results_text(suite_name=suite or None),
        }
    if action == "run":
        loaded = load_suite(suite)
        tasks = loaded.tasks
        if task_id:
            tasks = [t for t in tasks if t.id == task_id]
            if not tasks:
                return {"ok": False, "error": f"task not found: {task_id}"}
            loaded = HarnessSuite(name=loaded.name, description=loaded.description, tasks=tasks)
        payload = run_suite(loaded, dry_run=dry_run)
        path = store_suite_run(loaded.name, payload)
        return {
            "ok": payload.get("failed", 1) == 0,
            "action": "run",
            "results_path": str(path),
            **payload,
        }
    return {"ok": False, "error": f"unknown action: {action}"}
