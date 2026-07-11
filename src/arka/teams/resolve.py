"""Resolve team members to concrete execution targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from arka.teams.schema import Team, TeamMember

TargetKind = Literal["agent", "llm"]


@dataclass
class ResolvedMember:
    role: str
    kind: TargetKind
    member_kind: str
    member_id: str
    provider: str = ""
    model_id: str = ""
    agent_key: str = ""
    agent_name: str = ""
    meta: dict[str, Any] | None = None


def _resolve_agent(member: TeamMember) -> ResolvedMember:
    from arka.integrations.agent_hub import AGENTS, _resolve_agent

    resolved = _resolve_agent(member.id)
    if not resolved:
        known = ", ".join(sorted(AGENTS))
        raise ValueError(f"Unknown agent {member.id!r}. Known: {known}")
    agent_key, meta = resolved
    return ResolvedMember(
        role=member.role,
        kind="agent",
        member_kind="agent",
        member_id=member.id,
        agent_key=agent_key,
        agent_name=str(meta.get("name") or agent_key),
        meta=meta,
    )


def _resolve_model(member: TeamMember) -> ResolvedMember:
    from arka.llm.providers import get_provider

    provider = get_provider(member.provider)
    if not provider:
        raise ValueError(f"Unknown provider {member.provider!r} for model {member.id!r}")
    return ResolvedMember(
        role=member.role,
        kind="llm",
        member_kind="model",
        member_id=member.id,
        provider=provider.slug,
        model_id=member.id,
    )


def _resolve_provider(member: TeamMember) -> ResolvedMember:
    from arka.llm.providers import get_provider

    provider = get_provider(member.id)
    if not provider:
        raise ValueError(f"Unknown provider {member.id!r}")
    return ResolvedMember(
        role=member.role,
        kind="llm",
        member_kind="provider",
        member_id=member.id,
        provider=provider.slug,
        model_id=provider.default_model,
    )


def resolve_member(member: TeamMember) -> ResolvedMember:
    if member.kind == "agent":
        return _resolve_agent(member)
    if member.kind == "model":
        return _resolve_model(member)
    if member.kind == "provider":
        return _resolve_provider(member)
    raise ValueError(f"Unsupported member kind: {member.kind}")


def resolve_team(team: Team) -> dict[str, ResolvedMember]:
    resolved: dict[str, ResolvedMember] = {}
    for member in team.members:
        if member.role in resolved:
            raise ValueError(f"Duplicate role in team: {member.role}")
        resolved[member.role] = resolve_member(member)
    return resolved


def format_resolved(team: Team) -> str:
    rows = resolve_team(team)
    lines = [f"team\t{team.name}\tmembers={len(rows)}"]
    for role, member in sorted(rows.items()):
        if member.kind == "agent":
            lines.append(f"{role}\tagent\t{member.agent_key}\t{member.agent_name}")
        else:
            lines.append(f"{role}\tllm\t{member.provider}/{member.model_id}")
    return "\n".join(lines)
