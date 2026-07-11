"""Team and workflow schema validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MemberKind = Literal["agent", "model", "provider"]
WorkflowMode = Literal["sequential", "round_robin"]


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
    retries: int | None = None
    retry_delay: float | None = None
    mcp: bool | None = None
    mcp_servers: list[str] | None = None
    memory_scope: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.parallel:
            return {"parallel": [s.to_dict() for s in self.parallel]}
        row: dict[str, Any] = {"member": self.member, "action": self.action}
        if self.prompt:
            row["prompt"] = self.prompt
        if self.retries is not None:
            row["retries"] = self.retries
        if self.retry_delay is not None:
            row["retry_delay"] = self.retry_delay
        if self.mcp is not None:
            row["mcp"] = self.mcp
        if self.mcp_servers:
            row["mcp_servers"] = list(self.mcp_servers)
        if self.memory_scope:
            row["memory_scope"] = dict(self.memory_scope)
        return row


@dataclass
class Workflow:
    name: str
    team: str
    steps: list[WorkflowStep] = field(default_factory=list)
    mode: WorkflowMode = "sequential"
    max_turns: int = 6
    prompt: str = ""
    members: list[str] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "team": self.team,
        }
        if self.mode != "sequential":
            data["mode"] = self.mode
        if self.mode == "round_robin":
            data["max_turns"] = self.max_turns
            if self.prompt:
                data["prompt"] = self.prompt
            if self.members:
                data["members"] = list(self.members)
        if self.steps:
            data["steps"] = [s.to_dict() for s in self.steps]
        if self.defaults:
            data["defaults"] = self.defaults
        return data


def _require_str(data: dict[str, Any], key: str, *, default: str = "") -> str:
    val = data.get(key, default)
    if not isinstance(val, str):
        raise ValueError(f"{key} must be a string")
    val = val.strip()
    if not val and not default:
        raise ValueError(f"{key} is required")
    return val or default


def _optional_int(raw: Any, *, field: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _optional_float(raw: Any, *, field: str) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be a number")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc


def _optional_bool(raw: Any, *, field: str) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{field} must be a boolean")


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
    retries = _optional_int(raw.get("retries"), field="retries")
    retry_delay = _optional_float(raw.get("retry_delay"), field="retry_delay")
    mcp = _optional_bool(raw.get("mcp"), field="mcp")
    mcp_servers_raw = raw.get("mcp_servers")
    mcp_servers: list[str] | None = None
    if mcp_servers_raw is not None:
        if not isinstance(mcp_servers_raw, list):
            raise ValueError("mcp_servers must be a list")
        mcp_servers = [str(s).strip() for s in mcp_servers_raw if str(s).strip()]
    memory_scope_raw = raw.get("memory_scope")
    memory_scope: dict[str, Any] | None = None
    if memory_scope_raw is not None:
        if not isinstance(memory_scope_raw, dict):
            raise ValueError("memory_scope must be an object")
        memory_scope = dict(memory_scope_raw)
    return WorkflowStep(
        member=member,
        action=action,
        prompt=prompt,
        retries=retries,
        retry_delay=retry_delay,
        mcp=mcp,
        mcp_servers=mcp_servers,
        memory_scope=memory_scope,
    )


def parse_workflow(data: dict[str, Any], *, source: str = "") -> Workflow:
    name = _require_str(data, "name")
    team = _require_str(data, "team")
    mode_raw = str(data.get("mode") or "sequential").strip().lower()
    if mode_raw not in {"sequential", "round_robin"}:
        raise ValueError(f"unknown workflow mode: {mode_raw}")
    mode: WorkflowMode = mode_raw  # type: ignore[assignment]

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be an object")

    max_turns = _optional_int(data.get("max_turns"), field="max_turns") or 6
    if max_turns < 1:
        raise ValueError("max_turns must be >= 1")

    prompt_raw = data.get("prompt", "")
    if prompt_raw is None:
        prompt = ""
    elif not isinstance(prompt_raw, str):
        raise ValueError("prompt must be a string")
    else:
        prompt = prompt_raw.strip()
    members_raw = data.get("members") or []
    if not isinstance(members_raw, list):
        raise ValueError("members must be a list")
    members = [str(m).strip() for m in members_raw if str(m).strip()]

    steps_raw = data.get("steps")
    steps: list[WorkflowStep] = []
    if steps_raw is not None:
        if not isinstance(steps_raw, list):
            raise ValueError("steps must be a list")
        steps = [_parse_step(row) for row in steps_raw]

    if mode == "sequential":
        if not steps:
            raise ValueError("steps must be a non-empty list")
    elif mode == "round_robin":
        if not prompt:
            raise ValueError("round_robin workflows require prompt")

    return Workflow(
        name=name,
        team=team,
        steps=steps,
        mode=mode,
        max_turns=max_turns,
        prompt=prompt,
        members=members,
        defaults=defaults,
        source=source,
    )
