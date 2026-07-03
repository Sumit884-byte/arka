#!/usr/bin/env python3
"""Third-party skill registry for Arka — discover, install, route, and run plugins."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from arka.paths import cache_dir, config_dir, load_env_file, arka_home

    load_env_file()
except ImportError:
    def config_dir() -> Path:
        if env := os.environ.get("ARKA_CONFIG_DIR", "").strip():
            return Path(env).expanduser()
        legacy = Path.home() / ".config" / "fish"
        return legacy if (legacy / ".env").is_file() else Path.home() / ".config" / "arka"

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def arka_home() -> Path:
        if env := os.environ.get("ARKA_HOME", "").strip():
            return Path(env).expanduser()
        return Path(__file__).resolve().parent

REGISTRY_FILE = cache_dir() / "third_party_skills.json"
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")


def skills_search_paths() -> list[Path]:
    paths: list[Path] = []
    for raw in (os.environ.get("ARKA_SKILLS_PATH") or "").split(os.pathsep):
        raw = raw.strip()
        if raw:
            paths.append(Path(raw).expanduser())
    paths.extend(
        [
            config_dir() / "skills",
            arka_home() / "skills",
            Path.home() / ".local" / "share" / "arka" / "skills",
        ]
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _skill_from_manifest(manifest_path: Path) -> dict[str, Any] | None:
    data = _read_json(manifest_path)
    name = (data.get("name") or manifest_path.parent.name).strip()
    if not SKILL_NAME_RE.match(name):
        return None
    root = manifest_path.parent
    skill_type = (data.get("type") or "python").strip().lower()
    entry = (data.get("entry") or "").strip()
    if not entry:
        for candidate in ("run.py", "main.py", "skill.py", f"{name}.fish", "run.sh"):
            if (root / candidate).is_file():
                entry = candidate
                break
    triggers = data.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    triggers = [str(t).strip().lower() for t in triggers if str(t).strip()]
    if name not in [t.split()[0] for t in triggers if t]:
        triggers.insert(0, name.replace("_", " "))
    return {
        "name": name,
        "description": (data.get("description") or "").strip(),
        "version": (data.get("version") or "0.1.0").strip(),
        "author": (data.get("author") or "").strip(),
        "type": skill_type,
        "entry": entry,
        "triggers": triggers,
        "enabled": data.get("enabled", True) is not False,
        "voice_ack": (data.get("voice_ack") or "").strip(),
        "root": str(root),
        "manifest": str(manifest_path),
    }


def _skill_from_fish(fish_path: Path) -> dict[str, Any] | None:
    name = fish_path.stem
    if not SKILL_NAME_RE.match(name):
        return None
    desc = ""
    for line in fish_path.read_text(encoding="utf-8", errors="replace").splitlines()[:20]:
        m = re.search(r'--description\s+"([^"]+)"', line)
        if m:
            desc = m.group(1).strip()
            break
    return {
        "name": name,
        "description": desc or f"Fish skill from {fish_path.name}",
        "version": "0.0.0",
        "author": "",
        "type": "fish",
        "entry": fish_path.name,
        "triggers": [name.replace("_", " ")],
        "enabled": True,
        "voice_ack": "",
        "root": str(fish_path.parent),
        "manifest": str(fish_path),
    }


def discover_skills(*, refresh: bool = False) -> list[dict[str, Any]]:
    if not refresh and REGISTRY_FILE.is_file():
        try:
            cached = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("skills"):
                age = time.time() - REGISTRY_FILE.stat().st_mtime
                if age < 30:
                    return cached["skills"]
        except (OSError, json.JSONDecodeError):
            pass

    by_name: dict[str, dict[str, Any]] = {}
    for base in skills_search_paths():
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                if child.suffix == ".fish" and child.is_file():
                    sk = _skill_from_fish(child)
                    if sk:
                        by_name[sk["name"]] = sk
                continue
            for manifest_name in ("skill.json", "manifest.json", "plugin.json"):
                manifest = child / manifest_name
                if manifest.is_file():
                    sk = _skill_from_manifest(manifest)
                    if sk:
                        by_name[sk["name"]] = sk
                    break
            else:
                fish_file = child / f"{child.name}.fish"
                if fish_file.is_file():
                    sk = _skill_from_fish(fish_file)
                    if sk:
                        by_name[sk["name"]] = sk

    skills = sorted(by_name.values(), key=lambda s: s["name"])
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps({"updated": time.time(), "skills": skills}, indent=2),
        encoding="utf-8",
    )
    return skills


def list_names(*, enabled_only: bool = True) -> list[str]:
    skills = discover_skills()
    if enabled_only:
        skills = [s for s in skills if s.get("enabled")]
    return [s["name"] for s in skills]


def get_skill(name: str) -> dict[str, Any] | None:
    for sk in discover_skills():
        if sk["name"] == name:
            return sk
    return None


def fish_sources() -> list[str]:
    paths: list[str] = []
    for sk in discover_skills():
        if not sk.get("enabled") or sk.get("type") != "fish":
            continue
        root = Path(sk["root"])
        entry = sk.get("entry") or ""
        fish_path = root / entry if entry else root / f"{sk['name']}.fish"
        if fish_path.is_file():
            paths.append(str(fish_path))
    return paths


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def match_command(text: str) -> str:
    """Return skill invocation line e.g. 'habit_tracker log water' or ''."""
    raw = (text or "").strip()
    if not raw:
        return ""
    low = _normalize(raw)

    skills = [s for s in discover_skills() if s.get("enabled")]
    skills.sort(key=lambda s: max((len(t) for t in s.get("triggers") or [""]), default=0), reverse=True)

    for sk in skills:
        name = sk["name"]
        if low == name or low.startswith(f"{name} "):
            rest = raw[len(name) :].strip()
            return f"{name} {rest}".strip()

    for sk in skills:
        name = sk["name"]
        for trigger in sk.get("triggers") or []:
            trig = _normalize(trigger)
            if not trig:
                continue
            if low == trig:
                return name
            if low.startswith(trig + " "):
                rest = raw[len(trigger) :].strip() if len(raw) >= len(trigger) else ""
                # re-extract after trigger length in original case-insensitive way
                idx = low.find(trig)
                if idx >= 0:
                    rest = raw[idx + len(trigger) :].strip()
                return f"{name} {rest}".strip() if rest else name
            if trig in low and len(trig) >= 4:
                idx = low.find(trig)
                rest = raw[idx + len(trig) :].strip(" ,:-")
                return f"{name} {rest}".strip() if rest else name
    return ""


def voice_ack_for(text: str) -> str:
    line = match_command(text)
    if not line:
        return ""
    name = line.split()[0]
    sk = get_skill(name)
    if sk and sk.get("voice_ack"):
        return sk["voice_ack"]
    if sk and sk.get("description"):
        return f"Running {sk['description']}."
    return "Running your plugin."


def _py() -> str:
    venv = Path.home() / ".config" / "fish" / "venv-arka" / "bin" / "python3"
    if venv.is_file():
        return str(venv)
    return sys.executable


def run_skill(name: str, args: list[str]) -> int:
    sk = get_skill(name)
    if not sk or not sk.get("enabled"):
        print(f"Unknown or disabled third-party skill: {name}", file=sys.stderr)
        return 1

    root = Path(sk["root"])
    entry = sk.get("entry") or ""
    skill_type = sk.get("type") or "python"
    arg_str = " ".join(args)

    if skill_type == "fish":
        fish_path = root / entry if entry else root / f"{name}.fish"
        if not fish_path.is_file():
            print(f"Missing fish skill file: {fish_path}", file=sys.stderr)
            return 1
        cmd = f'source {fish_path}; {name} {arg_str}'.strip()
        return subprocess.run(["fish", "-c", cmd], env=os.environ.copy()).returncode

    if skill_type == "python":
        script = root / (entry or "run.py")
        if not script.is_file():
            print(f"Missing python entry: {script}", file=sys.stderr)
            return 1
        return subprocess.run([_py(), str(script), *args], cwd=str(root), env=os.environ.copy()).returncode

    if skill_type in ("shell", "bash"):
        script = root / (entry or "run.sh")
        if not script.is_file():
            print(f"Missing shell entry: {script}", file=sys.stderr)
            return 1
        return subprocess.run(["bash", str(script), *args], cwd=str(root), env=os.environ.copy()).returncode

    if skill_type == "command":
        template = entry or sk.get("command") or ""
        if not template:
            print(f"Skill {name} has type command but no entry template", file=sys.stderr)
            return 1
        cmd = template.replace("{args}", arg_str).replace("{name}", name)
        return subprocess.run(cmd, shell=True, cwd=str(root), env=os.environ.copy()).returncode

    print(f"Unsupported skill type: {skill_type}", file=sys.stderr)
    return 1


def install_skill(source: str) -> int:
    """Install from git URL or local directory into ~/.config/arka/skills/."""
    dest_root = config_dir() / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)

    src = source.strip()
    if not src:
        print("Usage: arka skills install <git-url|path>", file=sys.stderr)
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
        install_name = name
    else:
        src_path = Path(src).expanduser().resolve()
        if not src_path.is_dir():
            print(f"Not a directory: {src_path}", file=sys.stderr)
            return 1
        manifest = None
        for m in ("skill.json", "manifest.json", "plugin.json"):
            if (src_path / m).is_file():
                manifest = src_path / m
                break
        install_name = src_path.name
        if manifest:
            install_name = (_read_json(manifest).get("name") or install_name).strip()
        if not SKILL_NAME_RE.match(install_name):
            print(f"Invalid skill name: {install_name}", file=sys.stderr)
            return 1
        target = dest_root / install_name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src_path, target)
        print(f"Installed → {target}")

    discover_skills(refresh=True)
    sk = get_skill(install_name)
    if sk:
        print(f"✓ Skill '{sk['name']}' ready — try: arka {sk['name']}")
        if sk.get("triggers"):
            print(f"  Triggers: {', '.join(sk['triggers'][:5])}")
    return 0


def print_list(*, verbose: bool = False) -> None:
    skills = discover_skills(refresh=True)
    if not skills:
        print("No third-party skills installed.")
        print(f"  Install dir: {config_dir() / 'skills'}")
        print("  Try: arka skills install /path/to/skill  or  arka skills install <git-url>")
        return
    print(f"Third-party skills ({len(skills)}):")
    for sk in skills:
        flag = "on " if sk.get("enabled") else "off"
        line = f"  [{flag}] {sk['name']} v{sk.get('version', '?')}"
        if sk.get("description"):
            line += f" — {sk['description']}"
        print(line)
        if verbose:
            print(f"       type={sk.get('type')} root={sk.get('root')}")
            if sk.get("triggers"):
                print(f"       triggers: {', '.join(sk['triggers'][:8])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka third-party skills")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list")

    p_names = sub.add_parser("list-names")
    p_names.add_argument("--all", action="store_true")

    sub.add_parser("refresh")
    sub.add_parser("fish-sources")

    p_match = sub.add_parser("match")
    p_match.add_argument("text")

    p_ack = sub.add_parser("voice-ack")
    p_ack.add_argument("text")

    p_run = sub.add_parser("run")
    p_run.add_argument("name")
    p_run.add_argument("args", nargs="*")

    p_install = sub.add_parser("install")
    p_install.add_argument("source")

    p_info = sub.add_parser("info")
    p_info.add_argument("name")

    args = parser.parse_args()
    if args.cmd == "list":
        print_list(verbose=True)
        return 0
    if args.cmd == "list-names":
        for n in list_names(enabled_only=not args.all):
            print(n)
        return 0
    if args.cmd == "refresh":
        discover_skills(refresh=True)
        print("Skill registry refreshed.")
        return 0
    if args.cmd == "fish-sources":
        for p in fish_sources():
            print(p)
        return 0
    if args.cmd == "match":
        out = match_command(args.text)
        if out:
            print(out)
        return 0
    if args.cmd == "voice-ack":
        print(voice_ack_for(args.text))
        return 0
    if args.cmd == "run":
        return run_skill(args.name, args.args)
    if args.cmd == "install":
        return install_skill(args.source)
    if args.cmd == "info":
        sk = get_skill(args.name)
        if not sk:
            print(f"Skill not found: {args.name}", file=sys.stderr)
            return 1
        print(json.dumps(sk, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
