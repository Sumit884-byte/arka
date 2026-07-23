"""Safely project Arka environment values into another project's .env."""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_ALIASES = {
    "linkedin_email": "LINKEDIN_USERNAME",
    "LINKEDIN_EMAIL": "LINKEDIN_USERNAME",
    "linkedin_password": "LINKEDIN_PASSWORD",
    "LINKEDIN_PASS": "LINKEDIN_PASSWORD",
}

_ENV_SUFFIXES = ("_API_KEY", "_TOKEN", "_URL", "_BASE", "_MODEL", "_SECRET", "_PASSWORD")
_LINKEDIN_PREFIX = ("linkedin_", "google_", "github_", "openai_", "gemini_", "groq_", "ollama_")


@dataclass
class EnvBridgePlan:
    target: Path
    source: Path | None
    required: list[str] = field(default_factory=list)
    existing: dict[str, str] = field(default_factory=dict)
    from_arka: dict[str, str] = field(default_factory=dict)
    arka_map: dict[str, str] = field(default_factory=dict)
    from_constants: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    additions: dict[str, str] = field(default_factory=dict)
    updates: dict[str, str] = field(default_factory=dict)

    @property
    def resolved(self) -> dict[str, str]:
        out = dict(self.from_constants)
        out.update(self.from_arka)
        return out


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value != "your-secret-here":
            out[key] = value
    return out


def _arka_env_file(explicit: Path | None) -> Path | None:
    if explicit and explicit.is_file():
        return explicit
    try:
        from arka.paths import checkout_root, env_file

        path = env_file()
        if path.is_file():
            return path
        root = checkout_root()
        if root and (root / ".env").is_file():
            return root / ".env"
    except ImportError:
        pass
    return None


def _raw_arka_env(*, source_file: Path | None = None) -> dict[str, str]:
    values = {
        k: v
        for k, v in os.environ.items()
        if any(k.endswith(suffix) for suffix in _ENV_SUFFIXES) and v and v.strip() != "your-secret-here"
    }
    path = _arka_env_file(source_file)
    if path:
        for key, value in _parse_env_file(path).items():
            if any(key.endswith(suffix) for suffix in _ENV_SUFFIXES) or key.lower().startswith(_LINKEDIN_PREFIX):
                values.setdefault(key, value)
            elif key.lower() in _DEFAULT_ALIASES or key in _DEFAULT_ALIASES:
                values[key] = value
    return values


def _apply_aliases(values: dict[str, str], aliases: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (target_key -> value, target_key -> source_key)."""
    out = dict(values)
    mapping: dict[str, str] = {}
    for src, dst in aliases.items():
        if src in values and values[src]:
            out[dst] = values[src]
            mapping[dst] = src
    return out, mapping


def _project_keys(project: Path) -> list[str]:
    try:
        from arka.agent.env_setup import required_env

        return required_env(project)
    except ImportError:
        return []


def _project_constants(project: Path) -> dict[str, str]:
    try:
        from arka.agent.env_setup import scan_source_constants

        return scan_source_constants(project)
    except ImportError:
        return {}


def _reverse_aliases(aliases: dict[str, str]) -> dict[str, str]:
    return {dst: src for src, dst in aliases.items()}


def plan_env_bridge(
    project: Path,
    *,
    source_file: Path | None = None,
    allowed: set[str] | None = None,
    aliases: dict[str, str] | None = None,
    project_keys_only: bool = True,
    update_existing: bool = False,
) -> EnvBridgePlan:
    target = project / ".env"
    alias_map = dict(_DEFAULT_ALIASES)
    if aliases:
        alias_map.update(aliases)

    required = _project_keys(project)
    if allowed:
        required = [key for key in required if key in allowed]
    if not required and not project_keys_only:
        required = sorted(_raw_arka_env(source_file=source_file).keys())

    arka_raw = _raw_arka_env(source_file=source_file)
    arka_values, arka_map = _apply_aliases(arka_raw, alias_map)
    constants = _project_constants(project)
    existing = _parse_env_file(target) if target.is_file() else {}

    from_arka: dict[str, str] = {}
    from_constants: dict[str, str] = {}
    missing: list[str] = []
    additions: dict[str, str] = {}
    updates: dict[str, str] = {}

    for key in required:
        value = ""
        if key in arka_values and arka_values[key]:
            value = arka_values[key]
            from_arka[key] = value
        elif key in constants and constants[key]:
            value = constants[key]
            from_constants[key] = value
        elif key in arka_raw and arka_raw[key]:
            value = arka_raw[key]
            from_arka[key] = value

        if not value:
            if not existing.get(key):
                missing.append(key)
            continue

        if key not in existing:
            additions[key] = value
        elif update_existing and existing.get(key) != value:
            updates[key] = value

    return EnvBridgePlan(
        target=target,
        source=_arka_env_file(source_file),
        required=required,
        existing=existing,
        from_arka=from_arka,
        arka_map={k: arka_map.get(k, _reverse_aliases(alias_map).get(k, k)) for k in from_arka},
        from_constants=from_constants,
        missing=missing,
        additions=additions,
        updates=updates,
    )


def apply_env_bridge(plan: EnvBridgePlan) -> int:
    changes = {**plan.additions, **plan.updates}
    if not changes:
        return 0
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    if plan.target.is_file():
        raw = plan.target.read_text(encoding="utf-8", errors="replace")
        lines: list[str] = []
        for line in raw.splitlines():
            key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
            if key in changes:
                lines.append(f"{key}={changes[key]}")
            else:
                lines.append(line)
        present = {line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.lstrip().startswith("#")}
        for key, value in sorted(plan.additions.items()):
            if key not in present:
                lines.append(f"{key}={value}")
        text = "\n".join(lines).rstrip() + "\n"
    else:
        text = "# Bridged by Arka: required keys discovered, then filled from Arka .env / project constants.\n"
        text += "\n".join(f"{k}={v}" for k, v in sorted(changes.items())) + "\n"
    plan.target.write_text(text, encoding="utf-8")
    return len(changes)


def print_env_bridge_plan(plan: EnvBridgePlan) -> None:
    print(f"target\t{plan.target}")
    print(f"source\t{plan.source or 'process environment'}")
    print(f"required\t{len(plan.required)}")
    for key in plan.required:
        print(f"required_key\t{key}")
    for key in sorted(plan.from_arka):
        src = plan.arka_map.get(key, key)
        print(f"from_arka\t{key}\t{src}\t[redacted]")
    for key in sorted(plan.from_constants):
        print(f"from_constants\t{key}\t[redacted]")
    for key in plan.missing:
        print(f"missing\t{key}")
    print(f"additions\t{len(plan.additions)}")
    for key in sorted(plan.additions):
        print(f"candidate\t{key}\t[redacted]")
    print(f"updates\t{len(plan.updates)}")
    for key in sorted(plan.updates):
        print(f"update\t{key}\t[redacted]")


def bridge_env(
    project: Path,
    *,
    source_file: Path | None = None,
    allowed: set[str] | None = None,
    aliases: dict[str, str] | None = None,
    project_keys_only: bool = True,
    update_existing: bool = False,
    apply: bool = False,
) -> tuple[Path, dict[str, str], dict[str, str]]:
    plan = plan_env_bridge(
        project,
        source_file=source_file,
        allowed=allowed,
        aliases=aliases,
        project_keys_only=project_keys_only,
        update_existing=update_existing,
    )
    changes = {**plan.additions, **plan.updates}
    if apply:
        apply_env_bridge(plan)
    return plan.target, changes, plan.resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka env-bridge",
        description="Discover required project env keys, then fill from Arka .env (constants.py fallback)",
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--discover", action="store_true", help="Only list required env keys for the project")
    parser.add_argument("--update", action="store_true", help="Replace existing keys when a better value is found")
    parser.add_argument("--allow", default="", help="Comma-separated keys to copy")
    parser.add_argument("--source", type=Path, default=None, help="Arka .env file (default: config or checkout)")
    parser.add_argument(
        "--map",
        default="",
        help="Comma-separated src=dst aliases (default includes linkedin_email=LINKEDIN_USERNAME)",
    )
    parser.add_argument(
        "--all-keys",
        action="store_true",
        help="Do not restrict to keys referenced by the target project",
    )
    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    if not project.is_dir():
        print(f"project not found: {project}")
        return 1

    allowed = {x.strip() for x in args.allow.split(",") if x.strip()} or None
    aliases: dict[str, str] = {}
    for part in args.map.split(","):
        part = part.strip()
        if "=" in part:
            src, dst = part.split("=", 1)
            aliases[src.strip()] = dst.strip()

    source = args.source.expanduser().resolve() if args.source else None
    if args.discover:
        for key in _project_keys(project):
            print(f"required_key\t{key}")
        print(f"required\t{len(_project_keys(project))}")
        return 0

    plan = plan_env_bridge(
        project,
        source_file=source,
        allowed=allowed,
        aliases=aliases or None,
        project_keys_only=not args.all_keys,
        update_existing=args.update,
    )
    print_env_bridge_plan(plan)
    if not args.apply:
        print("preview\tpass --apply to write; values never printed")
        return 0
    count = apply_env_bridge(plan)
    print(f"applied\t{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
