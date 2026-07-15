"""Small, inspectable prompt and loop templates for composing new workflows."""
from __future__ import annotations
import argparse
import json

TEMPLATES = {
    "research_brief": {"kind": "prompt", "description": "Evidence-first research brief", "body": "Research {topic}. State the answer first, cite primary sources, separate facts from inference, and list open questions."},
    "repo_release": {"kind": "loop", "description": "Repeat health checks before release", "body": "loop 300 --count 5 repo_health run"},
    "frontend_review": {"kind": "loop", "description": "Iterate frontend review", "body": "frontend_loop {path} --loops {loops}"},
    "prompt_refine": {"kind": "prompt", "description": "Refine an existing prompt", "body": "prompt_optimize {prompt} --rounds {rounds}"},
    "python_cli": {"kind": "code", "description": "Typed Python CLI starter", "body": "#!/usr/bin/env python3\nfrom __future__ import annotations\nimport argparse\n\ndef main() -> int:\n    parser = argparse.ArgumentParser(description={description!r})\n    parser.add_argument('value', nargs='?', default={default!r})\n    print(parser.parse_args().value)\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n", "defaults": {"description": "An Arka-generated utility", "default": "hello"}},
    "api_health_check": {"kind": "code", "description": "Dependency-free HTTP health probe", "body": "#!/usr/bin/env python3\nimport argparse\nimport urllib.request\n\ndef main() -> int:\n    parser = argparse.ArgumentParser()\n    parser.add_argument('url', nargs='?', default={url!r})\n    args = parser.parse_args()\n    try:\n        with urllib.request.urlopen(args.url, timeout=10) as response:\n            print(response.status, args.url)\n            return 0 if 200 <= response.status < 400 else 1\n    except Exception as exc:\n        print(f'health check failed: {{exc}}')\n        return 1\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n", "defaults": {"url": "http://127.0.0.1:8000/health"}},
    "data_pipeline": {"kind": "code", "description": "Streaming JSONL transform", "body": "#!/usr/bin/env python3\nimport json\nimport sys\n\ndef transform(row: dict) -> dict:\n    return {{**row, 'processed': True}}\n\nfor line in sys.stdin:\n    if line.strip():\n        print(json.dumps(transform(json.loads(line))))\n", "defaults": {}},
    "browser_smoke": {"kind": "code", "description": "Playwright browser smoke test", "body": "from playwright.sync_api import sync_playwright\n\nURL = {url!r}\nwith sync_playwright() as p:\n    browser = p.chromium.launch(headless=True)\n    page = browser.new_page()\n    page.goto(URL, wait_until='domcontentloaded')\n    assert page.title(), 'page has no title'\n    print(page.title())\n    browser.close()\n", "defaults": {"url": "http://localhost:3000"}},
    "walk_folder": {"kind": "code", "description": "Walk a folder or all nested subfolders", "body": "#!/usr/bin/env python3\nfrom __future__ import annotations\nimport argparse\nfrom pathlib import Path\n\ndef main() -> int:\n    parser = argparse.ArgumentParser(description={description!r})\n    parser.add_argument('folder', nargs='?', default={folder!r})\n    parser.add_argument('--pattern', default={pattern!r}, help='Glob pattern, e.g. *.py')\n    parser.add_argument('--recursive', action='store_true', help='Include nested subfolders')\n    args = parser.parse_args()\n    root = Path(args.folder).expanduser().resolve()\n    if not root.is_dir():\n        parser.error(f'folder not found: {{root}}')\n    matches = root.rglob(args.pattern) if args.recursive else root.glob(args.pattern)\n    for path in sorted((item for item in matches if item.is_file()), key=lambda item: item.as_posix()):\n        print(path)\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n", "defaults": {"description": "Walk files safely", "folder": ".", "pattern": "*"}},
}

def render(name: str, values: dict[str, str]) -> str:
    if name not in TEMPLATES:
        raise KeyError(f"unknown template: {name}")
    merged = dict(TEMPLATES[name].get("defaults", {}))
    merged.update(values)
    return TEMPLATES[name]["body"].format_map({k: str(v) for k, v in merged.items()})

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Choose and instantiate Arka workflow templates")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("name")
    use = sub.add_parser("use")
    use.add_argument("name")
    use.add_argument("--set", action="append", default=[])
    use.add_argument("--out", help="write generated output to a new file")
    args = p.parse_args(argv)
    if args.command == "list":
        for name, item in TEMPLATES.items():
            print(f"{name}\t{item['kind']}\t{item['description']}")
        return 0
    if args.name not in TEMPLATES:
        p.error(f"unknown template: {args.name}")
    if args.command == "show":
        print(json.dumps({"name": args.name, **TEMPLATES[args.name]}, indent=2))
        return 0
    values = {}
    for item in args.set:
        if "=" not in item:
            p.error("--set expects key=value")
        key, value = item.split("=", 1)
        values[key] = value
    try:
        output = render(args.name, values)
        if args.out:
            from pathlib import Path
            target = Path(args.out)
            if target.exists():
                p.error(f"refusing to overwrite existing file: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(output, encoding="utf-8")
            print(f"created {target}")
        else:
            print(output)
    except (KeyError, ValueError) as exc:
        p.error(str(exc))
    return 0
