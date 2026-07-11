"""Execute team workflows — sequential and parallel steps."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from arka.teams.io import load_team, load_workflow
from arka.teams.resolve import ResolvedMember, resolve_team
from arka.teams.schema import Team, Workflow, WorkflowStep


@dataclass
class StepResult:
    role: str
    action: str
    member_kind: str
    member_id: str
    output: str
    ok: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "action": self.action,
            "member_kind": self.member_kind,
            "member_id": self.member_id,
            "output": self.output,
            "ok": self.ok,
            "error": self.error,
        }


@dataclass
class RunContext:
    task: str
    team: Team
    members: dict[str, ResolvedMember]
    results: list[StepResult] = field(default_factory=list)
    memory_context: str = ""

    def vars(self) -> dict[str, str]:
        merged = "\n\n".join(
            f"[{r.role}/{r.action}]\n{r.output}"
            for r in self.results
            if r.output
        )
        values = {
            "task": self.task,
            "results": merged,
            "last_result": self.results[-1].output if self.results else "",
        }
        for idx, result in enumerate(self.results, start=1):
            values[f"step_{idx}"] = result.output
            values[f"{result.role}"] = result.output
        return values

    def render(self, template: str) -> str:
        text = template or ""
        for key, value in self.vars().items():
            text = text.replace("{" + key + "}", value)
        return text.strip()


def _memory_context(team: Team, task: str) -> str:
    if team.defaults.get("memory", "unified") in (False, "off", "none", "0"):
        return ""
    try:
        from arka.core.unified_memory import recall

        return recall(task, limit_chars=2500)
    except Exception:
        return ""


def _run_agent(member: ResolvedMember, prompt: str, *, action: str) -> StepResult:
    header = (
        f"[Arka team step | role={member.role} | agent={member.agent_name} | action={action}]\n"
    )
    full_prompt = header + prompt
    try:
        from arka.agent.chat import answer_question

        _, answer = answer_question(full_prompt, deep=False, use_session=False, cleanup=True)
        output = (answer or "").strip() or "(no output)"
        return StepResult(
            role=member.role,
            action=action,
            member_kind=member.member_kind,
            member_id=member.member_id,
            output=output,
            ok=True,
        )
    except Exception as exc:
        return StepResult(
            role=member.role,
            action=action,
            member_kind=member.member_kind,
            member_id=member.member_id,
            output="",
            ok=False,
            error=str(exc),
        )


def _run_llm(member: ResolvedMember, prompt: str, *, action: str, system: str) -> StepResult:
    try:
        from arka.llm.fallback import LlmOrchestrator

        orch = LlmOrchestrator(
            task="agent",
            chain=[(member.provider, member.model_id)],
        )
        result = orch.complete(system, prompt, temperature=0.2)
        if result.error and not result.text:
            return StepResult(
                role=member.role,
                action=action,
                member_kind=member.member_kind,
                member_id=member.member_id,
                output="",
                ok=False,
                error=result.error,
            )
        output = (result.text or "").strip() or "(no output)"
        return StepResult(
            role=member.role,
            action=action,
            member_kind=member.member_kind,
            member_id=member.member_id,
            output=output,
            ok=True,
        )
    except Exception as exc:
        return StepResult(
            role=member.role,
            action=action,
            member_kind=member.member_kind,
            member_id=member.member_id,
            output="",
            ok=False,
            error=str(exc),
        )


def _default_system(ctx: RunContext, member: ResolvedMember, action: str) -> str:
    parts = [
        f"You are the {member.role} member of team {ctx.team.name}.",
        f"Action: {action}.",
    ]
    if ctx.team.description:
        parts.append(f"Team purpose: {ctx.team.description}")
    if ctx.memory_context:
        parts.append(f"Shared memory:\n{ctx.memory_context}")
    return "\n".join(parts)


def execute_member(
    ctx: RunContext,
    member_role: str,
    action: str,
    prompt: str,
    *,
    runner: Callable[[ResolvedMember, str, str], StepResult] | None = None,
) -> StepResult:
    member = ctx.members.get(member_role)
    if not member:
        return StepResult(
            role=member_role,
            action=action,
            member_kind="?",
            member_id="?",
            output="",
            ok=False,
            error=f"Unknown team role: {member_role}",
        )
    rendered = ctx.render(prompt) if prompt else ctx.task
    if not rendered:
        rendered = ctx.task
    system = _default_system(ctx, member, action)

    if runner is not None:
        return runner(member, rendered, system)

    if member.kind == "agent":
        return _run_agent(member, rendered, action=action)
    return _run_llm(member, rendered, action=action, system=system)


def _execute_step(
    ctx: RunContext,
    step: WorkflowStep,
    *,
    runner: Callable[[ResolvedMember, str, str], StepResult] | None = None,
) -> list[StepResult]:
    if step.parallel:
        max_workers = min(
            len(step.parallel),
            max(1, int(os.environ.get("TEAM_MAX_PARALLEL", "4"))),
        )
        results: list[StepResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    execute_member,
                    ctx,
                    sub.member,
                    sub.action,
                    sub.prompt,
                    runner=runner,
                ): sub
                for sub in step.parallel
            }
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda r: r.role)
        return results

    result = execute_member(ctx, step.member, step.action, step.prompt, runner=runner)
    return [result]


def execute_workflow(
    workflow: Workflow,
    task: str,
    *,
    team: Team | None = None,
    runner: Callable[[ResolvedMember, str, str], StepResult] | None = None,
) -> dict[str, Any]:
    team = team or load_team(workflow.team)
    members = resolve_team(team)
    ctx = RunContext(
        task=task.strip(),
        team=team,
        members=members,
        memory_context=_memory_context(team, task),
    )
    if not ctx.task:
        raise ValueError("task is required")

    all_results: list[StepResult] = []
    for step in workflow.steps:
        step_results = _execute_step(ctx, step, runner=runner)
        ctx.results.extend(step_results)
        all_results.extend(step_results)

    final = ctx.results[-1].output if ctx.results else ""
    ok = all(r.ok for r in all_results) if all_results else False
    return {
        "team": team.name,
        "workflow": workflow.name,
        "task": ctx.task,
        "ok": ok,
        "final": final,
        "steps": [r.to_dict() for r in all_results],
    }


def run_workflow(name: str, task: str, **kwargs: Any) -> dict[str, Any]:
    workflow = load_workflow(name)
    return execute_workflow(workflow, task, **kwargs)


def run_team(
    name: str,
    task: str,
    *,
    workflow_name: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    team = load_team(name)
    wf_name = workflow_name or team.defaults.get("workflow")
    if not wf_name:
        available = [w for w in _workflows_for_team(team.name)]
        if len(available) == 1:
            wf_name = available[0]
        else:
            raise ValueError(
                f"No workflow for team {name!r}. Pass --workflow or set defaults.workflow"
            )
    workflow = load_workflow(str(wf_name))
    if workflow.team != team.name:
        raise ValueError(
            f"Workflow {workflow.name!r} is for team {workflow.team!r}, not {team.name!r}"
        )
    return execute_workflow(workflow, task, team=team, **kwargs)


def _workflows_for_team(team_name: str) -> list[str]:
    from arka.teams.io import list_workflows, load_workflow

    matches: list[str] = []
    for name in list_workflows():
        try:
            wf = load_workflow(name)
            if wf.team == team_name:
                matches.append(name)
        except (ValueError, FileNotFoundError):
            continue
    return matches


def format_run_result(result: dict[str, Any]) -> str:
    lines = [
        f"team\t{result.get('team')}",
        f"workflow\t{result.get('workflow')}",
        f"ok\t{result.get('ok')}",
        f"task\t{result.get('task')}",
    ]
    for idx, step in enumerate(result.get("steps") or [], start=1):
        status = "ok" if step.get("ok") else "fail"
        lines.append(
            f"step_{idx}\t{step.get('role')}\t{step.get('action')}\t{status}\t"
            f"{str(step.get('output', ''))[:120]}"
        )
        if step.get("error"):
            lines.append(f"  error\t{step.get('error')}")
    lines.append("final\t" + str(result.get("final", "")))
    return "\n".join(lines)
