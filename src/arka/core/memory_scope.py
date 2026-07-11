#!/usr/bin/env python3
"""Scoped memory with provenance and trust tiers for teams and workflows."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

TrustTier = Literal["global", "team", "workflow", "run"]

TIER_ORDER: dict[str, int] = {
    "global": 0,
    "team": 1,
    "workflow": 2,
    "run": 3,
}

DEFAULT_READ_TIERS: list[TrustTier] = ["global", "team", "workflow"]
MAX_SCRATCHPAD_LINES = 2000


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def scratchpad_path() -> Path:
    return _config_dir() / "memory-scratchpad" / "index.jsonl"


def trust_max_tier() -> TrustTier:
    raw = (os.environ.get("ARKA_MEMORY_TRUST_MAX") or "run").strip().lower()
    if raw in TIER_ORDER:
        return raw  # type: ignore[return-value]
    return "run"


def tier_allowed(tier: TrustTier, *, policy: MemoryPolicy) -> bool:
    """Return True if tier is within the env trust cap and policy read list."""
    cap = trust_max_tier()
    if TIER_ORDER.get(tier, 99) > TIER_ORDER.get(cap, 3):
        return False
    return tier in policy.read_tiers


def hub_memory_scope() -> tuple[str, str] | None:
    """Parse ARKA_HUB_MEMORY_SCOPE like team:clawbox."""
    raw = (os.environ.get("ARKA_HUB_MEMORY_SCOPE") or "").strip()
    if not raw or ":" not in raw:
        return None
    kind, _, name = raw.partition(":")
    kind = kind.strip().lower()
    name = name.strip()
    if kind == "team" and name:
        return kind, name
    return None


def default_ttl_hours() -> int:
    try:
        return max(1, int(os.environ.get("MEMORY_SCRATCHPAD_TTL_HOURS", "72")))
    except ValueError:
        return 72


@dataclass
class Provenance:
    team: str = ""
    workflow: str = ""
    step: str = ""
    role: str = ""
    member_id: str = ""
    run_id: str = ""
    mcp_servers: list[str] = field(default_factory=list)
    source: str = "workflow"
    trust_tier: TrustTier = "workflow"
    when: str = ""

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        if not row.get("when"):
            row["when"] = _iso_now()
        return row

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Provenance:
        if not isinstance(data, dict):
            return cls()
        mcp = data.get("mcp_servers") or []
        tier = str(data.get("trust_tier") or "workflow").strip().lower()
        if tier not in TIER_ORDER:
            tier = "workflow"
        return cls(
            team=str(data.get("team") or ""),
            workflow=str(data.get("workflow") or ""),
            step=str(data.get("step") or ""),
            role=str(data.get("role") or ""),
            member_id=str(data.get("member_id") or ""),
            run_id=str(data.get("run_id") or ""),
            mcp_servers=[str(s) for s in mcp if str(s).strip()],
            source=str(data.get("source") or "workflow"),
            trust_tier=tier,  # type: ignore[arg-type]
            when=str(data.get("when") or ""),
        )


@dataclass
class MemoryPolicy:
    read_tiers: list[TrustTier] = field(default_factory=lambda: list(DEFAULT_READ_TIERS))
    write_tier: TrustTier = "workflow"
    ttl_hours: int = 72
    read_roles: list[str] | None = None
    include_channel: bool = False
    promote: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return {
            "read": list(self.read_tiers),
            "write": self.write_tier,
            "ttl_hours": self.ttl_hours,
            "read_roles": list(self.read_roles) if self.read_roles else None,
            "include_channel": self.include_channel,
            "promote": self.promote,
        }


@dataclass
class RecallScope:
    team: str
    workflow: str = ""
    run_id: str = ""
    policy: MemoryPolicy = field(default_factory=MemoryPolicy)


def parse_trust_tier(raw: Any, *, default: TrustTier = "workflow") -> TrustTier:
    text = str(raw or default).strip().lower()
    if text in TIER_ORDER:
        return text  # type: ignore[return-value]
    return default


def parse_memory_policy(raw: Any, *, default_ttl: int | None = None) -> MemoryPolicy:
    if not isinstance(raw, dict):
        return MemoryPolicy(ttl_hours=default_ttl or default_ttl_hours())
    read_raw = raw.get("read", DEFAULT_READ_TIERS)
    read_tiers: list[TrustTier] = []
    if isinstance(read_raw, list):
        for item in read_raw:
            tier = parse_trust_tier(item, default="global")
            if tier not in read_tiers:
                read_tiers.append(tier)
    if not read_tiers:
        read_tiers = list(DEFAULT_READ_TIERS)
    roles_raw = raw.get("read_roles")
    read_roles: list[str] | None = None
    if isinstance(roles_raw, list):
        read_roles = [str(r).strip() for r in roles_raw if str(r).strip()]
    ttl = raw.get("ttl_hours", default_ttl or default_ttl_hours())
    try:
        ttl_int = max(1, int(ttl))
    except (TypeError, ValueError):
        ttl_int = default_ttl_hours()
    promote = str(raw.get("promote") or "manual").strip().lower()
    if promote not in ("manual", "never"):
        promote = "manual"
    return MemoryPolicy(
        read_tiers=read_tiers,
        write_tier=parse_trust_tier(raw.get("write"), default="workflow"),
        ttl_hours=ttl_int,
        read_roles=read_roles,
        include_channel=bool(raw.get("include_channel")),
        promote=promote,
    )


def resolve_memory_policy(
    team_defaults: dict[str, Any] | None = None,
    workflow_defaults: dict[str, Any] | None = None,
    step_scope: dict[str, Any] | None = None,
) -> MemoryPolicy:
    team_defaults = team_defaults or {}
    workflow_defaults = workflow_defaults or {}
    base = parse_memory_policy(team_defaults.get("memory_scope"))
    wf = parse_memory_policy(workflow_defaults.get("memory_scope"))
    policy = MemoryPolicy(
        read_tiers=wf.read_tiers or base.read_tiers,
        write_tier=wf.write_tier or base.write_tier,
        ttl_hours=wf.ttl_hours or base.ttl_hours,
        read_roles=wf.read_roles if wf.read_roles is not None else base.read_roles,
        include_channel=wf.include_channel if wf.include_channel else base.include_channel,
        promote=wf.promote or base.promote,
    )
    if step_scope:
        step = parse_memory_policy(step_scope)
        if step.write_tier:
            policy.write_tier = step.write_tier
        if step.ttl_hours:
            policy.ttl_hours = step.ttl_hours
    return policy


def entry_matches_scope(
    provenance: Provenance,
    *,
    scope: RecallScope,
    policy: MemoryPolicy,
) -> bool:
    tier = provenance.trust_tier or "global"
    if not tier_allowed(tier, policy=policy):
        return False
    if tier == "global":
        return True
    if tier == "team":
        if scope.team and provenance.team and provenance.team != scope.team:
            return False
        hub = hub_memory_scope()
        if hub and hub[0] == "team" and provenance.team and provenance.team != hub[1]:
            return False
        return True
    if tier == "workflow":
        if scope.team and provenance.team and provenance.team != scope.team:
            return False
        if scope.workflow and provenance.workflow and provenance.workflow != scope.workflow:
            return False
        return True
    if tier == "run":
        if scope.run_id and provenance.run_id and provenance.run_id != scope.run_id:
            return False
        if scope.team and provenance.team and provenance.team != scope.team:
            return False
        if scope.workflow and provenance.workflow and provenance.workflow != scope.workflow:
            return False
        return True
    return False


def fact_trust_tier(row: dict[str, Any]) -> TrustTier:
    tier = str(row.get("trust_tier") or "").strip().lower()
    if tier in TIER_ORDER:
        return tier  # type: ignore[return-value]
    prov = row.get("provenance")
    if isinstance(prov, dict):
        tier = str(prov.get("trust_tier") or "").strip().lower()
        if tier in TIER_ORDER:
            return tier  # type: ignore[return-value]
    return "global"


def fact_provenance(row: dict[str, Any]) -> Provenance:
    prov = row.get("provenance")
    if isinstance(prov, dict):
        return Provenance.from_dict(prov)
    return Provenance(
        source=str(row.get("source") or "cli"),
        trust_tier=fact_trust_tier(row),
    )


def _read_scratchpad_lines() -> list[dict[str, Any]]:
    path = scratchpad_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows


def _write_scratchpad_lines(rows: list[dict[str, Any]]) -> None:
    path = scratchpad_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = rows[-MAX_SCRATCHPAD_LINES:]
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in trimmed)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _entry_expired(row: dict[str, Any]) -> bool:
    expires = row.get("expires_at")
    if not expires:
        return False
    try:
        exp = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp
    except (TypeError, ValueError):
        return False


def write_scratchpad(
    text: str,
    *,
    provenance: Provenance,
    ttl_hours: int | None = None,
) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""
    entry_id = hashlib.sha256(f"{text}{time.time()}{uuid.uuid4()}".encode()).hexdigest()[:12]
    hours = ttl_hours if ttl_hours is not None else default_ttl_hours()
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    if not provenance.when:
        provenance.when = _iso_now()
    row = {
        "id": entry_id,
        "text": text[:8000],
        "provenance": provenance.to_dict(),
        "trust_tier": provenance.trust_tier,
        "expires_at": expires.replace(microsecond=0).isoformat(),
    }
    rows = _read_scratchpad_lines()
    rows = [r for r in rows if not _entry_expired(r)]
    rows.append(row)
    _write_scratchpad_lines(rows)
    return entry_id


def list_scratchpad(
    *,
    team: str = "",
    workflow: str = "",
    run_id: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = [r for r in _read_scratchpad_lines() if not _entry_expired(r)]
    if team:
        rows = [
            r
            for r in rows
            if str((r.get("provenance") or {}).get("team") or "") == team
        ]
    if workflow:
        rows = [
            r
            for r in rows
            if str((r.get("provenance") or {}).get("workflow") or "") == workflow
        ]
    if run_id:
        rows = [
            r
            for r in rows
            if str((r.get("provenance") or {}).get("run_id") or "") == run_id
        ]
    return rows[-limit:]


def get_scratchpad(entry_id: str) -> dict[str, Any] | None:
    for row in _read_scratchpad_lines():
        if str(row.get("id") or "") == entry_id and not _entry_expired(row):
            return row
    return None


def recall_scratchpad(
    goal: str,
    *,
    scope: RecallScope,
    limit_chars: int = 1200,
) -> str:
    goal = goal.lower()
    scored: list[tuple[float, str]] = []
    for row in list_scratchpad():
        prov = Provenance.from_dict(row.get("provenance") if isinstance(row.get("provenance"), dict) else {})
        if not entry_matches_scope(prov, scope=scope, policy=scope.policy):
            continue
        if scope.policy.read_roles and prov.role and prov.role not in scope.policy.read_roles:
            continue
        text = str(row.get("text") or "")
        score = sum(1 for w in goal.split() if len(w) > 2 and w in text.lower())
        if score or not goal:
            scored.append((score or 0.1, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return ""
    lines = [f"- {t}" for _, t in scored[:8]]
    out = "Workflow scratchpad:\n" + "\n".join(lines)
    if len(out) > limit_chars:
        out = out[-limit_chars:]
    return out


def filter_fact_rows(
    rows: list[dict[str, Any]],
    *,
    scope: RecallScope,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        prov = fact_provenance(row)
        tier = fact_trust_tier(row)
        prov.trust_tier = tier
        if tier == "global":
            kept.append(row)
            continue
        if entry_matches_scope(prov, scope=scope, policy=scope.policy):
            if scope.policy.read_roles and prov.role and prov.role not in scope.policy.read_roles:
                continue
            kept.append(row)
    return kept


def promote_to_facts(entry_id: str) -> tuple[bool, str | None]:
    row = get_scratchpad(entry_id)
    if not row:
        return False, "scratchpad entry not found"
    text = str(row.get("text") or "").strip()
    if not text:
        return False, "empty entry"
    prov = Provenance.from_dict(row.get("provenance") if isinstance(row.get("provenance"), dict) else {})
    prov.trust_tier = "global"
    prov.source = "promoted"
    try:
        from arka.agent.core import memory_remember_silent

        ok = memory_remember_silent(
            text,
            source="promoted",
            provenance=prov.to_dict(),
            trust_tier="global",
        )
        if ok:
            return True, None
    except ImportError:
        pass
    return False, "memory store unavailable"


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def scope_status(scope: RecallScope | None = None) -> dict[str, Any]:
    rows = [r for r in _read_scratchpad_lines() if not _entry_expired(r)]
    hub = hub_memory_scope()
    info: dict[str, Any] = {
        "trust_max": trust_max_tier(),
        "hub_scope": f"{hub[0]}:{hub[1]}" if hub else None,
        "scratchpad_count": len(rows),
        "scratchpad_path": str(scratchpad_path()),
        "default_ttl_hours": default_ttl_hours(),
    }
    if scope:
        info["policy"] = scope.policy.to_dict()
        info["team"] = scope.team
        info["workflow"] = scope.workflow
        info["run_id"] = scope.run_id
    return info


def print_scope_status(scope: RecallScope | None = None) -> None:
    info = scope_status(scope)
    print(f"Trust cap: {info.get('trust_max')}")
    if info.get("hub_scope"):
        print(f"Hub scope filter: {info.get('hub_scope')}")
    print(f"Scratchpad: {info.get('scratchpad_count')} entries at {info.get('scratchpad_path')}")
    print(f"Default TTL: {info.get('default_ttl_hours')}h")
    if scope:
        print(f"Team: {scope.team or '(none)'}")
        print(f"Workflow: {scope.workflow or '(none)'}")
        print(f"Run: {scope.run_id or '(none)'}")
        print(f"Policy read tiers: {', '.join(scope.policy.read_tiers)}")
        print(f"Policy write tier: {scope.policy.write_tier}")
