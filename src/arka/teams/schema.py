"""Team and workflow schema validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MemberKind = Literal["agent", "model", "provider"]


@dataclass
class TeamMember:
    kind: MemberKind
    id: str
    role: str
    provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"kind": self.kind, "id": self.id, "role": self.role}
        if self.provider:
            row["provider"] = self.provider
        return row


@dataclass
class Team:
    name: str
    description: str = ""
    members: list[TeamMember] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "members": [m.to_dict() for m in self.members],
        }
        if self.defaults:
            data["defaults"] = self.defaults
        return data


@dataclass
class WorkflowStep:
    member: str = ""
    action: str = ""
    prompt: str = ""
    parallel: list[WorkflowStep] | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.parallel:
            return {"parallel": [s.to_dict() for s in self.parallel]}
        row: dict[str, Any] = {"member": self.member, "action": self.action}
        if self.prompt:
            row["prompt"] = self.prompt
        return row


@dataclass
class Workflow:
    name: str
    team: str
    steps: list[WorkflowStep] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "team": self.team,
            "steps": [s.to_dict() for s in self.steps],
        }


def _require_str(data: dict[str, Any], key: str, *, default: str = "") -> str:
    val = data.get(key, default)
    if not isinstance(val, str):
        raise ValueError(f"{key} must be a string")
    val = val.strip()
    if not val and not default:
        raise ValueError(f"{key} is required")
    return val or default


def _parse_member(raw: Any) -> TeamMember:
    if not isinstance(raw, dict):
        raise ValueError("member must be an object")
    kind = _require_str(raw, "kind").lower()
    if kind not in {"agent", "model", "provider"}:
        raise ValueError(f"unknown member kind: {kind}")
    member_id = _require_str(raw, "id")
    role = _require_str(raw, "role")
    provider = str(raw.get("provider") or "").strip()
    if kind == "model" and not provider:
        raise ValueError(f"model member {member_id!r} requires provider")
    return TeamMember(kind=kind, id=member_id, role=role, provider=provider)


def parse_team(data: dict[str, Any], *, source: str = "") -> Team:
    name = _require_str(data, "name")
    description = _require_str(data, "description", default="")
    members_raw = data.get("members")
    if not isinstance(members_raw, list) or not members_raw:
        raise ValueError("members must be a non-empty list")
    members = [_parse_member(row) for row in members_raw]
    roles = [m.role for m in members]
    if len(roles) != len(set(roles)):
        raise ValueError("duplicate member roles are not allowed")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be an object")
    return Team(
        name=name,
        description=description,
        members=members,
        defaults=defaults,
        source=source,
    )


def _parse_step(raw: Any) -> WorkflowStep:
    if not isinstance(raw, dict):
        raise ValueError("workflow step must be an object")
    if "parallel" in raw:
        parallel_raw = raw.get("parallel")
        if not isinstance(parallel_raw, list) or not parallel_raw:
            raise ValueError("parallel must be a non-empty list")
        return WorkflowStep(parallel=[_parse_step(row) for row in parallel_raw])
    member = _require_str(raw, "member")
    action = _require_str(raw, "action")
    prompt = _require_str(raw, "prompt", default="")
    return WorkflowStep(member=member, action=action, prompt=prompt)


def parse_workflow(data: dict[str, Any], *, source: str = "") -> Workflow:
    name = _require_str(data, "name")
    team = _require_str(data, "team")
    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError("steps must be a non-empty list")
    steps = [_parse_step(row) for row in steps_raw]
    return Workflow(name=name, team=team, steps=steps, source=source)
