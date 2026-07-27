"""Arka config backup, restore, and unified config root helpers."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

BACKUP_VERSION = 1
MANIFEST_NAME = "manifest.json"
CONFIG_ARCHIVE_PREFIX = "config/"
CACHE_ARCHIVE_PREFIX = "cache/"
SKIP_DIR_NAMES = frozenset(
    {"venv-arka", "venv-voice-hf", "__pycache__", ".git", "backups"}
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_paths() -> tuple[Any, Any, Any]:
    from arka.paths import cache_dir, config_dir, env_file

    return config_dir, cache_dir, env_file


def _hub_dir() -> Path:
    try:
        from arka.integrations.agent_hub import hub_dir

        return hub_dir()
    except ImportError:
        from arka.paths import config_dir

        return config_dir() / "hub"


def _known_paths() -> list[tuple[str, Path]]:
    from arka.paths import cache_dir, config_dir, env_file

    cfg = config_dir()
    entries: list[tuple[str, Path]] = [
        ("config_root", cfg),
        ("env", env_file()),
        ("hub", _hub_dir()),
        ("teams", cfg / "teams"),
        ("workflows", cfg / "workflows"),
        ("mcp", cfg / "mcp.json"),
        ("personalize", cfg / "personalize.json"),
        ("platform", cfg / "platform.json"),
        ("agent_memory", cfg / "agent-memory"),
        ("message_sessions", cfg / "message-sessions"),
        ("skills", cfg / "skills"),
        ("learned_routes", cfg / "learned_routes.json"),
        ("charts", cfg / "charts.yaml"),
        ("llm_skill_models", cfg / "llm-skill-models.json"),
        ("benchmarks", cfg / "benchmarks"),
        ("benchmark_results", cfg / "benchmark-results.json"),
        ("cache_root", cache_dir()),
        ("cache_memory", cache_dir() / "memory.json"),
    ]
    return entries


def _file_size(path: Path) -> int | None:
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return None
    return None


def iter_config_entries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, path in _known_paths():
        exists = path.exists()
        rows.append(
            {
                "label": label,
                "path": str(path),
                "exists": exists,
                "kind": "dir" if path.is_dir() else "file" if path.is_file() else "missing",
                "bytes": _file_size(path) if exists else 0,
            }
        )
    return rows



def list_payload() -> dict[str, Any]:
    """Structured config inventory for MCP / automation clients."""
    from arka.paths import cache_dir, config_dir

    entries = iter_config_entries()
    return {
        "config_dir": str(config_dir()),
        "cache_dir": str(cache_dir()),
        "count": len(entries),
        "entries": entries,
    }


def path_payload(target: Path | str | None = None) -> dict[str, Any]:
    """Config/cache path summary for MCP clients."""
    from arka.paths import cache_dir, config_dir

    cfg = (Path(target) if target else config_dir()).expanduser().resolve()
    return {
        "config_dir": str(cfg),
        "cache_dir": str(cache_dir()),
        "exists": cfg.exists(),
        "export_snippet": export_snippet(cfg),
    }


def format_list() -> str:
    from arka.paths import config_dir

    lines = [f"config_root\t{config_dir()}"]
    for row in iter_config_entries():
        if row["label"] == "config_root":
            continue
        size = row.get("bytes") or 0
        lines.append(
            f"{row['label']}\t{row['path']}\t{row['kind']}\t{size}"
        )
    return "\n".join(lines)


def export_snippet(target: Path | None = None) -> str:
    config_dir, _, _ = _load_paths()
    root = (target or config_dir()).expanduser().resolve()
    return (
        f'# Unified Arka config root\n'
        f'export ARKA_CONFIG_DIR="{root}"\n'
        f'export CONFIG_DIR="{root}"\n'
    )


def format_path(target: Path | None = None) -> str:
    from arka.paths import cache_dir, config_dir

    cfg = (target or config_dir()).expanduser().resolve()
    lines = [
        f"config_dir\t{cfg}",
        f"cache_dir\t{cache_dir()}",
        f"hub_dir\t{_hub_dir()}",
        "",
        export_snippet(cfg).rstrip(),
    ]
    return "\n".join(lines)


def _should_skip(path: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    name = path.name
    if name.endswith(".tar.gz") or name.endswith(".staging") or name.startswith(".restore-"):
        return True
    return False


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return
    for item in src.rglob("*"):
        if _should_skip(item):
            continue
        rel = item.relative_to(src)
        if _should_skip(rel):
            continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _env_files_for_backup() -> list[tuple[Path, str]]:
    """Env files Arka may load (deduped), archived under env/<label>/."""
    from arka.paths import arka_home, checkout_root, config_dir, env_file

    seen: set[Path] = set()
    rows: list[tuple[Path, str]] = []

    def add(path: Path, label: str) -> None:
        resolved = path.expanduser().resolve()
        if resolved in seen or not resolved.is_file():
            return
        seen.add(resolved)
        rows.append((resolved, f"env/{label}/{resolved.name}"))

    add(env_file(), "primary")
    cfg = config_dir()
    add(cfg / "platform.env", "config")
    root = checkout_root()
    if root:
        add(root / ".env", "checkout")
        add(root / "platform.env", "checkout")
    add(Path.home() / ".config" / "fish" / ".env", "legacy-fish")
    add(arka_home() / ".env", "install-home")
    return rows


def _cache_files_for_backup() -> list[Path]:
    from arka.paths import cache_dir

    cache = cache_dir()
    candidates = [cache / "memory.json"]
    return [p for p in candidates if p.is_file()]


def default_backup_path(output: Path | None = None) -> Path:
    if output:
        return output.expanduser().resolve()
    config_dir, _, _ = _load_paths()
    backups = config_dir() / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    return backups / f"arka-config-{stamp}.tar.gz"


def create_backup(output: Path | None = None) -> dict[str, Any]:
    config_dir_fn, cache_dir_fn, _ = _load_paths()
    cfg = config_dir_fn()
    cache_root = cache_dir_fn()
    archive_path = default_backup_path(output)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    entries: list[tuple[Path, str]] = []
    env_entries = _env_files_for_backup()
    cfg_resolved = cfg.resolve()

    for path, arcname in env_entries:
        resolved = path.resolve()
        if cfg_resolved in resolved.parents or resolved.parent == cfg_resolved:
            continue
        entries.append((path, arcname))

    if cfg.is_dir():
        for item in cfg.rglob("*"):
            if not item.is_file() or _should_skip(item):
                continue
            rel = item.relative_to(cfg)
            if _should_skip(rel):
                continue
            entries.append((item, f"config/{rel.as_posix()}"))

    for cache_file in _cache_files_for_backup():
        rel = cache_file.relative_to(cache_root)
        entries.append((cache_file, f"cache/{rel.as_posix()}"))

    config_count = sum(1 for _, arc in entries if arc.startswith("config/"))
    cache_count = sum(1 for _, arc in entries if arc.startswith("cache/"))
    env_count = len(env_entries)
    manifest: dict[str, Any] = {
        "version": BACKUP_VERSION,
        "created_at": _iso_now(),
        "config_dir": str(cfg),
        "cache_dir": str(cache_root),
        "files": {"config": config_count, "cache": cache_count, "env": env_count},
        "env_files": [str(p) for p, _ in env_entries],
    }

    if archive_path.is_file():
        archive_path.unlink()

    with tarfile.open(archive_path, "w:gz") as tar:
        manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        info = tarfile.TarInfo(name=MANIFEST_NAME)
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))
        for path, arcname in entries:
            tar.add(path, arcname=arcname, recursive=False)

    return {
        "ok": True,
        "archive": str(archive_path),
        "bytes": archive_path.stat().st_size,
        "manifest": manifest,
        "env_files": manifest.get("env_files") or [],
    }


def _extract_archive(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"Invalid backup: missing {MANIFEST_NAME}")
    return manifest_path


def restore_backup(archive: Path, *, force: bool = False) -> dict[str, Any]:
    from arka.paths import arka_home, checkout_root

    config_dir, cache_dir, _ = _load_paths()
    src = archive.expanduser().resolve()
    if not src.is_file():
        return {"ok": False, "error": "archive not found", "archive": str(src)}

    staging = Path(tempfile.mkdtemp(prefix="arka-config-restore-"))

    manifest: dict[str, Any] = {}
    try:
        manifest_path = _extract_archive(src, staging)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("invalid manifest")

        target_cfg = config_dir()
        if not force:
            print(f"Restore will overwrite config at: {target_cfg}", file=sys.stderr)
            print(f"Backup created: {manifest.get('created_at', 'unknown')}", file=sys.stderr)
            print(f"Source config: {manifest.get('config_dir', 'unknown')}", file=sys.stderr)
            answer = input("Continue? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                return {"ok": False, "cancelled": True, "archive": str(src)}

        config_src = staging / "config"
        if config_src.is_dir():
            target_cfg.mkdir(parents=True, exist_ok=True)
            for item in config_src.iterdir():
                if item.name == "backups":
                    continue
                dest = target_cfg / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

        env_root = staging / "env"
        if env_root.is_dir():
            for label_dir in env_root.iterdir():
                if not label_dir.is_dir():
                    continue
                for env_file in label_dir.iterdir():
                    if not env_file.is_file():
                        continue
                    target = None
                    if label_dir.name == "legacy-fish":
                        target = Path.home() / ".config" / "fish" / env_file.name
                    elif label_dir.name == "checkout":
                        root = checkout_root()
                        if root:
                            target = root / env_file.name
                    elif label_dir.name == "install-home":
                        target = arka_home() / env_file.name
                    elif label_dir.name in ("primary", "config"):
                        target = target_cfg / env_file.name
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(env_file, target)

        cache_src = staging / "cache"
        if cache_src.is_dir():
            cache_target = cache_dir()
            cache_target.mkdir(parents=True, exist_ok=True)
            for item in cache_src.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(cache_src)
                    dest = cache_target / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {
        "ok": True,
        "archive": str(src),
        "config_dir": str(config_dir()),
        "restored_from": manifest.get("created_at"),
    }


def init_config(target: Path, *, migrate: bool = False) -> dict[str, Any]:
    from arka.paths import bundled_env_example, ensure_layout

    root = target.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    example = root / ".env.example"
    if not example.is_file():
        src = bundled_env_example()
        if src.is_file():
            shutil.copy2(src, example)

    env = root / ".env"
    if not example.is_file() and bundled_env_example().is_file():
        shutil.copy2(bundled_env_example(), example)
    if not env.is_file() and example.is_file():
        shutil.copy2(example, env)

    migrated_from: str | None = None
    if migrate:
        config_dir, _, _ = _load_paths()
        old = config_dir()
        if old.resolve() != root and old.is_dir():
            for item in old.iterdir():
                if item.name in SKIP_DIR_NAMES:
                    continue
                dest = root / item.name
                if dest.exists():
                    continue
                if item.is_dir():
                    shutil.copytree(item, dest)
                elif item.is_file():
                    shutil.copy2(item, dest)
            migrated_from = str(old)

    # Ensure hub + platform cache under the new root when ARKA_CONFIG_DIR is set.
    prev = os.environ.get("CONFIG_DIR")
    os.environ["CONFIG_DIR"] = str(root)
    os.environ["ARKA_CONFIG_DIR"] = str(root)
    try:
        ensure_layout()
    finally:
        if prev:
            os.environ["CONFIG_DIR"] = prev
        else:
            os.environ.pop("CONFIG_DIR", None)

    return {
        "ok": True,
        "config_dir": str(root),
        "migrated_from": migrated_from,
        "snippet": export_snippet(root),
    }


def maybe_backup_before_unify() -> dict[str, Any] | None:
    flag = os.environ.get("ARKA_CONFIG_BACKUP_ON_UNIFY", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return None
    result = create_backup()
    return result


def cmd_list(_args: argparse.Namespace) -> int:
    print(format_list())
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    target = Path(args.dir).expanduser() if args.dir else None
    print(format_path(target))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser() if args.output else None
    result = create_backup(output)
    print(f"Backup saved: {result['archive']}")
    print(f"  size: {result['bytes']:,} bytes")
    print(f"  config files: {result['manifest']['files']['config']}")
    print(f"  cache files: {result['manifest']['files']['cache']}")
    env_files = result.get("env_files") or []
    if env_files:
        print(f"  env files: {len(env_files)}")
        for path in env_files:
            print(f"    - {path}")
    else:
        print("  env files: 0 (no .env found — check CONFIG_DIR / ~/.config/arka/.env)")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    result = restore_backup(Path(args.archive), force=args.force)
    if result.get("cancelled"):
        print("cancelled\ttrue", file=sys.stderr)
        return 1
    if not result.get("ok"):
        print(f"error\t{result.get('error', 'restore failed')}", file=sys.stderr)
        return 1
    print("ok\ttrue")
    print(f"config_dir\t{result.get('config_dir')}")
    print(f"restored_from\t{result.get('restored_from')}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    result = init_config(Path(args.dir), migrate=args.migrate)
    print(f"config_dir\t{result['config_dir']}")
    if result.get("migrated_from"):
        print(f"migrated_from\t{result['migrated_from']}")
    print("")
    print(result["snippet"].rstrip())
    print("")
    print("Add the export lines to your shell profile, then restart shells or run: arka reload")
    return 0


def build_backup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arka backup",
        description="Compressed backup of all Arka config and cache files",
    )
    sub = parser.add_subparsers(dest="command")

    all_p = sub.add_parser("all", help="Archive entire config dir + cache snippets (default)")
    all_p.add_argument(
        "-o",
        "--output",
        help="Output .tar.gz path (default: config/backups/arka-config-YYYY-MM-DD.tar.gz)",
    )
    all_p.set_defaults(func=cmd_backup)

    backup_p = sub.add_parser("backup", help="Alias for all")
    backup_p.add_argument("-o", "--output")
    backup_p.set_defaults(func=cmd_backup)

    sub.add_parser("list", help="List config paths and sizes").set_defaults(func=cmd_list)
    restore_p = sub.add_parser("restore", help="Restore config from archive")
    restore_p.add_argument("archive", help="Backup .tar.gz path")
    restore_p.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    restore_p.set_defaults(func=cmd_restore)

    return parser


def main_backup(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    raw = list(argv if argv is not None else sys.argv[1:])
    if not raw or raw[0] in ("-h", "--help", "help"):
        build_backup_parser().print_help()
        return 0
    if raw[0] not in {"all", "backup", "list", "restore"}:
        raw = ["all", *raw]
    parser = build_backup_parser()
    args = parser.parse_args(raw)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arka config",
        description="Unified config root, backup, and restore",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List config paths and sizes")
    backup_p = sub.add_parser("backup", help="Archive config dir + selected cache files")
    backup_p.add_argument(
        "-o",
        "--output",
        help="Output .tar.gz path (default: config/backups/arka-config-YYYY-MM-DD.tar.gz)",
    )
    restore_p = sub.add_parser("restore", help="Restore config from archive")
    restore_p.add_argument("archive", help="Backup .tar.gz path")
    restore_p.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    path_p = sub.add_parser("path", help="Show config root and export snippet")
    path_p.add_argument(
        "--dir",
        help="Preview snippet for a target directory",
    )
    init_p = sub.add_parser("init", help="Initialize a config directory")
    init_p.add_argument(
        "--dir",
        required=True,
        help="Target config directory (does not move existing config unless --migrate)",
    )
    init_p.add_argument(
        "--migrate",
        action="store_true",
        help="Copy files from current config dir into the new directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    raw = list(argv if argv is not None else sys.argv[1:])
    if not raw or raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args(raw)
    if not args.command:
        _print_help()
        return 0

    handlers = {
        "list": cmd_list,
        "path": cmd_path,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "init": cmd_init,
    }
    return handlers[args.command](args)


def _print_help() -> None:
    print(
        """Arka config — unified config root, backup, and restore

Usage:
  arka backup all [-o FILE]         Quick compressed backup (all config files)
  arka config backup [-o FILE]        Same as arka backup all
  arka config path                  Show config root + export snippet
  arka config list                  List config paths and sizes
  arka config restore ARCHIVE       Restore (prompts unless --force)
  arka config init --dir PATH       Initialize a new config directory

Environment:
  ARKA_CONFIG_DIR / CONFIG_DIR      Single config root (default ~/.config/arka)
  ARKA_CONFIG_BACKUP_ON_UNIFY=1     Auto-backup before agent_hub sync --unify

Examples:
  arka backup all
  arka backup all -o ~/backups/arka-2026-07-26.tar.gz
  arka config backup -o ~/backups/arka-2026-07-11.tar.gz
  arka config restore ~/backups/arka-2026-07-11.tar.gz --force
  arka config init --dir ~/my-arka-config
  export ARKA_CONFIG_DIR=~/my-arka-config
"""
    )


__all__ = [
    "create_backup",
    "default_backup_path",
    "export_snippet",
    "format_list",
    "format_path",
    "init_config",
    "iter_config_entries",
    "main_backup",
    "maybe_backup_before_unify",
    "restore_backup",
]
