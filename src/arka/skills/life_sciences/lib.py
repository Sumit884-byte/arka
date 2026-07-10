"""Anthropic life-sciences marketplace adapter for Arka."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

MARKETPLACE_REPO = "https://github.com/anthropics/life-sciences.git"
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")

# Workflow skills with runnable entry scripts (relative to skill root).
WORKFLOW_ENTRIES: dict[str, str] = {
    "single-cell-rna-qc": "scripts/qc_analysis.py",
    "instrument-data-to-allotrope": "scripts/convert_to_asm.py",
}

# Extra natural-language triggers per installed plugin.
PLUGIN_TRIGGERS: dict[str, list[str]] = {
    "pubmed": ["pubmed", "search pubmed", "biomedical literature", "biomedical papers"],
    "single-cell-rna-qc": [
        "single cell rna",
        "scrna qc",
        "single-cell qc",
        "rna-seq qc",
        "quality control scrna",
    ],
    "nextflow-development": ["nextflow", "nf-core", "rnaseq pipeline", "run rnaseq"],
    "scvi-tools": ["scvi", "scvi-tools", "single cell integration"],
    "scientific-problem-selection": [
        "research problem selection",
        "scientific problem selection",
        "pitch research idea",
        "stuck on research",
    ],
    "clinical-trial-protocol": ["clinical trial protocol", "fda protocol", "trial protocol"],
    "clinical-trials": ["clinical trials", "clinicaltrials.gov"],
    "biorxiv": ["biorxiv", "medrxiv", "preprint"],
    "chembl": ["chembl", "bioactive molecules"],
    "open-targets": ["open targets", "drug target"],
}


def _skill_root() -> Path:
    return Path(__file__).resolve().parent


def _marketplace_path() -> Path:
    return _skill_root() / "marketplace.json"


def _repo_cache_dir() -> Path:
    try:
        from arka.paths import cache_dir

        root = cache_dir() / "life-sciences"
    except ImportError:
        root = Path.home() / ".cache" / "arka" / "life-sciences"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _install_root() -> Path:
    try:
        from arka.paths import config_dir

        root = config_dir() / "skills"
    except ImportError:
        root = Path.home() / ".config" / "arka" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_marketplace() -> dict[str, Any]:
    data = json.loads(_marketplace_path().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid marketplace.json")
    plugins = data.get("plugins") or []
    if not isinstance(plugins, list):
        raise ValueError("marketplace plugins must be a list")
    return data


def list_plugins() -> list[dict[str, Any]]:
    data = load_marketplace()
    plugins: list[dict[str, Any]] = []
    for row in data.get("plugins") or []:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        kind = (row.get("kind") or _infer_kind(row)).strip().lower()
        plugins.append({**row, "kind": kind})
    return sorted(plugins, key=lambda p: p["name"])


def get_plugin(name: str) -> dict[str, Any] | None:
    key = name.strip().lower()
    for plugin in list_plugins():
        if plugin["name"].lower() == key:
            return plugin
    return None


def _infer_kind(row: dict[str, Any]) -> str:
    if row.get("skills"):
        source = (row.get("source") or "").strip()
        if source in (".", "./"):
            return "guidance"
        return "workflow"
    source = (row.get("source") or "").strip()
    if source and not source.endswith(".claude-plugin"):
        if (Path(source).name or source).replace("./", "") in WORKFLOW_ENTRIES:
            return "workflow"
    return "mcp"


def _normalize_skill_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "-", name.strip().lower()).strip("-")


def parse_skill_md_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end].strip()
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def ensure_repo_clone(*, refresh: bool = False) -> Path:
    target = _repo_cache_dir() / "repo"
    if refresh and target.exists():
        shutil.rmtree(target)
    if target.is_dir() and (target / ".git").is_dir():
        return target
    if target.exists():
        shutil.rmtree(target)
    print(f"Cloning {MARKETPLACE_REPO} → {target}", file=sys.stderr)
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", MARKETPLACE_REPO, str(target)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git clone failed")
    return target


def _plugin_source_dir(repo: Path, plugin: dict[str, Any]) -> Path | None:
    source = (plugin.get("source") or "").strip().lstrip("./")
    if not source:
        return None
    if plugin.get("skills"):
        skill_paths = plugin.get("skills") or []
        if skill_paths:
            rel = str(skill_paths[0]).strip().lstrip("./")
            path = repo / rel
            return path if path.is_dir() else None
    path = repo / source
    if path.is_dir():
        if (path / "SKILL.md").is_file():
            return path
        return path
    return None


def _skill_dir_for_plugin(repo: Path, plugin: dict[str, Any]) -> Path | None:
    name = plugin["name"]
    direct = repo / name
    if direct.is_dir() and (direct / "SKILL.md").is_file():
        return direct
    source = (plugin.get("source") or "").strip().lstrip("./")
    if source:
        candidate = repo / source
        if candidate.is_dir() and (candidate / "SKILL.md").is_file():
            return candidate
    if plugin.get("skills"):
        for rel in plugin.get("skills") or []:
            candidate = repo / str(rel).strip().lstrip("./")
            if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                return candidate
    return None


def _build_triggers(plugin: dict[str, Any], skill_name: str) -> list[str]:
    triggers = list(PLUGIN_TRIGGERS.get(plugin["name"], []))
    name_words = skill_name.replace("_", " ")
    if name_words not in triggers:
        triggers.insert(0, name_words)
    if skill_name not in triggers:
        triggers.append(skill_name)
    desc = (plugin.get("description") or "").lower()
    if "pubmed" in plugin["name"]:
        triggers.extend(["search pubmed for", "find papers on"])
    if "single-cell" in plugin["name"] or "single cell" in desc:
        triggers.append("quality control on scrna")
    return list(dict.fromkeys(t.strip().lower() for t in triggers if t.strip()))


def _workflow_entry(skill_dir: Path, plugin_name: str) -> str | None:
    rel = WORKFLOW_ENTRIES.get(plugin_name)
    if rel and (skill_dir / rel).is_file():
        return rel
    scripts = skill_dir / "scripts"
    if not scripts.is_dir():
        return None
    for candidate in ("qc_analysis.py", "convert_to_asm.py", "main.py", "run.py"):
        if (scripts / candidate).is_file():
            return f"scripts/{candidate}"
    py_files = sorted(scripts.glob("*.py"))
    if len(py_files) == 1:
        return str(py_files[0].relative_to(skill_dir))
    return None


def _render_run_py(*, plugin: dict[str, Any], skill_name: str, kind: str, entry: str | None) -> str:
    description = (plugin.get("description") or skill_name).replace('"', "'")
    if kind == "workflow" and entry:
        return textwrap.dedent(
            f'''\
            #!/usr/bin/env python3
            """Arka adapter for {skill_name} (anthropics/life-sciences)."""
            from __future__ import annotations

            import subprocess
            import sys
            from pathlib import Path

            ROOT = Path(__file__).resolve().parent
            WORKFLOW = ROOT / "{entry}"


            def main() -> int:
                if not WORKFLOW.is_file():
                    print(f"Missing workflow script: {{WORKFLOW}}", file=sys.stderr)
                    return 1
                if not sys.argv[1:]:
                    print("{description}")
                    print(f"Usage: arka {skill_name} <input-file> [workflow-args]")
                    return 0
                return subprocess.run([sys.executable, str(WORKFLOW), *sys.argv[1:]], cwd=str(ROOT)).returncode


            if __name__ == "__main__":
                raise SystemExit(main())
            '''
        )
    if kind == "guidance":
        return textwrap.dedent(
            f'''\
            #!/usr/bin/env python3
            """Arka adapter for {skill_name} (anthropics/life-sciences)."""
            from __future__ import annotations

            import sys
            from pathlib import Path

            ROOT = Path(__file__).resolve().parent
            SKILL_MD = ROOT / "SKILL.md"


            def _load_skill_text() -> str:
                if SKILL_MD.is_file():
                    return SKILL_MD.read_text(encoding="utf-8", errors="replace")
                return "{description}"


            def main() -> int:
                question = " ".join(sys.argv[1:]).strip()
                if not question:
                    print("{description}")
                    print(f"Usage: arka {skill_name} <question or research topic>")
                    return 0
                skill_text = _load_skill_text()
                try:
                    from arka.llm.cli import llm_complete
                except ImportError:
                    print(skill_text[:4000])
                    print("\\n(LLM unavailable — showing SKILL.md excerpt.)", file=sys.stderr)
                    return 0
                system = (
                    "Follow the life-sciences skill workflow below. "
                    "Write plain terminal text (no markdown). Be structured and practical.\\n\\n"
                    + skill_text[:12000]
                )
                answer = llm_complete(system, question, temperature=0.3, task="default")
                print(answer.strip() or "No answer returned.")
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
            '''
        )
    if plugin["name"] == "pubmed":
        return textwrap.dedent(
            '''\
            #!/usr/bin/env python3
            """PubMed search via NCBI E-utilities (Arka fallback for life-sciences MCP)."""
            from __future__ import annotations

            import sys
            import urllib.error
            import urllib.parse
            import urllib.request
            import xml.etree.ElementTree as ET


            def _search_pubmed(query: str, *, retmax: int = 8) -> list[dict[str, str]]:
                params = urllib.parse.urlencode(
                    {"db": "pubmed", "term": query, "retmax": retmax, "retmode": "json"}
                )
                url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}"
                with urllib.request.urlopen(url, timeout=20) as resp:
                    import json

                    data = json.loads(resp.read().decode("utf-8"))
                ids = data.get("esearchresult", {}).get("idlist") or []
                if not ids:
                    return []
                summary_params = urllib.parse.urlencode(
                    {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
                )
                summary_url = (
                    f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{summary_params}"
                )
                with urllib.request.urlopen(summary_url, timeout=20) as resp:
                    root = ET.fromstring(resp.read())
                rows: list[dict[str, str]] = []
                for doc in root.findall(".//DocSum"):
                    uid = (doc.findtext("Id") or "").strip()
                    title = ""
                    journal = ""
                    year = ""
                    for item in doc.findall("Item"):
                        name = item.attrib.get("Name", "")
                        if name == "Title":
                            title = (item.text or "").strip()
                        elif name == "FullJournalName":
                            journal = (item.text or "").strip()
                        elif name == "PubDate":
                            year = (item.text or "").strip()[:4]
                    if uid and title:
                        rows.append(
                            {
                                "pmid": uid,
                                "title": title,
                                "journal": journal,
                                "year": year,
                                "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                            }
                        )
                return rows


            def main() -> int:
                query = " ".join(sys.argv[1:]).strip()
                if not query:
                    print("Search PubMed biomedical literature.")
                    print("Usage: arka pubmed <search query>")
                    return 0
                try:
                    hits = _search_pubmed(query)
                except (urllib.error.URLError, TimeoutError, ET.ParseError) as exc:
                    print(f"PubMed search failed: {exc}", file=sys.stderr)
                    return 1
                if not hits:
                    print(f"No PubMed results for: {query}")
                    return 0
                print(f"PubMed results for: {query}\\n")
                for i, row in enumerate(hits, 1):
                    meta = ", ".join(x for x in (row["journal"], row["year"]) if x)
                    suffix = f" ({meta})" if meta else ""
                    print(f"{i}. {row['title']}{suffix}")
                    print(f"   {row['url']}")
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
            '''
        )
    return textwrap.dedent(
        f'''\
        #!/usr/bin/env python3
        """Arka adapter for {skill_name} (anthropics/life-sciences MCP plugin)."""
        from __future__ import annotations

        import sys


        def main() -> int:
            args = " ".join(sys.argv[1:]).strip()
            print("{description}")
            print("This plugin is an MCP server in Claude Code. Arka provides a local stub.")
            print("Install credentials in Claude Code, or use: arka profession ask life_sciences <question>")
            if args:
                print(f"\\nYou asked: {{args}}")
            print("\\nTry: arka life_sciences info {plugin["name"]}")
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    )


def _write_skill_manifest(
    *,
    target: Path,
    plugin: dict[str, Any],
    skill_name: str,
    kind: str,
    entry_script: str,
) -> None:
    triggers = _build_triggers(plugin, skill_name)
    manifest = {
        "name": skill_name,
        "description": (plugin.get("description") or skill_name)[:240],
        "version": "1.0.0",
        "author": "Anthropic (life-sciences marketplace)",
        "type": "python",
        "entry": entry_script,
        "triggers": triggers,
        "voice_ack": f"Running {plugin['name'].replace('-', ' ')}.",
        "metadata": {
            "arka": {
                "marketplace": "anthropics/life-sciences",
                "plugin": plugin["name"],
                "kind": kind,
            }
        },
    }
    if kind == "workflow":
        manifest["requires"] = {"bins": ["python3"]}
        manifest["permissions"] = ["shell"]
    if plugin["name"] == "nextflow-development":
        manifest["requires"] = {"anyBins": ["nextflow", "docker"]}
    if plugin["name"] == "pubmed":
        manifest["permissions"] = ["network"]
    (target / "skill.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def install_plugin(name: str, *, refresh_repo: bool = False) -> int:
    plugin = get_plugin(name)
    if not plugin:
        print(f"Unknown life-sciences plugin: {name}", file=sys.stderr)
        print("Try: arka life_sciences list", file=sys.stderr)
        return 1

    skill_name = _normalize_skill_name(plugin["name"])
    if not SKILL_NAME_RE.match(skill_name):
        print(f"Invalid Arka skill name for plugin: {plugin['name']}", file=sys.stderr)
        return 1

    kind = plugin.get("kind") or _infer_kind(plugin)
    target = _install_root() / skill_name
    if target.exists():
        shutil.rmtree(target)

    repo = ensure_repo_clone(refresh=refresh_repo)
    skill_dir = _skill_dir_for_plugin(repo, plugin)

    if skill_dir and skill_dir.is_dir():
        shutil.copytree(skill_dir, target)
        workflow_entry = _workflow_entry(target, plugin["name"]) if kind == "workflow" else None
        if kind == "workflow" and not workflow_entry:
            kind = "guidance"
    else:
        target.mkdir(parents=True, exist_ok=True)
        workflow_entry = None
        readme = (
            f"# {plugin['name']}\n\n"
            f"{plugin.get('description', '')}\n\n"
            "MCP plugin from anthropics/life-sciences. Configure in Claude Code for full access.\n"
        )
        (target / "README.md").write_text(readme, encoding="utf-8")

    entry_name = "run.py"
    run_py = _render_run_py(
        plugin=plugin,
        skill_name=skill_name,
        kind=kind,
        entry=workflow_entry,
    )
    (target / entry_name).write_text(run_py, encoding="utf-8")
    _write_skill_manifest(
        target=target,
        plugin=plugin,
        skill_name=skill_name,
        kind=kind,
        entry_script=entry_name,
    )

    try:
        from arka.agent.skills import discover_skills

        discover_skills(refresh=True)
    except ImportError:
        pass

    print(f"✓ Installed life-sciences plugin '{plugin['name']}' as arka skill '{skill_name}'")
    print(f"  Path: {target}")
    print(f"  Kind: {kind}")
    if kind == "mcp" and plugin["name"] != "pubmed":
        print("  Note: full MCP access requires Claude Code; Arka installed a local stub.")
    print(f"  Try: arka {skill_name}")
    return 0


def print_plugin_list() -> None:
    plugins = list_plugins()
    if not plugins:
        print("No plugins in marketplace.")
        return
    print(f"Anthropic life-sciences marketplace ({len(plugins)} plugins)\n")
    for plugin in plugins:
        kind = plugin.get("kind", "mcp")
        print(f"  {plugin['name']:<28} [{kind:<8}] {plugin.get('description', '')[:70]}")
    print("\nInstall: arka life_sciences install <name>")
    print("Example: arka life_sciences install pubmed")


def print_plugin_info(name: str) -> int:
    plugin = get_plugin(name)
    if not plugin:
        print(f"Unknown plugin: {name}", file=sys.stderr)
        return 1
    print(f"Plugin: {plugin['name']}")
    print(f"Kind:   {plugin.get('kind', 'mcp')}")
    print(f"About:  {plugin.get('description', '')}")
    tags = plugin.get("tags") or []
    if tags:
        print(f"Tags:   {', '.join(tags)}")
    skill_name = _normalize_skill_name(plugin["name"])
    installed = (_install_root() / skill_name / "skill.json").is_file()
    print(f"Status: {'installed' if installed else 'not installed'}")
    if plugin.get("kind") == "mcp" and plugin["name"] != "pubmed":
        print("MCP:    Requires Claude Code plugin system for remote MCP servers.")
        print("        Arka installs a stub; use pubmed for a working local search.")
    return 0


def doctor() -> int:
    repo = _repo_cache_dir() / "repo"
    plugins = list_plugins()
    installed = 0
    for plugin in plugins:
        skill_name = _normalize_skill_name(plugin["name"])
        if (_install_root() / skill_name / "skill.json").is_file():
            installed += 1
    print("Life sciences integration")
    print(f"  Marketplace plugins: {len(plugins)}")
    print(f"  Installed skills:    {installed}")
    print(f"  Repo cache:          {repo} ({'ok' if repo.is_dir() else 'missing'})")
    print(f"  Skills dir:          {_install_root()}")
    print("\nQuick start:")
    print("  arka life_sciences install pubmed")
    print("  arka pubmed crispr gene editing")
    print("  arka profession ask life_sciences <research question>")
    return 0
