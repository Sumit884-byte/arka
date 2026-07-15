"""Fast setup and diagnostics for web-search API providers."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from arka.paths import env_file

PROVIDERS = {
    "serper": ("SERPER_API_KEY", "https://serper.dev/api-key"),
    "tavily": ("TAVILY_API_KEY", "https://app.tavily.com"),
    "brave": ("BRAVE_SEARCH_API_KEY", "https://brave.com/search/api/"),
}


def load_saved_env(path: Path | None = None) -> None:
    """Load simple dotenv entries without overwriting explicit environment state."""
    target = path or env_file()
    if not target.is_file():
        return
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if text.startswith("export "):
            text = text[7:].lstrip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _write_key(name: str, value: str, path: Path | None = None) -> Path:
    path = path or env_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    # Quote values containing dotenv-significant characters while keeping
    # simple keys readable and backwards-compatible.
    encoded = value if all(ch not in value for ch in " #\t\"'") else "'" + value.replace("'", "'\\''") + "'"
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == name:
            lines[i] = f"{name}={encoded}"
            break
    else:
        lines.append(f"{name}={encoded}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    os.environ[name] = value
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configure search API providers")
    sub = parser.add_subparsers(dest="action")
    p_setup = sub.add_parser("setup")
    p_setup.add_argument("provider", choices=sorted(PROVIDERS))
    p_setup.add_argument("--key", default="")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.action == "setup":
        name, url = PROVIDERS[args.provider]
        key = (args.key or os.environ.get(name, "")).strip()
        if not key:
            print(f"Get a key at {url}, then run: arka search setup {args.provider} --key <key>")
            return 2
        print(f"Saved {name} to { _write_key(name, key) }")
        return 0
    if args.action == "status":
        for provider, (name, url) in PROVIDERS.items():
            print(f"{provider}\t{'configured' if os.environ.get(name, '').strip() else 'missing'}\t{url}")
        return 0
    parser.print_help()
    return 2
