#!/usr/bin/env python3
"""Harvard ARK Agent CLI — biomedical knowledge graph chat (external tool).

This wraps mims-harvard/ark-agent-cli (PrimeKG, AfriMedKG, OptimusKG).
Not the same as Arka (arka-agent) itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_URL = "https://github.com/mims-harvard/ark-agent-cli.git"
INSTALL_HINT = (
    "Harvard ARK Agent CLI is not installed.\n"
    "  arka harvard-ark install\n"
    "Requires: node, pnpm, git-lfs, bun (dev) or built binary; ANTHROPIC_API_KEY in ~/.config/arka/.env"
)

_KG_NAMES = frozenset({"primekg", "afrimedkg", "optimuskg"})
_EXPLICIT_RE = re.compile(
    r"(?i)\b("
    r"harvard[-_ ]?ark|"
    r"ark[-_ ]agent[-_ ]cli|"
    r"biomedical knowledge graph|"
    r"knowledge graph agent|"
    r"primekg|afrimedkg|optimuskg|"
    r"zitnik\s+lab\s+ark"
    r")\b"
)
_ASK_KG_RE = re.compile(
    r"(?i)\b(?:ask|query|search|use)\s+(?:primekg|afrimedkg|optimuskg|harvard[- ]?ark)\b"
)


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def install_dir() -> Path:
    override = os.environ.get("HARVARD_ARK_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _config_dir() / "tools" / "ark-agent-cli"


def _load_env() -> None:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=merged,
        text=True,
        capture_output=capture,
        check=False,
    )


def _platform() -> str:
    try:
        from arka.platform_info import system

        return system()
    except ImportError:
        return "linux" if sys.platform.startswith("linux") else sys.platform


_BREW_PACKAGES: dict[str, str] = {
    "git": "git",
    "node": "node",
    "pnpm": "pnpm",
    "git-lfs": "git-lfs",
    "bun": "bun",
}

_APT_PACKAGES: dict[str, str] = {
    "git": "git",
    "node": "nodejs",
    "pnpm": "pnpm",
    "git-lfs": "git-lfs",
}


def check_prerequisites(*, for_launch: bool = False) -> list[str]:
    """Return missing tools (empty if satisfied)."""
    missing: list[str] = []
    for tool, hint in (
        ("git", "git"),
        ("node", "Node.js 18+"),
        ("pnpm", "pnpm >= 10"),
    ):
        if not shutil.which(tool):
            missing.append(f"{tool} ({hint})")
    if not for_launch:
        if not shutil.which("git-lfs"):
            missing.append("git-lfs (Git LFS for graph parquet data)")
    if for_launch:
        d = install_dir()
        built = d / "build" / "ark-agent-cli"
        if not built.is_file() and not shutil.which("bun"):
            missing.append("bun (required for `pnpm cli`, or run install to build binary)")
    return missing


def _missing_tool_names(missing: list[str]) -> list[str]:
    names: list[str] = []
    for item in missing:
        name = item.split("(", 1)[0].strip()
        if name:
            names.append(name)
    return names


def ensure_prerequisites(*, for_launch: bool = False) -> list[str]:
    """Install missing prerequisites when possible; return any still missing."""
    missing = check_prerequisites(for_launch=for_launch)
    if not missing:
        return []

    tools = _missing_tool_names(missing)
    plat = _platform()
    if plat == "macos" and shutil.which("brew"):
        pkgs = [_BREW_PACKAGES[t] for t in tools if t in _BREW_PACKAGES]
        if pkgs:
            print(f"Installing prerequisites via Homebrew: {' '.join(pkgs)} …", file=sys.stderr)
            _run(["brew", "install", *pkgs])
    elif plat == "linux" and shutil.which("apt-get"):
        pkgs = [_APT_PACKAGES[t] for t in tools if t in _APT_PACKAGES]
        if pkgs:
            print(f"Installing prerequisites via apt: {' '.join(pkgs)} …", file=sys.stderr)
            _run(["sudo", "apt-get", "install", "-y", *pkgs])
        if "bun" in tools and not shutil.which("bun"):
            print(
                "bun not available via apt — install from https://bun.sh or skip binary build",
                file=sys.stderr,
            )
    elif plat == "linux":
        print(
            "Install prerequisites manually (apt): "
            "sudo apt install git nodejs pnpm git-lfs",
            file=sys.stderr,
        )
    else:
        print(
            "Install prerequisites manually: node, pnpm, git-lfs, bun (macOS: brew install node pnpm git-lfs bun)",
            file=sys.stderr,
        )

    return check_prerequisites(for_launch=for_launch)


def _update_stamp_file() -> Path:
    return install_dir() / ".arka-update-check"


def maybe_update_install(*, ttl: int = 3600) -> bool:
    """Pull + refresh deps if the Harvard ARK checkout is behind origin."""
    dest = install_dir()
    if not (dest / ".git").is_dir():
        return False

    stamp = _update_stamp_file()
    now = time.time()
    if stamp.is_file():
        try:
            if now - float(stamp.read_text(encoding="utf-8").strip()) < ttl:
                return False
        except (OSError, ValueError):
            pass
    try:
        stamp.write_text(str(now), encoding="utf-8")
    except OSError:
        pass

    fetch = _run(["git", "fetch", "--quiet", "origin"], cwd=dest, capture=True)
    if fetch.returncode != 0:
        return False

    behind = _run(["git", "rev-list", "--count", "HEAD..@{u}"], cwd=dest, capture=True)
    count = (behind.stdout or "").strip() if behind.returncode == 0 else ""
    if count in ("", "0"):
        return False

    print(f"Harvard ARK CLI is {count} commit(s) behind — updating …", file=sys.stderr)
    if _run(["git", "pull", "--ff-only"], cwd=dest).returncode != 0:
        print("git pull failed", file=sys.stderr)
        return False

    _run(["git", "lfs", "pull"], cwd=dest)
    if _run(["pnpm", "install"], cwd=dest).returncode != 0:
        print("pnpm install failed after update", file=sys.stderr)
        return False

    if shutil.which("bun"):
        _run(["pnpm", "build"], cwd=dest)
    sync_env_file()
    return True


def is_installed() -> bool:
    d = install_dir()
    return (d / "package.json").is_file() and (
        (d / "node_modules").is_dir() or (d / "build" / "ark-agent-cli").is_file()
    )


def sync_env_file() -> bool:
    """Copy ANTHROPIC_API_KEY from Arka config into the Harvard ARK .env."""
    _load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return False
    target = install_dir() / ".env"
    example = install_dir() / ".env.example"
    lines: list[str] = []
    if target.is_file():
        lines = target.read_text(encoding="utf-8").splitlines()
    elif example.is_file():
        lines = example.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("ANTHROPIC_API_KEY="):
            out.append(f"ANTHROPIC_API_KEY={key}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"ANTHROPIC_API_KEY={key}")
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True


def list_graphs() -> list[dict[str, object]]:
    """Read graph.json metadata from the install data/ directory."""
    data_dir = install_dir() / "data"
    if not data_dir.is_dir():
        return []
    graphs: list[dict[str, object]] = []
    for child in sorted(data_dir.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / "graph.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        graphs.append(
            {
                "slug": child.name,
                "name": meta.get("name", child.name),
                "description": meta.get("description", ""),
                "id": meta.get("id"),
                "order": meta.get("order"),
            }
        )
    graphs.sort(key=lambda g: (g.get("order") if isinstance(g.get("order"), int) else 999, str(g.get("name", ""))))
    return graphs


def cli_exec_prefix() -> list[str] | None:
    d = install_dir()
    built = d / "build" / "ark-agent-cli"
    if built.is_file():
        return [str(built)]
    if (d / "package.json").is_file() and shutil.which("pnpm"):
        return ["pnpm", "cli"]
    return None


def wants_harvard_ark(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if re.match(r"(?i)^(?:arka\s+)?harvard[-_]ark\b", clean):
        return True
    if re.match(r"(?i)^harvard_ark\b", clean):
        return True
    if _ASK_KG_RE.search(clean):
        return True
    if _EXPLICIT_RE.search(clean):
        if re.search(r"(?i)\b(?:self\s+improve|improve\s+arka|fix\s+arka|loop\s+self)\b", clean):
            return False
        return True
    if re.search(r"(?i)\bask\s+primekg\b", clean):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_harvard_ark(text):
        return ""
    clean = (text or "").strip()
    if re.search(r"(?i)\b(?:install|setup|download)\b", clean) and _EXPLICIT_RE.search(clean):
        return "harvard_ark install"
    if re.search(r"(?i)\b(?:harvard[- ]?ark|ark[- ]agent[- ]cli)\s+(?:status|doctor)\b", clean):
        return "harvard_ark status"
    if re.search(r"(?i)\b(?:list|show)\b.*\b(?:graphs?|primekg|knowledge graphs?)\b", clean) and _EXPLICIT_RE.search(
        clean
    ):
        return "harvard_ark list"
    if re.match(r"(?i)^(?:arka\s+)?harvard[-_]ark\s+list\b", clean):
        return "harvard_ark list"
    m = re.match(r"(?i)^(?:arka\s+)?harvard[-_]ark\s+chat(?:\s+(.+))?$", clean)
    if m:
        rest = (m.group(1) or "").strip()
        return "harvard_ark chat " + shlex.quote(rest) if rest else "harvard_ark chat"
    m = re.search(
        r"(?i)\b(?:ask|query|search|use)\s+(?:primekg|afrimedkg|optimuskg|harvard[- ]?ark)\s+(?:about\s+)?(.+)$",
        clean,
    )
    if m:
        return "harvard_ark chat " + shlex.quote(m.group(1).strip())
    if re.search(r"(?i)\b(?:chat|talk|explore)\b", clean) and _EXPLICIT_RE.search(clean):
        q = re.sub(
            r"(?i)^.*?\b(?:chat|talk|explore|with|using|on|about)\s+",
            "",
            clean,
        ).strip(" ?.")
        if q and not re.match(r"(?i)^(?:primekg|afrimedkg|optimuskg|harvard[- ]?ark)\b", q):
            return "harvard_ark chat " + shlex.quote(q)
        return "harvard_ark chat"
    return "harvard_ark chat"


def nl_to_argv(text: str) -> list[str] | None:
    route = route_command(text)
    if not route:
        return None
    return shlex.split(route)[1:]


def cmd_install() -> int:
    missing = ensure_prerequisites()
    if missing:
        print("Missing prerequisites:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1

    dest = install_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.is_dir() and (dest / ".git").is_dir():
        print(f"Updating {dest} …", file=sys.stderr)
        rc = _run(["git", "pull", "--ff-only"], cwd=dest).returncode
        if rc != 0:
            print("git pull failed", file=sys.stderr)
            return rc
    else:
        if dest.exists() and any(dest.iterdir()):
            print(f"Install path exists and is not a git repo: {dest}", file=sys.stderr)
            return 1
        print(f"Cloning {REPO_URL} → {dest} …", file=sys.stderr)
        rc = _run(["git", "clone", REPO_URL, str(dest)]).returncode
        if rc != 0:
            return rc

    print("Fetching knowledge graph data (git lfs pull) …", file=sys.stderr)
    _run(["git", "lfs", "install"], cwd=dest)
    lfs = _run(["git", "lfs", "pull"], cwd=dest)
    if lfs.returncode != 0:
        print("git lfs pull failed — graph parquet files may be missing", file=sys.stderr)
        if lfs.stderr:
            print(lfs.stderr, file=sys.stderr)

    print("Installing npm dependencies (pnpm install) …", file=sys.stderr)
    rc = _run(["pnpm", "install"], cwd=dest).returncode
    if rc != 0:
        return rc

    if not sync_env_file():
        print(
            "Warning: ANTHROPIC_API_KEY not found in Arka config — add it to ~/.config/arka/.env",
            file=sys.stderr,
        )
    else:
        print("Synced ANTHROPIC_API_KEY to install .env", file=sys.stderr)

    if shutil.which("bun"):
        print("Building standalone binary (pnpm build) …", file=sys.stderr)
        build_rc = _run(["pnpm", "build"], cwd=dest).returncode
        if build_rc != 0:
            print("pnpm build failed — you can still run via `pnpm cli` (needs bun)", file=sys.stderr)
    else:
        print("bun not found — skipped binary build; install bun or use `pnpm cli`", file=sys.stderr)

    print(f"Harvard ARK Agent CLI ready at {dest}", file=sys.stderr)
    print("Run: arka harvard-ark chat", file=sys.stderr)
    return 0


def cmd_list() -> int:
    if not is_installed():
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    maybe_update_install()
    graphs = list_graphs()
    if not graphs:
        print("No knowledge graphs found in data/ — run: arka harvard-ark install", file=sys.stderr)
        return 1
    print("Harvard ARK knowledge graphs (Zitnik Lab):")
    for g in graphs:
        name = g.get("name", g.get("slug", "?"))
        desc = g.get("description", "")
        slug = g.get("slug", "")
        line = f"  • {name} ({slug})"
        if desc:
            line += f" — {desc}"
        print(line)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    d = install_dir()
    print(f"harvard_ark\t{'installed' if is_installed() else 'not_installed'}")
    print(f"install_dir\t{d}")
    missing = check_prerequisites(for_launch=is_installed())
    if missing:
        print("missing\t" + ", ".join(missing))
    else:
        print("prerequisites\tok")
    _load_env()
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("auth\tANTHROPIC_API_KEY set")
    else:
        print("auth\tANTHROPIC_API_KEY missing")
    prefix = cli_exec_prefix()
    if prefix:
        print(f"launch\t{' '.join(prefix)}")
    graphs = list_graphs()
    print(f"graphs\t{len(graphs)}")
    return 0 if is_installed() else 1


def run_harvard_ark(argv: list[str], *, inherit_stdio: bool = True) -> int:
    prefix = cli_exec_prefix()
    if not prefix:
        print(INSTALL_HINT, file=sys.stderr)
        return 127

    missing = check_prerequisites(for_launch=True)
    if missing:
        print("Missing prerequisites:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1

    if not sync_env_file():
        print(
            "ANTHROPIC_API_KEY not set — add it to ~/.config/arka/.env before chatting",
            file=sys.stderr,
        )
        return 1

    if inherit_stdio:
        return _run(prefix + argv, cwd=install_dir()).returncode
    proc = _run(prefix + argv, cwd=install_dir(), capture=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


def cmd_chat(argv: list[str]) -> int:
    if not is_installed():
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    maybe_update_install()
    initial = " ".join(argv).strip()
    if initial:
        print(
            "Note: Harvard ARK CLI is interactive — type your question in the TUI.",
            file=sys.stderr,
        )
        print(f"Suggested question: {initial}", file=sys.stderr)
    return run_harvard_ark([])


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])

    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    if not raw:
        _print_help()
        return 0

    cmd = raw[0]
    rest = raw[1:]

    if cmd in ("harvard_ark", "harvard-ark", "harvardark"):
        if not rest:
            _print_help()
            return 0
        return main(rest)

    if cmd in ("install", "setup"):
        return cmd_install()
    if cmd == "list":
        return cmd_list()
    if cmd == "status":
        return cmd_status(argparse.Namespace())
    if cmd == "chat":
        return cmd_chat(rest)
    if cmd == "doctor":
        return cmd_status(argparse.Namespace())

    nl = nl_to_argv(" ".join(raw))
    if nl:
        return main(nl)

    return cmd_chat(raw)


def _print_help() -> None:
    print(
        """Harvard ARK Agent CLI (external — not Arka itself)

Biomedical knowledge graph chat from Zitnik Lab (PrimeKG, AfriMedKG, OptimusKG).
Repo: https://github.com/mims-harvard/ark-agent-cli

Usage:
  arka harvard-ark install          Clone, pnpm install, git lfs pull
  arka harvard-ark list             List available knowledge graphs
  arka harvard-ark chat             Launch interactive graph chat (TUI)
  arka harvard-ark chat "question"  Launch TUI (suggested question printed)
  arka harvard-ark status           Install + auth check

Natural language (from fish or arka route):
  harvard ark chat about diabetes
  ask primekg about metformin
  biomedical knowledge graph chat

Requires:
  node, pnpm, git-lfs; bun (or built binary); ANTHROPIC_API_KEY in ~/.config/arka/.env

Override install path:
  HARVARD_ARK_DIR=~/ark-agent-cli arka harvard-ark status
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
