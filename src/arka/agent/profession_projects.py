#!/usr/bin/env python3
"""Clone GitHub repos for profession domains that have real local projects."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from arka.paths import cache_dir, config_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def load_env_file() -> None:
        pass


MANIFEST_FILE = cache_dir() / "profession_projects.json"
DEFAULT_ROOT = Path.home() / "Projects" / "professions"

# Only domains with real cloned repos — matches professions.py project_key.
DOMAIN_IDS = ("investor", "startup", "nutrition", "engineer")


@dataclass(frozen=True)
class RepoSpec:
    name: str
    url: str
    primary: bool = False
    entry: str | None = None
    shared: bool = False


@dataclass(frozen=True)
class DomainBundle:
    id: str
    env_key: str
    repos: tuple[RepoSpec, ...]


BUNDLES: tuple[DomainBundle, ...] = (
    DomainBundle(
        "investor",
        "STOCK_PROJECT",
        (
            RepoSpec(
                "stock_analyzer",
                "https://github.com/Sumit884-byte/stock_analyzer.git",
                primary=True,
                entry="use_model.py",
            ),
        ),
    ),
    DomainBundle(
        "startup",
        "PROFESSION_STARTUP_PROJECT",
        (
            RepoSpec(
                "GameGen",
                "https://github.com/Sumit884-byte/GameGen.git",
                primary=True,
            ),
        ),
    ),
    DomainBundle(
        "nutrition",
        "PROFESSION_NUTRITION_PROJECT",
        (
            RepoSpec(
                "nourish-diet-planner",
                "https://github.com/paradise-007/nourish-diet-planner.git",
                primary=True,
                entry="app.py",
            ),
        ),
    ),
    DomainBundle(
        "engineer",
        "PROFESSION_ENGINEER_PROJECT",
        (
            RepoSpec(
                "agno",
                "https://github.com/Sumit884-byte/agno.git",
                primary=True,
            ),
        ),
    ),
)

_BY_ID = {b.id: b for b in BUNDLES}


def projects_root() -> Path:
    raw = os.environ.get("PROFESSIONS_ROOT", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_ROOT


def _repo_path(bundle_id: str, spec: RepoSpec) -> Path:
    return projects_root() / bundle_id / spec.name


def _primary_path(bundle: DomainBundle) -> Path | None:
    for spec in bundle.repos:
        if spec.primary:
            path = _repo_path(bundle.id, spec)
            if path.is_dir():
                return path
    for spec in bundle.repos:
        path = _repo_path(bundle.id, spec)
        if path.is_dir():
            return path
    return None


def _git_clone(url: str, dest: Path, *, depth: int = 1) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_dir() and (dest / ".git").is_dir():
        print(f"  ✓ {dest}", file=sys.stderr)
        return
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} exists but is not a git repo")
    print(f"  cloning {url}", file=sys.stderr)
    subprocess.run(["git", "clone", f"--depth={depth}", url, str(dest)], check=True)


def clone_domain(domain_id: str, *, depth: int = 1) -> None:
    aliases = {"nutritionist": "nutrition", "doctor": "health"}
    domain_id = aliases.get(domain_id, domain_id)
    bundle = _BY_ID.get(domain_id)
    if not bundle:
        raise SystemExit(f"Unknown domain: {domain_id}. Valid: {', '.join(DOMAIN_IDS)}")
    for spec in bundle.repos:
        _git_clone(spec.url, _repo_path(bundle.id, spec), depth=depth)


def clone_all(*, depth: int = 1) -> None:
    for bundle in BUNDLES:
        for spec in bundle.repos:
            _git_clone(spec.url, _repo_path(bundle.id, spec), depth=depth)


def build_manifest() -> dict:
    professions: dict[str, dict] = {}
    env_lines: dict[str, str] = {}
    for bundle in BUNDLES:
        primary = _primary_path(bundle)
        repos = {}
        for spec in bundle.repos:
            path = _repo_path(bundle.id, spec)
            repos[spec.name] = {
                "path": str(path),
                "url": spec.url,
                "cloned": path.is_dir(),
                "primary": spec.primary,
                "entry": spec.entry,
            }
        professions[bundle.id] = {
            "env_key": bundle.env_key,
            "primary_path": str(primary) if primary else None,
            "repos": repos,
        }
        if primary:
            env_lines[bundle.env_key] = str(primary)
    return {
        "version": 2,
        "updated": datetime.now(timezone.utc).isoformat(),
        "root": str(projects_root()),
        "domains": professions,
        "env": env_lines,
    }


def save_manifest(data: dict | None = None) -> Path:
    data = data or build_manifest()
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return MANIFEST_FILE


def load_manifest() -> dict:
    if MANIFEST_FILE.is_file():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return build_manifest()


def profession_project_path(domain_id: str) -> Path | None:
    aliases = {"nutritionist": "nutrition", "doctor": "health"}
    domain_id = aliases.get(domain_id, domain_id)
    manifest = load_manifest()
    prof = manifest.get("domains", manifest.get("professions", {})).get(domain_id, {})
    raw = prof.get("primary_path")
    if raw:
        path = Path(raw).expanduser()
        if path.is_dir():
            return path
    bundle = _BY_ID.get(domain_id)
    if bundle:
        env = os.environ.get(bundle.env_key, "").strip()
        if env and Path(env).expanduser().is_dir():
            return Path(env).expanduser()
        primary = _primary_path(bundle)
        if primary:
            return primary
    # Legacy layout from earlier clones (nutritionist/…)
    legacy_names = {
        "nutrition": ("nutritionist", "nourish-diet-planner"),
        "investor": ("investor", "stock_analyzer"),
        "startup": ("startup", "GameGen"),
        "engineer": ("engineer", "agno"),
    }
    if domain_id in legacy_names:
        folder, repo = legacy_names[domain_id]
        legacy = projects_root() / folder / repo
        if legacy.is_dir():
            return legacy
    return None


def sync_env_keys(manifest: dict, *, write: bool = False) -> list[str]:
    env_path = config_dir() / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    lines_out: list[str] = []
    for key, val in manifest.get("env", {}).items():
        if not val or not Path(val).is_dir():
            continue
        entry = f"{key}={val}"
        lines_out.append(entry)
        pat = re.compile(rf"^\s*{re.escape(key)}\s*=", re.M)
        if pat.search(existing):
            existing = pat.sub(entry, existing, count=1)
        else:
            existing += f"\n# Profession domain projects\n{entry}\n"
    if write and lines_out:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(existing, encoding="utf-8")
    return lines_out


def cmd_status() -> int:
    m = build_manifest()
    print(f"Root: {m['root']}")
    for pid, prof in m["domains"].items():
        p = prof.get("primary_path") or "(not cloned)"
        print(f"  {'✓' if p != '(not cloned)' else '○'} {pid:<12} {p}")
    print("\nDomains without local repos: health, teacher, legal, journalism, marketing, finance, counselor, chef")
    print("After clone: repos are indexed automatically for profession ask (use setup --no-index to skip)")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    if args.domain:
        clone_domain(args.domain, depth=args.depth)
    else:
        clone_all(depth=args.depth)
    manifest = build_manifest()
    save_manifest(manifest)
    lines = sync_env_keys(manifest, write=args.write_env)
    print(f"Manifest → {MANIFEST_FILE}")
    for line in lines:
        print(line)
    if not args.no_index:
        try:
            from arka.agent.profession_sources import index_domain_codebase

            targets = [args.domain] if args.domain else list(DOMAIN_IDS)
            for dom in targets:
                ok, msg = index_domain_codebase(dom)
                mark = "✓" if ok else "○"
                print(f"  {mark} index {dom}: {msg}", file=sys.stderr)
        except ImportError as exc:
            print(f"Index skipped: {exc}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup")
    p.add_argument("domain", nargs="?")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--write-env", action="store_true")
    p.add_argument("--no-index", action="store_true", help="Skip TurboQuant indexing after clone")
    p.set_defaults(func=cmd_setup)
    sub.add_parser("status").set_defaults(func=lambda _: cmd_status())
    p2 = sub.add_parser("path")
    p2.add_argument("domain")
    p2.set_defaults(
        func=lambda a: (print(p) or 0)
        if (p := profession_project_path(a.domain))
        else (print("not cloned", file=sys.stderr) or 1)
    )
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
