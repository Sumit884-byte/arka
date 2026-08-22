"""Suggest tech stacks by locating a project folder (fuzzy name match) and reading manifests."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

IGNORE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        ".cursor",
        "site-packages",
    }
)

MANIFEST_FILES = (
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "composer.json",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "llm.txt",
    "README.md",
)


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def _similarity(a: str, b: str) -> float:
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return max(SequenceMatcher(None, na, nb).ratio(), 0.82)
    return SequenceMatcher(None, na, nb).ratio()


def _search_roots(extra: list[str] | None = None) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        key = str(resolved)
        if key in seen or not resolved.is_dir():
            return
        seen.add(key)
        roots.append(resolved)

    add(Path.cwd())
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            add(Path((proc.stdout or "").strip()))
    except (OSError, subprocess.SubprocessError):
        pass

    for candidate in (
        Path.home() / "dev",
        Path.home() / "projects",
        Path.home() / "code",
        Path.home() / "src",
        Path.home() / "workspace",
    ):
        add(candidate)

    if extra:
        for item in extra:
            add(Path(item))

    return roots


@dataclass
class FolderMatch:
    path: Path
    folder_name: str
    score: float
    exact: bool
    package_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "folder_name": self.folder_name,
            "score": round(self.score, 3),
            "exact": self.exact,
            "package_name": self.package_name,
        }


def _read_package_name(project_dir: Path) -> str | None:
    pyproject = project_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        match = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', text)
        if match:
            return match.group(1).strip()
    package_json = project_dir / "package.json"
    if package_json.is_file():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _is_project_dir(path: Path) -> bool:
    return any((path / name).is_file() for name in MANIFEST_FILES[:8])


def find_similar_folders(
    query: str,
    *,
    roots: list[Path] | None = None,
    max_depth: int = 2,
    limit: int = 8,
) -> list[FolderMatch]:
    """Search configured roots for directories whose names resemble *query*."""
    target = (query or "").strip()
    if not target:
        return []
    normalized_query = _normalize_name(target)
    matches: list[FolderMatch] = []
    seen_paths: set[str] = set()

    for root in roots or _search_roots():
        candidates: list[Path] = [root]
        if _is_project_dir(root):
            candidates = [root, *root.iterdir()] if root.is_dir() else [root]
        else:
            try:
                candidates = [p for p in root.iterdir() if p.is_dir()]
            except OSError:
                continue

        for candidate in candidates:
            if not candidate.is_dir():
                continue
            if candidate.name in IGNORE_DIRS or any(p in IGNORE_DIRS for p in candidate.parts):
                continue
            rel_depth = len(candidate.relative_to(root).parts) if candidate != root else 0
            if rel_depth > max_depth:
                continue
            key = str(candidate.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)

            folder_score = _similarity(target, candidate.name)
            package_name = _read_package_name(candidate)
            package_score = _similarity(target, package_name) if package_name else 0.0
            score = max(folder_score, package_score)
            if not _is_project_dir(candidate) and score < 0.72:
                continue
            if score < 0.55 and normalized_query not in _normalize_name(candidate.name):
                continue

            exact = (
                _normalize_name(candidate.name) == normalized_query
                or (package_name is not None and _normalize_name(package_name) == normalized_query)
            )
            matches.append(
                FolderMatch(
                    path=candidate,
                    folder_name=candidate.name,
                    score=score,
                    exact=exact,
                    package_name=package_name,
                )
            )

    matches.sort(key=lambda item: (-item.score, -int(item.exact), item.path.as_posix()))
    return matches[:limit]


def _strip_shell_quotes(text: str) -> str:
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1].strip()
    return s


def _is_folder_navigation(text: str) -> bool:
    try:
        from arka.core.to_folder import parse_folder_name
    except ImportError:
        return False
    unquoted = _strip_shell_quotes(text)
    return parse_folder_name(unquoted) is not None or parse_folder_name(text) is not None


def extract_project_name(text: str) -> str | None:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return None
    if _is_folder_navigation(clean):
        return None
    patterns = (
        r"(?i)(?:best|recommended|ideal|good|right|optimal)\s+tech\s+stack(?:s)?\s+(?:for|of)\s+['\"]?([^'\"?\n]+?)['\"]?(?:\?|$|\s+with|\s+using)",
        r"(?i)tech\s+stack(?:s)?\s+(?:for|of)\s+['\"]?([^'\"?\n]+?)['\"]?(?:\?|$|\s+with|\s+using)",
        r"(?i)(?:what|which)\s+(?:is|are)\s+(?:the\s+)?(?:best\s+)?tech\s+stack(?:s)?\s+(?:for|of)\s+['\"]?([^'\"?\n]+?)['\"]?(?:\?|$)",
        r"(?i)(?:stack|stacks)\s+(?:for|of)\s+['\"]?([^'\"?\n]+?)['\"]?(?:\?|$)",
        r"(?i)project\s+['\"]?([^'\"?\n]+?)['\"]?\s+tech\s+stack",
    )
    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            name = match.group(1).strip(" .'\"")
            if name:
                return name
    if re.search(r"(?i)\b(?:tech\s+stack|technology\s+stack|stack\s+for)\b", clean):
        quoted = re.findall(r"""['"]([^'"]+)['"]""", clean)
        if quoted:
            return quoted[0].strip()
    return None


def _read_text(path: Path, max_chars: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _parse_pyproject(text: str) -> dict[str, object]:
    info: dict[str, object] = {"kind": "python"}
    name = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', text)
    if name:
        info["name"] = name.group(1)
    version = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', text)
    if version:
        info["version"] = version.group(1)
    python = re.search(r'(?m)^requires-python\s*=\s*["\']([^"\']+)["\']', text)
    if python:
        info["python"] = python.group(1)
    deps = re.findall(r'^\s*["\']([^"\']+)["\'],?\s*$', text, flags=re.MULTILINE)
    runtime = [d for d in deps if not d.startswith(("dev", "test", "build"))]
    if runtime:
        info["dependencies"] = runtime[:20]
    extras = re.findall(r"\[(project\.optional-dependencies\.([^\]]+))\]", text)
    if extras:
        info["extras"] = sorted({label for _, label in extras})
    return info


def _parse_package_json(text: str) -> dict[str, object]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"kind": "node", "parse_error": True}
    info: dict[str, object] = {"kind": "node", "name": payload.get("name")}
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        if isinstance(payload.get(key), dict):
            deps.update(payload[key])
    if deps:
        info["dependencies"] = sorted(deps.keys())[:24]
    scripts = payload.get("scripts")
    if isinstance(scripts, dict):
        info["scripts"] = sorted(scripts.keys())[:12]
    return info


def read_project_stack(project_dir: Path) -> dict[str, object]:
    """Read manifests under *project_dir* and infer stack signals."""
    root = project_dir.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project folder not found: {root}")

    manifests: dict[str, object] = {}
    notes: list[str] = []

    for filename in MANIFEST_FILES:
        path = root / filename
        if not path.is_file():
            continue
        text = _read_text(path, max_chars=16000 if filename.endswith(".md") else 8000)
        if not text:
            continue
        if filename == "pyproject.toml":
            manifests["pyproject"] = _parse_pyproject(text)
        elif filename == "package.json":
            manifests["package_json"] = _parse_package_json(text)
        elif filename in {"go.mod", "Cargo.toml", "composer.json", "Gemfile"}:
            manifests[filename.replace(".", "_")] = {"kind": filename.split(".")[0], "present": True}
        elif filename.startswith("docker"):
            manifests["docker"] = True
        elif filename == "llm.txt":
            manifests["llm_txt"] = {"chars": len(text), "preview": text[:400]}
        elif filename == "README.md":
            manifests["readme"] = {"chars": len(text), "preview": text[:600]}

    try:
        from arka.agent.workspace import discover

        workspace = discover(root, depth=3)
        if workspace.get("services"):
            manifests["workspace_services"] = workspace["services"][:12]
    except ImportError:
        pass

    languages: list[str] = []
    if "pyproject" in manifests:
        languages.append("Python")
    if "package_json" in manifests:
        languages.append("Node.js")
    if "go_mod" in manifests:
        languages.append("Go")
    if "Cargo_toml" in manifests:
        languages.append("Rust")
    if manifests.get("docker"):
        languages.append("Docker")

    recommendations = _recommend_stack(manifests, languages)
    return {
        "project_dir": str(root),
        "folder_name": root.name,
        "manifests": manifests,
        "languages": languages,
        "recommendations": recommendations,
        "notes": notes,
    }


def _recommend_stack(manifests: dict[str, object], languages: list[str]) -> list[str]:
    recs: list[str] = []
    py = manifests.get("pyproject")
    if isinstance(py, dict):
        python = py.get("python") or ">=3.11"
        recs.append(f"Python {python} with pyproject.toml packaging")
        extras = py.get("extras")
        if isinstance(extras, list) and extras:
            recs.append(f"Optional extras: {', '.join(str(x) for x in extras[:8])}")
        deps = py.get("dependencies")
        if isinstance(deps, list):
            if any("agno" in str(d) or "openai" in str(d) for d in deps):
                recs.append("LLM layer: agno/openai with provider failover")
            if any("Pillow" in str(d) for d in deps):
                recs.append("Media/images: Pillow-based local compositors")
    pkg = manifests.get("package_json")
    if isinstance(pkg, dict):
        deps = pkg.get("dependencies")
        if isinstance(deps, list):
            if "next" in deps:
                recs.append("Frontend: Next.js")
            elif "react" in deps:
                recs.append("Frontend: React")
            if "vite" in deps:
                recs.append("Frontend tooling: Vite")
    services = manifests.get("workspace_services")
    if isinstance(services, list) and services:
        runtimes = sorted({str(item.get("runtime")) for item in services if isinstance(item, dict) and item.get("runtime")})
        if runtimes:
            recs.append(f"Workspace runtimes detected: {', '.join(runtimes)}")
    if not recs and languages:
        recs.append(f"Detected languages: {', '.join(languages)}")
    if not recs:
        recs.append("No strong manifest signals — inspect README and source tree manually")
    return recs


def _prompt_yes_no(message: str, *, default_no: bool = True) -> bool:
    if not sys.stdin.isatty():
        return False
    suffix = "[y/N]" if default_no else "[Y/n]"
    try:
        answer = input(f"{message} {suffix}: ").strip().lower()
    except EOFError:
        return False
    if not answer:
        return not default_no
    return answer in {"y", "yes"}


def resolve_project_folder(
    query: str,
    *,
    roots: list[str] | None = None,
    path: str | None = None,
    assume_yes: bool = False,
    interactive: bool | None = None,
) -> tuple[FolderMatch | None, str | None]:
    """Return chosen match or None; second value is skip/decline reason."""
    if path:
        chosen = Path(path).expanduser().resolve()
        if not chosen.is_dir():
            raise ValueError(f"path is not a directory: {chosen}")
        package_name = _read_package_name(chosen)
        exact = _normalize_name(chosen.name) == _normalize_name(query) or (
            package_name is not None and _normalize_name(package_name) == _normalize_name(query)
        )
        return (
            FolderMatch(
                path=chosen,
                folder_name=chosen.name,
                score=1.0 if exact else 0.9,
                exact=exact,
                package_name=package_name,
            ),
            None,
        )

    root_paths = [Path(r) for r in roots] if roots else None
    matches = find_similar_folders(query, roots=root_paths)
    if not matches:
        return None, f"No folder similar to {query!r} found under search roots"

    best = matches[0]
    if best.exact:
        return best, None

    is_interactive = interactive if interactive is not None else sys.stdin.isatty()
    if assume_yes:
        return best, None
    if not is_interactive:
        return None, (
            f"Best match {best.path} ({best.folder_name}) is not an exact name match for {query!r}; "
            "pass --yes or set path= to confirm"
        )

    hint = best.folder_name
    if best.package_name and _normalize_name(best.package_name) == _normalize_name(query):
        hint = f"{best.folder_name} (package {best.package_name})"
    print(
        f"Found similar folder: {best.path}\n"
        f"  Query: {query!r}\n"
        f"  Match: {hint} (score {best.score:.2f}, not exact folder name)\n"
        f"Other candidates: {', '.join(m.folder_name for m in matches[1:4]) or 'none'}"
    )
    if _prompt_yes_no("Use this folder?"):
        return best, None
    return None, "User declined non-exact folder match"


def suggest_tech_stack(
    query: str,
    *,
    roots: list[str] | None = None,
    path: str | None = None,
    assume_yes: bool = False,
    interactive: bool | None = None,
    include_candidates: bool = False,
) -> dict[str, object]:
    match, skip_reason = resolve_project_folder(
        query,
        roots=roots,
        path=path,
        assume_yes=assume_yes,
        interactive=interactive,
    )
    if match is None:
        payload: dict[str, object] = {
            "query": query,
            "ok": False,
            "reason": skip_reason,
        }
        if include_candidates:
            payload["candidates"] = [m.to_dict() for m in find_similar_folders(query, roots=[Path(r) for r in roots] if roots else None)]
        return payload

    stack = read_project_stack(match.path)
    return {
        "ok": True,
        "query": query,
        "match": match.to_dict(),
        "exact_match": match.exact,
        **stack,
    }


def route_command(text: str) -> str | None:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return None
    if not re.search(r"(?i)\b(?:tech\s+stack|technology\s+stack|stack\s+for)\b", clean):
        return None
    if not re.search(r"(?i)\b(?:best|recommend|what|which|suggest|ideal|good|right|optimal)\b", clean):
        return None
    project = extract_project_name(clean)
    if project:
        return "tech_stack suggest " + shlex.quote(project)
    return "tech_stack suggest " + shlex.quote(clean)


def nl_to_argv(text: str) -> list[str]:
    if _is_folder_navigation(text):
        return []
    project = extract_project_name(text)
    if project:
        return ["suggest", project]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka tech_stack",
        description="Find a similarly named project folder, confirm if not exact, read manifests, suggest stack",
    )
    sub = parser.add_subparsers(dest="cmd")

    suggest_p = sub.add_parser("suggest", help="Search folder, optional y/n confirm, read stack")
    suggest_p.add_argument("project", help="Project name to search for (e.g. arka-agent)")
    suggest_p.add_argument("--path", help="Skip search and use this directory")
    suggest_p.add_argument("--root", action="append", dest="roots", help="Extra search root (repeat)")
    suggest_p.add_argument("--yes", "-y", action="store_true", help="Accept best fuzzy match without prompting")
    suggest_p.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting on fuzzy match")
    suggest_p.add_argument("--json", action="store_true")
    suggest_p.add_argument("--candidates", action="store_true", help="Include candidate folders on failure")

    search_p = sub.add_parser("search", help="List folders similar to a project name")
    search_p.add_argument("project")
    search_p.add_argument("--root", action="append", dest="roots")
    search_p.add_argument("--json", action="store_true")

    parse_p = sub.add_parser("parse", help="Parse NL into argv")
    parse_p.add_argument("text", nargs="+")

    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))

    if args.cmd == "parse":
        argv_out = nl_to_argv(" ".join(args.text))
        print(json.dumps({"argv": argv_out}, indent=2))
        return 0

    if args.cmd == "search":
        matches = find_similar_folders(
            args.project,
            roots=[Path(r) for r in args.roots] if args.roots else None,
        )
        if args.json:
            print(json.dumps([m.to_dict() for m in matches], indent=2))
        else:
            for item in matches:
                exact = "exact" if item.exact else "similar"
                pkg = f" package={item.package_name}" if item.package_name else ""
                print(f"{item.score:.2f}\t{exact}\t{item.path}{pkg}")
        return 0

    if args.cmd == "suggest":
        try:
            result = suggest_tech_stack(
                args.project,
                roots=args.roots,
                path=args.path,
                assume_yes=args.yes,
                interactive=False if args.non_interactive else None,
                include_candidates=args.candidates,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1
        if not result.get("ok"):
            print(result.get("reason") or "No match")
            if result.get("candidates"):
                print("\nCandidates:")
                for item in result["candidates"]:
                    print(f"  - {item['path']} ({item['score']})")
            return 1
        print(f"Project: {result['project_dir']}")
        print(f"Match: {result['match']['folder_name']} ({'exact' if result['exact_match'] else 'similar'})")
        if result.get("languages"):
            print("Languages:", ", ".join(result["languages"]))
        print("\nRecommended stack:")
        for line in result.get("recommendations") or []:
            print(f"  - {line}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
