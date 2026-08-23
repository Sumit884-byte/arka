"""Symbolic parallel decomposition for sub-agent workflows."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from arka.paths import cache_dir

RUNS_FILE = cache_dir() / "parallel-runs.json"

FILE_PATH_RE = re.compile(
    r"(?:~|/|\./|\.\./)?[\w./~-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|md|json|ya?ml|toml|css|html?)\b",
    re.I,
)

SEQUENTIAL_SPLIT_RE = re.compile(
    r"(?i)\s+(?:;\s*|\bthen\b|\bafter(?:\s+that|\s+wards)?\b|\bnext\b|\bfollowed\s+by\b)\s+",
)

PARALLEL_MARKERS = (
    r"\bin\s+parallel\b",
    r"\bconcurrently\b",
    r"\bat\s+the\s+same\s+time\b",
    r"\bsimultaneously\b",
)

DOMAIN_PAIRS: tuple[tuple[str, str], ...] = (
    ("frontend", "backend"),
    ("client", "server"),
    ("ui", "api"),
    ("web", "mobile"),
    ("unit tests?", "integration tests?"),
    ("tests?", "lint"),
    ("docs?", "code"),
)

ACTION_VERBS = (
    "fix",
    "update",
    "refactor",
    "review",
    "lint",
    "test",
    "implement",
    "add",
    "remove",
    "migrate",
    "deploy",
    "write",
    "patch",
)


@dataclass(frozen=True)
class ParallelTask:
    id: str
    goal: str
    rule: str
    paths: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass
class ParallelPlan:
    goal: str
    tasks: list[ParallelTask]
    mode: str
    reasoning: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "mode": self.mode,
            "reasoning": list(self.reasoning),
            "tasks": [
                {
                    "id": task.id,
                    "goal": task.goal,
                    "rule": task.rule,
                    "paths": list(task.paths),
                    "depends_on": list(task.depends_on),
                }
                for task in self.tasks
            ],
        }


def _task_id(index: int) -> str:
    return f"t{index + 1}"


def _extract_paths(text: str) -> list[str]:
    return [match.group(0) for match in FILE_PATH_RE.finditer(text)]


def _has_parallel_marker(text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in PARALLEL_MARKERS)


def _strip_parallel_markers(text: str) -> str:
    out = text
    for pattern in PARALLEL_MARKERS:
        out = re.sub(pattern, " ", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip(" ,;")


def _looks_independent_clause(clause: str) -> bool:
    clean = clause.strip()
    if not clean:
        return False
    if re.search(r"(?i)\b(?:" + "|".join(ACTION_VERBS) + r")\b", clean):
        return True
    return bool(_extract_paths(clean))


def _split_quoted(text: str) -> list[str] | None:
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    items = [(left or right).strip() for left, right in quoted if (left or right).strip()]
    if len(items) >= 2:
        return items
    return None


def _split_domain_pair(text: str) -> tuple[list[str], str] | None:
    for left, right in DOMAIN_PAIRS:
        pattern = rf"(?i)\b({left})\b.*\band\b.*\b({right})\b"
        match = re.search(pattern, text)
        if not match:
            pattern = rf"(?i)\b({right})\b.*\band\b.*\b({left})\b"
            match = re.search(pattern, text)
        if match:
            a, b = match.group(1), match.group(2)
            verb = _leading_verb(text) or "update"
            return [f"{verb} {a}", f"{verb} {b}"], f"domain_pair:{a}/{b}"
    return None


def _leading_verb(text: str) -> str | None:
    match = re.match(rf"(?i)\b({'|'.join(ACTION_VERBS)})\b", text.strip())
    return match.group(1).lower() if match else None


def _split_file_paths(text: str) -> tuple[list[str], str] | None:
    paths = _extract_paths(text)
    if len(paths) < 2:
        return None
    verb = _leading_verb(text)
    if not verb and not re.search(r"(?i)\b(?:fix|update|lint|test|refactor|review)\b", text):
        return None
    verb = verb or "fix"
    subject = re.sub(FILE_PATH_RE, " ", text)
    subject = re.sub(r"\s+", " ", subject).strip(" ,;")
    subject = re.sub(r"(?i)\b(?:in|for|on)\s+$", "", subject).strip()
    tasks = []
    for path in paths:
        if subject:
            tasks.append(f"{subject} {path}".strip())
        else:
            tasks.append(f"{verb} {path}")
    return tasks, "file_path_disjoint"


def _split_and_targets(text: str) -> tuple[list[str], str] | None:
    match = re.search(
        rf"(?i)^((?:{'|'.join(ACTION_VERBS)})(?:\s+\w+){{0,4}})\s+(?:in|for|on)\s+(.+?)\s+and\s+(.+)$",
        text.strip(),
    )
    if not match:
        return None
    prefix, left, right = match.group(1), match.group(2).strip(), match.group(3).strip()
    if not left or not right:
        return None
    return [f"{prefix} {left}".strip(), f"{prefix} {right}".strip()], "and_targets"


def _split_commas(text: str) -> tuple[list[str], str] | None:
    if _has_parallel_marker(text):
        text = _strip_parallel_markers(text)
    parts = [part.strip() for part in re.split(r"\s*,\s*", text) if part.strip()]
    if len(parts) < 2:
        return None
    if not all(_looks_independent_clause(part) for part in parts):
        return None
    return parts, "comma_clauses"


def _split_explicit_parallel(text: str) -> tuple[list[str], str] | None:
    if not _has_parallel_marker(text):
        return None
    body = _strip_parallel_markers(text)
    if " and " in body.lower():
        parts = re.split(r"(?i)\s+and\s+", body)
        parts = [part.strip(" ,") for part in parts if part.strip(" ,")]
        if len(parts) >= 2:
            return parts, "explicit_parallel_and"
    quoted = _split_quoted(body)
    if quoted:
        return quoted, "explicit_parallel_quoted"
    comma = _split_commas(body)
    if comma:
        return comma[0], "explicit_parallel_comma"
    return None


def _decompose_segment(text: str, *, reasoning: list[str]) -> list[ParallelTask]:
    clean = text.strip()
    if not clean:
        return []

    splitters: tuple[tuple[str, object], ...] = (
        ("quoted_clauses", _split_quoted),
        ("explicit_parallel", _split_explicit_parallel),
        ("and_targets", _split_and_targets),
        ("domain_pair", _split_domain_pair),
        ("comma_clauses", _split_commas),
        ("file_path_disjoint", _split_file_paths),
    )
    for label, splitter in splitters:
        hit = splitter(clean)
        if not hit:
            continue
        if isinstance(hit, tuple):
            goals, rule = hit
        else:
            goals, rule = hit, label
        reasoning.append(f"{rule}: matched {len(goals)} independent subtasks")
        return [
            ParallelTask(
                id=_task_id(index),
                goal=goal,
                rule=rule,
                paths=tuple(_extract_paths(goal)),
            )
            for index, goal in enumerate(goals)
        ]

    reasoning.append("single_task: no parallel decomposition rule matched")
    return [
        ParallelTask(
            id=_task_id(0),
            goal=clean,
            rule="single_task",
            paths=tuple(_extract_paths(clean)),
        )
    ]


def decompose_parallel(goal: str) -> ParallelPlan:
    """Split a natural-language goal into parallel or sequential subtasks."""
    text = (goal or "").strip()
    reasoning: list[str] = []
    if not text:
        return ParallelPlan(goal="", tasks=[], mode="empty", reasoning=["empty goal"])

    segments = [part.strip() for part in SEQUENTIAL_SPLIT_RE.split(text) if part.strip()]
    if len(segments) > 1:
        reasoning.append(f"sequential_marker: split into {len(segments)} ordered phases")
        tasks: list[ParallelTask] = []
        previous_id: str | None = None
        for segment in segments:
            segment_tasks = _decompose_segment(segment, reasoning=reasoning)
            if previous_id and segment_tasks:
                first = segment_tasks[0]
                segment_tasks[0] = ParallelTask(
                    id=first.id,
                    goal=first.goal,
                    rule=first.rule,
                    paths=first.paths,
                    depends_on=(previous_id,),
                )
            tasks.extend(segment_tasks)
            previous_id = tasks[-1].id if tasks else previous_id
        mode = "mixed" if any(task.depends_on for task in tasks) and len(tasks) > 1 else "sequential"
        if mode == "mixed" and not any(task.depends_on for task in tasks[1:]):
            mode = "sequential"
        parallelizable = sum(1 for task in tasks if not task.depends_on)
        if parallelizable > 1 and any(task.depends_on for task in tasks):
            mode = "mixed"
        elif parallelizable > 1:
            mode = "parallel"
        return ParallelPlan(goal=text, tasks=tasks, mode=mode, reasoning=reasoning)

    tasks = _decompose_segment(text, reasoning=reasoning)
    mode = "parallel" if len(tasks) > 1 else "sequential"
    return ParallelPlan(goal=text, tasks=tasks, mode=mode, reasoning=reasoning)


def format_plan(plan: ParallelPlan) -> str:
    lines = [
        f"Goal: {plan.goal}",
        f"Mode: {plan.mode}",
        "Reasoning:",
    ]
    lines.extend(f"  - {line}" for line in plan.reasoning)
    lines.append("Tasks:")
    for task in plan.tasks:
        deps = f" (after {', '.join(task.depends_on)})" if task.depends_on else ""
        lines.append(f"  [{task.id}] {task.goal}{deps}")
        lines.append(f"       rule={task.rule}")
        if task.paths:
            lines.append(f"       paths={', '.join(task.paths)}")
    return "\n".join(lines)


def _save_run(record: dict[str, object]) -> None:
    RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = json.loads(RUNS_FILE.read_text(encoding="utf-8")) if RUNS_FILE.is_file() else {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw[str(record["plan_id"])] = record
    RUNS_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def load_run(plan_id: str) -> dict[str, object] | None:
    if not RUNS_FILE.is_file():
        return None
    try:
        raw = json.loads(RUNS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    row = raw.get(plan_id) if isinstance(raw, dict) else None
    return row if isinstance(row, dict) else None


def run_parallel_subagents(
    plan: ParallelPlan,
    *,
    sync: bool = False,
    plan_id: str | None = None,
) -> dict[str, object]:
    """Execute plan tasks via existing sub-agent spawn infrastructure."""
    from arka.integrations.subagent import agent_status, spawn

    run_id = plan_id or uuid.uuid4().hex[:10]
    agents: list[dict[str, object]] = []
    completed: set[str] = set()
    pending = list(plan.tasks)

    while pending:
        ready = [task for task in pending if all(dep in completed for dep in task.depends_on)]
        if not ready:
            break
        batch = ready if len(ready) > 1 and not any(task.depends_on for task in ready) else ready[:1]
        for task in batch:
            data, err = spawn(task.goal, background=not sync)
            row: dict[str, object] = {
                "task_id": task.id,
                "goal": task.goal,
                "rule": task.rule,
                "error": err,
            }
            if data:
                row["agent_id"] = data.get("id")
                row["status"] = data.get("status")
                row["exit_code"] = data.get("exit_code")
                if sync:
                    latest = agent_status(str(data.get("id") or "")) or data
                    row["status"] = latest.get("status")
                    row["exit_code"] = latest.get("exit_code")
                    row["result"] = latest.get("result")
            agents.append(row)
            completed.add(task.id)
        pending = [task for task in pending if task.id not in completed]

    record = {
        "plan_id": run_id,
        "goal": plan.goal,
        "mode": plan.mode,
        "sync": sync,
        "agents": agents,
        "plan": plan.to_dict(),
    }
    _save_run(record)
    return record


def route_command(text: str) -> str | None:
    clean = text.strip()
    low = clean.lower()
    if re.search(r"\b(?:parallel\s+plan|plan\s+parallel)\b", low):
        goal = re.sub(r"(?i)\b(?:parallel\s+plan|plan\s+parallel)\b", "", clean).strip(" :-")
        return "parallel plan " + goal if goal else "parallel plan"
    if re.search(r"\b(?:parallel\s+run|run\s+parallel)\b", low):
        goal = re.sub(r"(?i)\b(?:parallel\s+run|run\s+parallel)\b", "", clean).strip(" :-")
        return "parallel run " + goal if goal else "parallel run"
    if re.search(r"\b(?:decompose|split)\b.*\b(?:parallel|subagents?|sub-agents?)\b", low):
        goal = re.sub(r"(?i)\b(?:decompose|split)\b", "", clean).strip(" :-")
        goal = re.sub(r"(?i)\b(?:into\s+)?(?:parallel\s+)?(?:subagents?|sub-agents?)\b", "", goal).strip(" :-")
        return "parallel plan " + goal if goal else "parallel plan"
    if _has_parallel_marker(clean) and re.search(r"\b(?:fix|update|implement|run|do)\b", low):
        return "parallel plan " + clean
    return None
