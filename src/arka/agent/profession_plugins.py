#!/usr/bin/env python3
"""Third-party profession domains — discover, install, and merge with built-in registries."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from arka.agent.profession_sources import DomainSources, RssSource
    from arka.agent.professions import BUILTIN_DOMAINS, Domain
    from arka.paths import arka_home, cache_dir, config_dir, load_env_file

    load_env_file()
except ImportError:
    BUILTIN_DOMAINS = ()  # type: ignore[misc, assignment]

    @dataclass(frozen=True)
    class Domain:  # type: ignore[no-redef]
        id: str
        title: str
        aliases: tuple[str, ...]
        keywords: tuple[str, ...]
        disclaimer: str
        project_key: str | None = None

    @dataclass(frozen=True)
    class RssSource:  # type: ignore[no-redef]
        id: str
        label: str
        url: str
        limit: int = 6

    @dataclass(frozen=True)
    class DomainSources:  # type: ignore[no-redef]
        domain_id: str
        rss: tuple[RssSource, ...] = ()
        search_bias: str = ""
        codebase_artifact: str | None = None
        bridge: str | None = None

    def config_dir() -> Path:
        if env := os.environ.get("CONFIG_DIR", "").strip():
            return Path(env).expanduser()
        legacy = Path.home() / ".config" / "fish"
        return legacy if (legacy / ".env").is_file() else Path.home() / ".config" / "arka"

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def arka_home() -> Path:
        if env := os.environ.get("INSTALL_HOME", "").strip():
            return Path(env).expanduser()
        return Path(__file__).resolve().parent.parent

    def load_env_file() -> None:
        pass

PROFESSION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,32}$")
REGISTRY_FILE = cache_dir() / "third_party_professions.json"
_CACHE_TTL = 30.0
_cache_version = 0.0


def professions_search_paths() -> list[Path]:
    paths: list[Path] = []
    for raw in (os.environ.get("PROFESSIONS_PATH") or "").split(os.pathsep):
        raw = raw.strip()
        if raw:
            paths.append(Path(raw).expanduser())
    paths.extend(
        [
            config_dir() / "professions",
            arka_home() / "professions",
            Path.home() / ".local" / "share" / "arka" / "professions",
        ]
    )
    if os.environ.get("ARKA_PROFESSION_EXAMPLES", "").strip().lower() in ("1", "true", "yes"):
        paths.append(Path(__file__).resolve().parent.parent / "professions" / "examples")
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp.is_dir() and rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _expand_path(raw: str, *, root: Path) -> Path | None:
    text = (raw or "").strip()
    if not text:
        return None
    text = os.path.expandvars(text)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    return path if path.is_dir() else None


def _manifest_to_domain(data: dict[str, Any], *, root: Path) -> Domain | None:
    dom_id = (data.get("id") or data.get("name") or root.name).strip().lower()
    if not PROFESSION_ID_RE.match(dom_id):
        return None
    title = (data.get("title") or dom_id.replace("_", " ").title()).strip()
    aliases = data.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    keywords = data.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    aliases_t = tuple(str(a).strip().lower() for a in aliases if str(a).strip())
    keywords_t = tuple(str(k).strip().lower() for k in keywords if str(k).strip())
    project_key = (data.get("project_key") or "").strip() or None
    return Domain(
        dom_id,
        title,
        aliases_t,
        keywords_t,
        (data.get("disclaimer") or "").strip(),
        project_key=project_key,
    )


def _manifest_to_sources(data: dict[str, Any], *, root: Path) -> DomainSources:
    dom_id = (data.get("id") or data.get("name") or root.name).strip().lower()
    rss_items = data.get("rss") or []
    feeds: list[RssSource] = []
    if isinstance(rss_items, list):
        for row in rss_items:
            if not isinstance(row, dict):
                continue
            fid = (row.get("id") or "").strip()
            label = (row.get("label") or fid).strip()
            url = (row.get("url") or "").strip()
            if fid and label and url:
                feeds.append(
                    RssSource(fid, label, url, int(row.get("limit") or 6))
                )
    artifact = (data.get("codebase_artifact") or "").strip() or None
    if not artifact and data.get("project_dir"):
        artifact = f"codebase-{dom_id}"
    return DomainSources(
        dom_id,
        rss=tuple(feeds),
        search_bias=(data.get("search_bias") or "").strip(),
        codebase_artifact=artifact,
        bridge=(data.get("bridge") or "").strip() or None,
    )


def _profession_from_dir(root: Path) -> dict[str, Any] | None:
    manifest = None
    for name in ("profession.json", "manifest.json", "domain.json"):
        candidate = root / name
        if candidate.is_file():
            manifest = candidate
            break
    if manifest is None:
        return None
    data = _read_json(manifest)
    if data.get("enabled") is False:
        return None
    domain = _manifest_to_domain(data, root=root)
    if domain is None:
        return None
    sources = _manifest_to_sources(data, root=root)
    project_dir = _expand_path(str(data.get("project_dir") or ""), root=root)
    rss_rows = []
    for feed in sources.rss:
        rss_rows.append(
            {"id": feed.id, "label": feed.label, "url": feed.url, "limit": feed.limit}
        )
    return {
        "id": domain.id,
        "title": domain.title,
        "aliases": list(domain.aliases),
        "keywords": list(domain.keywords),
        "disclaimer": domain.disclaimer,
        "project_key": domain.project_key,
        "enabled": True,
        "root": str(root),
        "manifest": str(manifest),
        "project_dir": str(project_dir) if project_dir else "",
        "version": (data.get("version") or "0.1.0").strip(),
        "author": (data.get("author") or "").strip(),
        "description": (data.get("description") or "").strip(),
        "search_bias": sources.search_bias,
        "codebase_artifact": sources.codebase_artifact or "",
        "bridge": sources.bridge or "",
        "rss": rss_rows,
    }


def discover_professions(*, refresh: bool = False) -> list[dict[str, Any]]:
    global _cache_version
    if not refresh and REGISTRY_FILE.is_file():
        try:
            cached = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("professions") is not None:
                age = time.time() - REGISTRY_FILE.stat().st_mtime
                if age < _CACHE_TTL:
                    _cache_version = REGISTRY_FILE.stat().st_mtime
                    return cached["professions"]
        except (OSError, json.JSONDecodeError):
            pass

    by_id: dict[str, dict[str, Any]] = {}
    for base in professions_search_paths():
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            prof = _profession_from_dir(child)
            if prof:
                by_id[prof["id"]] = prof

    professions = sorted(by_id.values(), key=lambda p: p["id"])
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps({"updated": time.time(), "professions": professions}, indent=2),
        encoding="utf-8",
    )
    _cache_version = time.time()
    return professions


def invalidate_cache() -> None:
    global _cache_version
    _cache_version = 0.0
    discover_professions(refresh=True)


def plugin_domains(*, refresh: bool = False) -> tuple[Domain, ...]:
    out: list[Domain] = []
    for row in discover_professions(refresh=refresh):
        out.append(
            Domain(
                row["id"],
                row["title"],
                tuple(row.get("aliases") or ()),
                tuple(row.get("keywords") or ()),
                row.get("disclaimer") or "",
                project_key=row.get("project_key"),
            )
        )
    return tuple(out)


def all_domains(*, refresh: bool = False) -> tuple[Domain, ...]:
    builtin_ids = {d.id for d in BUILTIN_DOMAINS}
    plugins = [d for d in plugin_domains(refresh=refresh) if d.id not in builtin_ids]
    return BUILTIN_DOMAINS + tuple(plugins)


def all_alias_to_domain(*, refresh: bool = False) -> dict[str, str]:
    from arka.agent.professions import BUILTIN_ROLE_TO_DOMAIN

    mapping: dict[str, str] = {}
    for d in all_domains(refresh=refresh):
        mapping[d.id] = d.id
        for alias in d.aliases:
            mapping[alias.lower()] = d.id
    for role, dom in BUILTIN_ROLE_TO_DOMAIN.items():
        mapping.setdefault(role, dom)
    return mapping


def domain_by_id(domain_id: str, *, refresh: bool = False) -> Domain | None:
    dom_id = domain_id.strip().lower()
    for d in all_domains(refresh=refresh):
        if d.id == dom_id:
            return d
    return None


def _row_to_sources(row: dict[str, Any]) -> DomainSources:
    feeds: list[RssSource] = []
    for item in row.get("rss") or []:
        if not isinstance(item, dict):
            continue
        fid = (item.get("id") or "").strip()
        label = (item.get("label") or fid).strip()
        url = (item.get("url") or "").strip()
        if fid and label and url:
            feeds.append(RssSource(fid, label, url, int(item.get("limit") or 6)))
    artifact = (row.get("codebase_artifact") or "").strip() or None
    return DomainSources(
        row["id"],
        rss=tuple(feeds),
        search_bias=(row.get("search_bias") or "").strip(),
        codebase_artifact=artifact,
        bridge=(row.get("bridge") or "").strip() or None,
    )


def plugin_sources(*, refresh: bool = False) -> dict[str, DomainSources]:
    out: dict[str, DomainSources] = {}
    for row in discover_professions(refresh=refresh):
        out[row["id"]] = _row_to_sources(row)
    return out


def plugin_project_path(domain_id: str, *, refresh: bool = False) -> Path | None:
    dom_id = domain_id.strip().lower()
    for row in discover_professions(refresh=refresh):
        if row["id"] != dom_id:
            continue
        raw = (row.get("project_dir") or "").strip()
        if raw:
            path = Path(raw).expanduser()
            if path.is_dir():
                return path
    return None


def is_plugin_domain(domain_id: str, *, refresh: bool = False) -> bool:
    dom_id = domain_id.strip().lower()
    builtin_ids = {d.id for d in BUILTIN_DOMAINS}
    return dom_id not in builtin_ids and any(
        p["id"] == dom_id for p in discover_professions(refresh=refresh)
    )


def list_domain_ids(*, refresh: bool = False) -> list[str]:
    return [d.id for d in all_domains(refresh=refresh)]


def install_profession(source: str) -> int:
    dest_root = config_dir() / "professions"
    dest_root.mkdir(parents=True, exist_ok=True)

    src = source.strip()
    if not src:
        print("Usage: profession install <git-url|path>", file=sys.stderr)
        return 1

    if re.match(r"^https?://", src) or src.startswith("git@"):
        name = Path(src.rstrip("/").split("/")[-1]).stem.replace(".git", "")
        target = dest_root / name
        if target.exists():
            shutil.rmtree(target)
        print(f"Cloning {src} → {target}")
        proc = subprocess.run(["git", "clone", "--depth", "1", src, str(target)])
        if proc.returncode != 0:
            return proc.returncode
        install_id = name
    else:
        src_path = Path(src).expanduser().resolve()
        if not src_path.is_dir():
            print(f"Not a directory: {src_path}", file=sys.stderr)
            return 1
        manifest = None
        for m in ("profession.json", "manifest.json", "domain.json"):
            if (src_path / m).is_file():
                manifest = src_path / m
                break
        if not manifest:
            print(
                "Missing profession.json (needs id, title, aliases, keywords, rss/search_bias).",
                file=sys.stderr,
            )
            return 1
        data = _read_json(manifest)
        install_id = (data.get("id") or data.get("name") or src_path.name).strip().lower()
        if not PROFESSION_ID_RE.match(install_id):
            print(f"Invalid profession id: {install_id}", file=sys.stderr)
            return 1
        target = dest_root / install_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src_path, target)
        print(f"Installed → {target}")

    invalidate_cache()
    prof = next((p for p in discover_professions(refresh=True) if p["id"] == install_id), None)
    if prof:
        print(f"✓ Profession '{prof['id']}' ready — try: profession ask {prof['id']} <question>")
        print(f"  Title: {prof['title']}")
        if prof.get("aliases"):
            print(f"  Aliases: {', '.join(prof['aliases'][:6])}")
    else:
        print(f"Installed folder '{install_id}' but profession.json could not be loaded.", file=sys.stderr)
        return 1
    return 0


def print_plugin_list(*, verbose: bool = False) -> None:
    plugins = discover_professions(refresh=True)
    if not plugins:
        print("No third-party professions installed.")
        print(f"  Install dir: {config_dir() / 'professions'}")
        print("  Try: profession install /path/to/profession  or  profession install <git-url>")
        print(f"  Example: {arka_home() / 'professions' / 'examples'}")
        return
    print(f"Third-party professions ({len(plugins)}):")
    for row in plugins:
        line = f"  {row['id']:<14} {row['title']}"
        if row.get("author"):
            line += f" — {row['author']}"
        print(line)
        if verbose:
            print(f"       root={row.get('root')}")
            if row.get("aliases"):
                print(f"       aliases: {', '.join(row['aliases'][:8])}")
            if row.get("keywords"):
                print(f"       keywords: {', '.join(row['keywords'][:8])}")


def main() -> int:
    parser = __import__("argparse").ArgumentParser(description="Arka third-party professions")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list")
    sub.add_parser("refresh")

    p_ids = sub.add_parser("list-ids")
    p_ids.add_argument("--plugins-only", action="store_true")

    p_install = sub.add_parser("install")
    p_install.add_argument("source")

    p_info = sub.add_parser("info")
    p_info.add_argument("id")

    args = parser.parse_args()
    if args.cmd == "list":
        print_plugin_list(verbose=True)
        return 0
    if args.cmd == "refresh":
        invalidate_cache()
        print("Profession plugin registry refreshed.")
        return 0
    if args.cmd == "list-ids":
        if args.plugins_only:
            for row in discover_professions(refresh=True):
                print(row["id"])
        else:
            for dom_id in list_domain_ids(refresh=True):
                print(dom_id)
        return 0
    if args.cmd == "install":
        return install_profession(args.source)
    if args.cmd == "info":
        row = next((p for p in discover_professions(refresh=True) if p["id"] == args.id), None)
        if not row:
            print(f"Profession not found: {args.id}", file=sys.stderr)
            return 1
        safe = {k: v for k, v in row.items() if k != "sources"}
        print(json.dumps(safe, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
