"""Health checks for agent teams and scoped memory."""

from __future__ import annotations

import os
from typing import Any

from arka.teams.io import (
    _config_path,
    list_teams,
    list_workflows,
    load_team,
    load_workflow,
    teams_dir,
    workflows_dir,
)
from arka.teams.resolve import resolve_team


def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def _scratchpad_writable() -> dict[str, Any]:
    try:
        from arka.core.memory_scope import scratchpad_path
    except ImportError:
        return _check("scratchpad_writable", False, "memory_scope unavailable")

    path = scratchpad_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return _check("scratchpad_writable", True, str(path.parent))
    except OSError as exc:
        return _check("scratchpad_writable", False, f"{path.parent}: {exc}")


def _trust_env_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        from arka.core.memory_scope import TIER_ORDER, trust_max_tier
    except ImportError:
        return [_check("trust_max", False, "memory_scope unavailable")]

    raw_trust = (os.environ.get("ARKA_MEMORY_TRUST_MAX") or "").strip()
    tier = trust_max_tier()
    if raw_trust and raw_trust.lower() not in TIER_ORDER:
        checks.append(
            _check(
                "trust_max",
                False,
                f"invalid ARKA_MEMORY_TRUST_MAX={raw_trust!r} (use global|team|workflow|run)",
            )
        )
    else:
        source = "default" if not raw_trust else "env"
        checks.append(_check("trust_max", True, f"{tier} ({source})"))

    raw_scope = (os.environ.get("ARKA_HUB_MEMORY_SCOPE") or "").strip()
    if not raw_scope:
        checks.append(_check("hub_memory_scope", True, "unset (no hub filter)"))
    elif ":" not in raw_scope:
        checks.append(
            _check(
                "hub_memory_scope",
                False,
                f"invalid ARKA_HUB_MEMORY_SCOPE={raw_scope!r} (expected team:<name>)",
            )
        )
    else:
        kind, _, name = raw_scope.partition(":")
        if kind.strip().lower() == "team" and name.strip():
            checks.append(_check("hub_memory_scope", True, raw_scope))
        else:
            checks.append(
                _check(
                    "hub_memory_scope",
                    False,
                    f"invalid ARKA_HUB_MEMORY_SCOPE={raw_scope!r} (expected team:<name>)",
                )
            )
    return checks


def _layout_checks() -> list[dict[str, Any]]:
    tdir = teams_dir()
    wdir = workflows_dir()
    checks = [
        _check("teams_dir", tdir.is_dir(), str(tdir)),
        _check("workflows_dir", wdir.is_dir(), str(wdir)),
        _scratchpad_writable(),
        *_trust_env_checks(),
    ]
    return checks


def _team_checks(name: str) -> list[dict[str, Any]]:
    prefix = f"team_{name}"
    path = _config_path(teams_dir(), name)
    if not path:
        return [_check(f"{prefix}_config", False, f"team not found: {name}")]

    checks = [_check(f"{prefix}_config", True, str(path))]

    try:
        team = load_team(name)
    except (FileNotFoundError, ValueError) as exc:
        checks.append(_check(f"{prefix}_parse", False, str(exc)))
        return checks

    try:
        resolved = resolve_team(team)
        roles = ", ".join(sorted(resolved))
        checks.append(_check(f"{prefix}_members", True, roles))
    except ValueError as exc:
        checks.append(_check(f"{prefix}_members", False, str(exc)))

    default_wf = str((team.defaults or {}).get("workflow") or "").strip()
    if default_wf:
        wf_path = _config_path(workflows_dir(), default_wf)
        if wf_path:
            checks.append(_check(f"{prefix}_workflow", True, str(wf_path)))
        else:
            checks.append(
                _check(f"{prefix}_workflow", False, f"workflow not found: {default_wf}")
            )
        if wf_path:
            try:
                wf = load_workflow(default_wf)
                if wf.team != team.name:
                    checks.append(
                        _check(
                            f"{prefix}_workflow_team",
                            False,
                            f"workflow {default_wf!r} targets team {wf.team!r}, not {team.name!r}",
                        )
                    )
                else:
                    checks.append(
                        _check(
                            f"{prefix}_workflow_team",
                            True,
                            f"{default_wf} -> {team.name}",
                        )
                    )
            except ValueError as exc:
                checks.append(_check(f"{prefix}_workflow_parse", False, str(exc)))

    return checks


def doctor(team_name: str | None = None) -> list[dict[str, Any]]:
    """Run team health checks. If team_name is set, only check that team."""
    checks = _layout_checks()
    names = [team_name] if team_name else list_teams()
    if not names:
        checks.append(_check("teams_present", False, "no teams — run: arka team create research"))
    else:
        checks.append(_check("teams_present", True, f"{len(names)} team(s)"))
        for name in names:
            checks.extend(_team_checks(name))
    if not team_name:
        wf_names = list_workflows()
        checks.append(
            _check(
                "workflows_present",
                bool(wf_names),
                f"{len(wf_names)} workflow(s)" if wf_names else "no workflows",
            )
        )
    return checks


def format_doctor(team_name: str | None = None) -> tuple[str, int]:
    checks = doctor(team_name)
    lines: list[str] = []
    ok_count = 0
    for row in checks:
        status = "ok" if row.get("ok") else "fail"
        if row.get("ok"):
            ok_count += 1
        lines.append(f"{row.get('name')}\t{status}\t{row.get('detail', '')}")
    lines.append(f"summary\t{ok_count}/{len(checks)} checks passed")
    return "\n".join(lines), 0 if ok_count == len(checks) else 1
