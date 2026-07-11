"""Execute team workflows — sequential, parallel, and round-robin steps."""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from arka.teams.io import load_team, load_workflow
from arka.teams.mcp_context import build_mcp_context, inject_mcp, resolve_step_mcp
from arka.teams.resolve import ResolvedMember, resolve_team
from arka.teams.schema import Team, Workflow, WorkflowStep

_MCP_TOOL_JSON_RE = re.compile(r"\{[^{}]*\"mcp_tool\"[^{}]*\}", re.DOTALL)


@dataclass
class StepResult:
    role: str
    action: str
    member_kind: str
    member_id: str
    output: str
    ok: bool = True
    error: str = ""
    retries: int = 0
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        row = {
            "role": self.role,
            "action": self.action,
            "member_kind": self.member_kind,
            "member_id": self.member_id,
            "output": self.output,
            "ok": self.ok,
            "error": self.error,
        }
        if self.retries:
            row["retries"] = self.retries
        if self.attempts > 1:
            row["attempts"] = self.attempts
        return row


@dataclass
class RunContext:
    task: str
    team: Team
    workflow: Workflow | None = None
    members: dict[str, ResolvedMember] = field(default_factory=dict)
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
            "transcript": merged,
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


def _resolve_retry_settings(
    step: WorkflowStep,
    team: Team,
    workflow: Workflow,
) -> tuple[int, float]:
    wf_defaults = workflow.defaults or {}
    team_defaults = team.defaults or {}

    retries = step.retries
    if retries is None:
        raw = wf_defaults.get("retries", team_defaults.get("retries", 0))
        retries = int(raw) if raw is not None else 0

    retry_delay = step.retry_delay
    if retry_delay is None:
        raw = wf_defaults.get("retry_delay", team_defaults.get("retry_delay", 1))
        retry_delay = float(raw) if raw is not None else 1.0

    return max(0, int(retries)), max(0.0, float(retry_delay))


def _retry_backoff_enabled() -> bool:
    return os.environ.get("TEAM_RETRY_BACKOFF", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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


def _maybe_run_mcp_tool_loop(
    member: ResolvedMember,
    prompt: str,
    system: str,
    *,
    action: str,
    mcp_servers: list[str],
) -> StepResult | None:
    """Optional single-round MCP tool loop for model steps (TEAM_MCP_TOOL_ROUNDS > 0)."""
    max_rounds = max(0, int(os.environ.get("TEAM_MCP_TOOL_ROUNDS", "0")))
    if max_rounds <= 0 or not mcp_servers:
        return None

    try:
        from arka.llm.fallback import LlmOrchestrator
        from arka.integrations.mcp_manager import call_tool

        orch = LlmOrchestrator(
            task="agent",
            chain=[(member.provider, member.model_id)],
        )
        combined = inject_mcp(system, build_mcp_context(mcp_servers))
        result = orch.complete(combined, prompt, temperature=0.2)
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

        text = (result.text or "").strip()
        match = _MCP_TOOL_JSON_RE.search(text)
        if not match:
            return None

        payload = json.loads(match.group(0))
        server = str(payload.get("mcp_tool") or payload.get("server") or "").strip()
        tool = str(payload.get("tool") or payload.get("name") or "").strip()
        arguments = payload.get("arguments") or {}
        if not server or not tool:
            return None
        if server not in mcp_servers:
            return StepResult(
                role=member.role,
                action=action,
                member_kind=member.member_kind,
                member_id=member.member_id,
                output="",
                ok=False,
                error=f"MCP server {server!r} not enabled for this step",
            )
        tool_out = call_tool(server, tool, arguments if isinstance(arguments, dict) else {})
        followup = (
            f"{text}\n\n[MCP {server}/{tool}]\n{tool_out}\n\n"
            "Summarize the tool result for the workflow step."
        )
        final = orch.complete(combined, followup, temperature=0.2)
        if final.error and not final.text:
            return StepResult(
                role=member.role,
                action=action,
                member_kind=member.member_kind,
                member_id=member.member_id,
                output="",
                ok=False,
                error=final.error,
            )
        output = (final.text or "").strip() or tool_out.strip() or "(no output)"
        return StepResult(
            role=member.role,
            action=action,
            member_kind=member.member_kind,
            member_id=member.member_id,
            output=output,
            ok=True,
        )
    except Exception:
        return None


def _run_llm(
    member: ResolvedMember,
    prompt: str,
    *,
    action: str,
    system: str,
    mcp_servers: list[str] | None = None,
) -> StepResult:
    servers = list(mcp_servers or [])
    loop_result = _maybe_run_mcp_tool_loop(
        member,
        prompt,
        system,
        action=action,
        mcp_servers=servers,
    )
    if loop_result is not None:
        return loop_result

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


def _step_mcp_context(step: WorkflowStep, ctx: RunContext) -> str:
    if ctx.workflow is None:
        return ""
    enabled, servers = resolve_step_mcp(step, ctx.team, ctx.workflow)
    if not enabled:
        return ""
    return build_mcp_context(servers)


def execute_member(
    ctx: RunContext,
    member_role: str,
    action: str,
    prompt: str,
    *,
    step: WorkflowStep | None = None,
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

    mcp_context = ""
    mcp_servers: list[str] = []
    if step is not None and ctx.workflow is not None:
        enabled, mcp_servers = resolve_step_mcp(step, ctx.team, ctx.workflow)
        if enabled:
            mcp_context = build_mcp_context(mcp_servers)
            system = inject_mcp(system, mcp_context)

    if runner is not None:
        if mcp_context and member.kind == "agent":
            rendered = f"{mcp_context}\n\n{rendered}"
        return runner(member, rendered, system)

    if member.kind == "agent":
        if mcp_context:
            rendered = f"{mcp_context}\n\n{rendered}"
        return _run_agent(member, rendered, action=action)
    return _run_llm(
        member,
        rendered,
        action=action,
        system=system,
        mcp_servers=mcp_servers,
    )


def execute_member_with_retries(
    ctx: RunContext,
    member_role: str,
    action: str,
    prompt: str,
    *,
    step: WorkflowStep | None = None,
    workflow: Workflow,
    runner: Callable[[ResolvedMember, str, str], StepResult] | None = None,
) -> StepResult:
    pseudo_step = step or WorkflowStep(member=member_role, action=action, prompt=prompt)
    max_retries, delay = _resolve_retry_settings(pseudo_step, ctx.team, workflow)
    last: StepResult | None = None

    for attempt in range(max_retries + 1):
        result = execute_member(
            ctx,
            member_role,
            action,
            prompt,
            step=pseudo_step,
            runner=runner,
        )
        result.attempts = attempt + 1
        if result.ok:
            result.retries = attempt
            return result
        last = result
        if attempt < max_retries:
            wait = delay * (2**attempt) if _retry_backoff_enabled() else delay
            if wait > 0:
                time.sleep(wait)

    assert last is not None
    last.retries = max_retries
    last.attempts = max_retries + 1
    return last


def _execute_step(
    ctx: RunContext,
    step: WorkflowStep,
    *,
    workflow: Workflow,
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
                    execute_member_with_retries,
                    ctx,
                    sub.member,
                    sub.action,
                    sub.prompt,
                    step=sub,
                    workflow=workflow,
                    runner=runner,
                ): sub
                for sub in step.parallel
            }
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda r: r.role)
        return results

    result = execute_member_with_retries(
        ctx,
        step.member,
        step.action,
        step.prompt,
        step=step,
        workflow=workflow,
        runner=runner,
    )
    return [result]


def _round_robin_roles(workflow: Workflow, ctx: RunContext) -> list[str]:
    if workflow.members:
        roles = list(workflow.members)
    else:
        roles = [m.role for m in ctx.team.members]
    missing = [role for role in roles if role not in ctx.members]
    if missing:
        raise ValueError(f"Round-robin member roles not in team: {', '.join(missing)}")
    if not roles:
        raise ValueError("Round-robin workflow has no members")
    return roles


def _execute_round_robin(
    ctx: RunContext,
    workflow: Workflow,
    *,
    runner: Callable[[ResolvedMember, str, str], StepResult] | None = None,
) -> list[StepResult]:
    roles = _round_robin_roles(workflow, ctx)
    pseudo_step = WorkflowStep(prompt=workflow.prompt, mcp=workflow.defaults.get("mcp"))
    if workflow.defaults.get("mcp_servers"):
        pseudo_step.mcp_servers = list(workflow.defaults.get("mcp_servers") or [])

    all_results: list[StepResult] = []
    for turn in range(workflow.max_turns):
        role = roles[turn % len(roles)]
        action = f"turn-{turn + 1}"
        result = execute_member_with_retries(
            ctx,
            role,
            action,
            workflow.prompt,
            step=pseudo_step,
            workflow=workflow,
            runner=runner,
        )
        ctx.results.append(result)
        all_results.append(result)
    return all_results


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
        workflow=workflow,
        members=members,
        memory_context=_memory_context(team, task),
    )
    if not ctx.task:
        raise ValueError("task is required")

    if workflow.mode == "round_robin":
        all_results = _execute_round_robin(ctx, workflow, runner=runner)
    else:
        all_results = []
        for step in workflow.steps:
            step_results = _execute_step(ctx, step, workflow=workflow, runner=runner)
            ctx.results.extend(step_results)
            all_results.extend(step_results)

    final = ctx.results[-1].output if ctx.results else ""
    ok = all(r.ok for r in all_results) if all_results else False
    return {
        "team": team.name,
        "workflow": workflow.name,
        "mode": workflow.mode,
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
        f"mode\t{result.get('mode', 'sequential')}",
        f"ok\t{result.get('ok')}",
        f"task\t{result.get('task')}",
    ]
    for idx, step in enumerate(result.get("steps") or [], start=1):
        status = "ok" if step.get("ok") else "fail"
        retry_note = ""
        if step.get("retries"):
            retry_note = f"\tretries={step.get('retries')}"
        elif step.get("attempts", 1) > 1:
            retry_note = f"\tattempts={step.get('attempts')}"
        lines.append(
            f"step_{idx}\t{step.get('role')}\t{step.get('action')}\t{status}{retry_note}\t"
            f"{str(step.get('output', ''))[:120]}"
        )
        if step.get("error"):
            lines.append(f"  error\t{step.get('error')}")
    lines.append("final\t" + str(result.get("final", "")))
    return "\n".join(lines)
