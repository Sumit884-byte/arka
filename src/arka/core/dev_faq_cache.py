"""Cache for commonly asked developer questions — instant answers, no LLM."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

try:
    from arka.core.answer_cache import normalize_cache_key
    from arka.paths import config_dir
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def normalize_cache_key(query: str) -> str:
        q = re.sub(r"\s+", " ", (query or "").strip().casefold())
        return q.rstrip("?.")


BUILTIN_DEV_FAQ: dict[str, str] = {
    "what is git": (
        "Git is a distributed version control system. It tracks file changes over time, "
        "supports branches for parallel work, and lets teams merge code via commits. "
        "Common commands: `git clone`, `git status`, `git add`, `git commit`, `git push`, `git pull`."
    ),
    "what is github": (
        "GitHub is a hosting platform for Git repositories. It adds pull requests, code review, "
        "Issues, Actions (CI/CD), and collaboration features on top of plain Git."
    ),
    "what is a pull request": (
        "A pull request (PR) proposes merging a branch into another (usually `main`). "
        "Teammates review the diff, run CI checks, discuss changes, then merge or close it."
    ),
    "what is docker": (
        "Docker packages an app and its dependencies into an image, then runs it in an isolated container. "
        "Same image runs on laptop, CI, and production. Key pieces: Dockerfile, image, container, registry."
    ),
    "what is kubernetes": (
        "Kubernetes (K8s) orchestrates containers across a cluster — scheduling, scaling, "
        "self-healing, load balancing, and rolling updates. Docker runs one container; K8s runs many."
    ),
    "what is ci cd": (
        "CI/CD automates building, testing, and deploying code. "
        "CI (Continuous Integration) runs tests on every push; "
        "CD (Continuous Delivery/Deployment) ships passing builds to staging or production."
    ),
    "what is rest api": (
        "A REST API exposes resources over HTTP using standard verbs: "
        "GET (read), POST (create), PUT/PATCH (update), DELETE (remove). "
        "Responses are usually JSON; URLs represent resources (`/users/42`)."
    ),
    "what is npm": (
        "npm is Node.js's package manager and registry. `npm install` adds dependencies; "
        "`package.json` lists them; `npm run <script>` runs project scripts."
    ),
    "what is pip": (
        "pip installs Python packages from PyPI. Use a virtual environment first: "
        "`python -m venv .venv && source .venv/bin/activate`, then `pip install <package>`."
    ),
    "what is python venv": (
        "A venv is an isolated Python environment with its own packages. "
        "Create: `python3 -m venv .venv`. Activate: `source .venv/bin/activate` (macOS/Linux) "
        "or `.venv\\Scripts\\activate` (Windows). Deactivate: `deactivate`."
    ),
    "how to create a python virtual environment": (
        "From your project folder:\n"
        "```bash\npython3 -m venv .venv\nsource .venv/bin/activate   # macOS/Linux\n"
        "pip install -r requirements.txt\n```\n"
        "Use `.venv` in `.gitignore`; commit `requirements.txt`, not the venv folder."
    ),
    "how to undo last git commit": (
        "Keep changes, undo commit only: `git reset --soft HEAD~1`\n"
        "Discard commit and staged changes: `git reset --hard HEAD~1` (destructive)\n"
        "Already pushed? Prefer `git revert HEAD` — adds a new commit that undoes the last one."
    ),
    "git merge vs rebase": (
        "**Merge** preserves branch history with a merge commit — safe for shared branches.\n"
        "**Rebase** replays your commits on top of another branch — linear history; "
        "avoid rebasing commits already pushed that others may have pulled."
    ),
    "what is the difference between git merge and rebase": (
        "**Merge** preserves branch history with a merge commit — safe for shared branches.\n"
        "**Rebase** replays your commits on top of another branch — linear history; "
        "avoid rebasing commits already pushed that others may have pulled."
    ),
    "what is an environment variable": (
        "Environment variables are key/value pairs passed to processes (e.g. `API_KEY=secret`). "
        "Shell: `export VAR=value`. Python: `os.environ.get('VAR')`. "
        "Never commit secrets — use `.env` locally and platform secrets in production."
    ),
    "what is mcp": (
        "MCP (Model Context Protocol) lets AI clients call tools on local or remote servers — "
        "filesystem, databases, APIs — through a standard JSON-RPC interface. "
        "Arka exposes MCP tools via `arka mcp serve`."
    ),
    "what is linting": (
        "Linting statically analyzes code for bugs, style issues, and anti-patterns before runtime. "
        "Examples: ESLint (JS), Ruff/Flake8 (Python), Clippy (Rust). "
        "Run in CI to keep main green."
    ),
    "what is typescript": (
        "TypeScript is JavaScript plus optional static types. It compiles to JS, catches errors at "
        "build time, and improves IDE autocomplete. Common in React/Node backends."
    ),
    "what is json": (
        "JSON (JavaScript Object Notation) is a text format for structured data: "
        "objects `{}`, arrays `[]`, strings, numbers, booleans, null. "
        "Standard for REST APIs and config files."
    ),
}

_DEV_FAQ_ALIASES: dict[str, str] = {
    "what's git": "what is git",
    "whats git": "what is git",
    "how do i create a venv": "how to create a python virtual environment",
    "how to make a venv": "how to create a python virtual environment",
    "what is ci/cd": "what is ci cd",
    "what is cicd": "what is ci cd",
    "what is a pr": "what is a pull request",
    "what is pr in github": "what is a pull request",
    "merge vs rebase": "git merge vs rebase",
    "git rebase vs merge": "git merge vs rebase",
}

_DEV_QUERY_RE = re.compile(
    r"(?i)\b("
    r"what\s+is\s+(?:git|github|docker|kubernetes|k8s|npm|pip|venv|python|typescript|json|mcp|rest|"
    r"ci/?cd|lint(?:ing)?|a\s+pull\s+request|pr)|"
    r"how\s+(?:do\s+i|to)\s+(?:create|make|undo|install|use).{0,40}|"
    r"(?:git\s+)?merge\s+vs\s+rebase|"
    r"difference\s+between\s+git\s+merge\s+and\s+rebase|"
    r"what\s+(?:is|are)\s+(?:an?\s+)?environment\s+variable"
    r")\b"
)


def dev_faq_cache_path() -> Path:
    return config_dir() / "dev_faq_cache.json"


def dev_faq_cache_enabled() -> bool:
    return os.environ.get("ARKA_DEV_FAQ_CACHE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def dev_faq_cache_ttl() -> float:
    raw = os.environ.get("ARKA_DEV_FAQ_CACHE_TTL", "604800").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 604800.0


def _canonical_key(query: str) -> str:
    key = normalize_cache_key(query)
    return _DEV_FAQ_ALIASES.get(key, key)


def is_dev_faq_query(query: str) -> bool:
    q = normalize_cache_key(query)
    if not q or len(q.split()) > 18:
        return False
    if q in BUILTIN_DEV_FAQ or q in _DEV_FAQ_ALIASES:
        return True
    if _canonical_key(q) in BUILTIN_DEV_FAQ:
        return True
    return bool(_DEV_QUERY_RE.search(q))


def should_use_dev_cache(user_text: str, *, prebuilt: bool = False) -> bool:
    if prebuilt or not dev_faq_cache_enabled():
        return False
    text = (user_text or "").strip()
    if not text:
        return False
    try:
        from arka.core.chat_context_gate import needs_past_chat_heuristic

        if needs_past_chat_heuristic(text):
            return False
    except ImportError:
        pass
    return is_dev_faq_query(text) or lookup_dev_faq(text) is not None


def _load_store() -> dict[str, Any]:
    path = dev_faq_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            entries = data.get("entries")
            if isinstance(entries, dict):
                return {"version": 1, "entries": entries}
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "entries": {}}


def _save_store(store: dict[str, Any]) -> None:
    path = dev_faq_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def lookup_dev_faq(query: str) -> str | None:
    if not dev_faq_cache_enabled():
        return None
    key = _canonical_key(query)
    if not key:
        return None
    if key in BUILTIN_DEV_FAQ:
        return BUILTIN_DEV_FAQ[key]
    ttl = dev_faq_cache_ttl()
    if ttl <= 0:
        return None
    entry = _load_store().get("entries", {}).get(key)
    if not isinstance(entry, dict):
        return None
    answer = entry.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    try:
        updated = float(entry.get("updated", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - updated >= ttl:
        return None
    return answer.strip()


def _can_learn_dev_faq(query: str) -> bool:
    q = normalize_cache_key(query)
    return is_dev_faq_query(q) or bool(
        re.match(r"(?i)^(what is|how to|how do i|difference between|what are)\s+", q)
    )


def set_dev_faq(query: str, answer: str) -> None:
    if not dev_faq_cache_enabled() or not _can_learn_dev_faq(query):
        return
    text = (answer or "").strip()
    if not text or len(text) < 40:
        return
    if text.startswith("[Errno") or "Operation timed out" in text or "Operation cancelled" in text:
        return
    key = _canonical_key(query)
    if not key or key in BUILTIN_DEV_FAQ:
        return
    store = _load_store()
    entries = store.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        store["entries"] = entries
    entries[key] = {"answer": text, "updated": time.time()}
    _save_store(store)


def list_dev_faq_keys(*, include_builtin: bool = True) -> list[str]:
    keys = sorted(BUILTIN_DEV_FAQ.keys()) if include_builtin else []
    for k in sorted(_load_store().get("entries", {}).keys()):
        if k not in keys:
            keys.append(k)
    return keys


def clear_dev_faq_cache(*, learned_only: bool = True) -> None:
    path = dev_faq_cache_path()
    if learned_only:
        _save_store({"version": 1, "entries": {}})
    elif path.is_file():
        path.unlink()
