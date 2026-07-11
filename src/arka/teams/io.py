"""Load, save, and seed team/workflow configs."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from arka.teams.schema import Team, Workflow, parse_team, parse_workflow


def _env_dir(primary: str, legacy: str, default_name: str) -> Path:
    for key in (primary, legacy):
        if raw := os.environ.get(key, "").strip():
            return Path(raw).expanduser().resolve()
    from arka.paths import config_dir

    return config_dir() / default_name


def teams_dir() -> Path:
    return _env_dir("ARKA_TEAMS_DIR", "TEAMS_DIR", "teams")


def workflows_dir() -> Path:
    return _env_dir("ARKA_WORKFLOWS_DIR", "WORKFLOWS_DIR", "workflows")


def templates_dir() -> Path:
    from arka.paths import package_dir

    return package_dir() / "teams" / "templates"


def _load_text(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception as exc:
            raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be an object: {path}")
    return data


def _dump_text(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml

            text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
        except ImportError:
            path = path.with_suffix(".json")
            text = json.dumps(data, indent=2)
            text += "\n"
    else:
        text = json.dumps(data, indent=2)
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _config_path(directory: Path, name: str) -> Path | None:
    stem = name.strip()
    if not stem:
        return None
    for ext in (".yaml", ".yml", ".json"):
        candidate = directory / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def list_config_names(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    names: set[str] = set()
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".json"}:
            names.add(path.stem)
    return sorted(names)


def list_teams() -> list[str]:
    ensure_layout()
    return list_config_names(teams_dir())


def list_workflows() -> list[str]:
    ensure_layout()
    return list_config_names(workflows_dir())


def load_team(name: str) -> Team:
    ensure_layout()
    path = _config_path(teams_dir(), name)
    if not path:
        raise FileNotFoundError(f"Team not found: {name}")
    return parse_team(_load_text(path), source=str(path))


def load_workflow(name: str) -> Workflow:
    ensure_layout()
    path = _config_path(workflows_dir(), name)
    if not path:
        raise FileNotFoundError(f"Workflow not found: {name}")
    return parse_workflow(_load_text(path), source=str(path))


def save_team(team: Team, *, fmt: str = "yaml") -> Path:
    directory = teams_dir()
    directory.mkdir(parents=True, exist_ok=True)
    ext = ".json" if fmt == "json" else ".yaml"
    path = directory / f"{team.name}{ext}"
    _dump_text(team.to_dict(), path)
    return path


def save_workflow(workflow: Workflow, *, fmt: str = "yaml") -> Path:
    directory = workflows_dir()
    directory.mkdir(parents=True, exist_ok=True)
    ext = ".json" if fmt == "json" else ".yaml"
    path = directory / f"{workflow.name}{ext}"
    _dump_text(workflow.to_dict(), path)
    return path


def ensure_layout() -> tuple[Path, Path]:
    tdir = teams_dir()
    wdir = workflows_dir()
    tdir.mkdir(parents=True, exist_ok=True)
    wdir.mkdir(parents=True, exist_ok=True)
    src = templates_dir()
    if src.is_dir():
        for path in src.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                continue
            if path.name.startswith("team-"):
                dest = tdir / path.name.removeprefix("team-")
            elif path.name.startswith("workflow-"):
                dest = wdir / path.name.removeprefix("workflow-")
            else:
                continue
            if not dest.is_file():
                shutil.copy2(path, dest)
    return tdir, wdir


def format_team_list() -> str:
    names = list_teams()
    if not names:
        return "teams\t(none — run: arka team create research)"
    lines = ["teams"]
    for name in names:
        try:
            team = load_team(name)
            desc = team.description or ""
            roles = ", ".join(sorted({m.role for m in team.members}))
            lines.append(f"{name}\t{desc}\troles={roles}")
        except (ValueError, FileNotFoundError) as exc:
            lines.append(f"{name}\tinvalid\t{exc}")
    return "\n".join(lines)


def format_workflow_list() -> str:
    names = list_workflows()
    if not names:
        return "workflows\t(none — run: arka workflow create review-and-ship)"
    lines = ["workflows"]
    for name in names:
        try:
            wf = load_workflow(name)
            lines.append(f"{name}\tteam={wf.team}\tsteps={len(wf.steps)}")
        except (ValueError, FileNotFoundError) as exc:
            lines.append(f"{name}\tinvalid\t{exc}")
    return "\n".join(lines)


def format_team_show(name: str) -> str:
    team = load_team(name)
    lines = [
        f"name\t{team.name}",
        f"description\t{team.description}",
        f"source\t{team.source}",
    ]
    if team.defaults:
        lines.append(f"defaults\t{json.dumps(team.defaults)}")
    for member in team.members:
        parts = [member.kind, member.id, f"role={member.role}"]
        if member.provider:
            parts.append(f"provider={member.provider}")
        lines.append("member\t" + "\t".join(parts))
    return "\n".join(lines)


def format_workflow_show(name: str) -> str:
    wf = load_workflow(name)
    lines = [
        f"name\t{wf.name}",
        f"team\t{wf.team}",
        f"source\t{wf.source}",
        f"steps\t{len(wf.steps)}",
    ]
    for idx, step in enumerate(wf.steps, start=1):
        if step.parallel:
            lines.append(f"step_{idx}\tparallel\tcount={len(step.parallel)}")
            for sub_idx, sub in enumerate(step.parallel, start=1):
                lines.append(
                    f"  step_{idx}.{sub_idx}\t{sub.member}\t{sub.action}\t{sub.prompt[:80]}"
                )
        else:
            lines.append(f"step_{idx}\t{step.member}\t{step.action}\t{step.prompt[:80]}")
    return "\n".join(lines)
