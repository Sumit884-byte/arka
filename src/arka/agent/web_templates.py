"""Reusable web UI templates — list, show, and scaffold common interface patterns."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
from pathlib import Path

TEMPLATE_META: dict[str, dict[str, str]] = {
    "login": {
        "title": "Login / auth",
        "description": "Email/password sign-in with OAuth placeholders and sign-up CTA.",
        "when": "Authentication shells before wiring your auth provider.",
    },
    "dashboard": {
        "title": "Dashboard",
        "description": "Sidebar navigation, stats cards, and recent activity panel.",
        "when": "Admin panels, SaaS home views, or internal tools.",
    },
    "settings": {
        "title": "Settings",
        "description": "Tabbed settings with profile, notifications, and security sections.",
        "when": "User preferences, account management, or app configuration.",
    },
    "landing": {
        "title": "Landing / marketing hero",
        "description": "Marketing hero, feature grid, and footer CTA band.",
        "when": "Product landing pages and launch sites.",
    },
    "data-table": {
        "title": "Data table / list view",
        "description": "Search, filters, sortable-style table, badges, and pagination.",
        "when": "Admin lists, CRM views, inventory, or tabular data.",
    },
    "form": {
        "title": "Form (multi-step)",
        "description": "Wizard with progress indicator and validation-friendly fields.",
        "when": "Onboarding, checkout steps, surveys, or complex forms.",
    },
    "empty-state": {
        "title": "Empty state / error page",
        "description": "Empty, 404, and 500 state patterns on one page.",
        "when": "Zero-data views, error pages, or permission denied screens.",
    },
    "modal": {
        "title": "Modal / dialog",
        "description": "Confirm, form, and alert dialogs with open/close behavior.",
        "when": "Confirmations, quick edits, alerts, or focus-trapped overlays.",
    },
}

ALIASES: dict[str, str] = {
    "auth": "login",
    "signin": "login",
    "sign-in": "login",
    "signup": "login",
    "admin": "dashboard",
    "home": "dashboard",
    "marketing": "landing",
    "hero": "landing",
    "table": "data-table",
    "list": "data-table",
    "list-view": "data-table",
    "wizard": "form",
    "multi-step": "form",
    "404": "empty-state",
    "error": "empty-state",
    "error-page": "empty-state",
    "dialog": "modal",
}


def templates_root() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "web"


def shared_tokens_path() -> Path:
    return templates_root() / "_shared" / "tokens.css"


def normalize_name(name: str) -> str:
    key = (name or "").strip().lower().replace("_", "-")
    return ALIASES.get(key, key)


def template_names() -> list[str]:
    root = templates_root()
    names = sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "index.html").is_file()
    )
    return names


def _meta(name: str) -> dict[str, str]:
    canonical = normalize_name(name)
    base = TEMPLATE_META.get(canonical, {})
    return {
        "name": canonical,
        "title": base.get("title", canonical.replace("-", " ").title()),
        "description": base.get("description", ""),
        "when": base.get("when", ""),
    }


def list_templates() -> list[dict[str, str]]:
    return [_meta(name) for name in template_names()]


def template_dir(name: str) -> Path:
    canonical = normalize_name(name)
    path = templates_root() / canonical
    if not path.is_dir() or not (path / "index.html").is_file():
        raise FileNotFoundError(f"unknown web template: {name}")
    return path


def show_template(name: str) -> dict[str, object]:
    canonical = normalize_name(name)
    path = template_dir(canonical)
    index_html = (path / "index.html").read_text(encoding="utf-8")
    readme = (path / "README.md").read_text(encoding="utf-8") if (path / "README.md").is_file() else ""
    tokens = shared_tokens_path().read_text(encoding="utf-8")
    payload = _meta(canonical)
    payload.update(
        {
            "path": str(path),
            "readme": readme.strip(),
            "tokens_css": tokens,
            "index_html": index_html,
            "files": ["tokens.css", "index.html", "README.md"],
        }
    )
    return payload


def scaffold_files(name: str) -> list[tuple[Path, Path]]:
    """Return (source, dest_relative) pairs for a scaffold."""
    canonical = normalize_name(name)
    src_dir = template_dir(canonical)
    pairs: list[tuple[Path, Path]] = [
        (shared_tokens_path(), Path("tokens.css")),
        (src_dir / "index.html", Path("index.html")),
    ]
    readme = src_dir / "README.md"
    if readme.is_file():
        pairs.append((readme, Path("README.md")))
    return pairs


def scaffold_template(
    name: str,
    output: str | Path,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    canonical = normalize_name(name)
    template_dir(canonical)
    out = Path(output).expanduser().resolve()
    created: list[str] = []
    for src, rel in scaffold_files(canonical):
        dest = out / rel
        if dest.exists() and not force:
            raise FileExistsError(f"refusing to overwrite existing file: {dest}; use --force")
        created.append(str(dest))
        if dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return created


def route_command(cmd: str) -> str | None:
    clean = " ".join((cmd or "").split()).strip()
    if not clean:
        return None
    if re.search(
        r"(?i)\b(?:web|ui|interface)\s+templates?\b|\bcommon\s+web\s+interface\s+templates?\b|\bweb\s+ui\s+patterns?\b",
        clean,
    ):
        m = re.search(
            r"(?i)\b(?:scaffold|use|copy|generate|create)\b.*\b(login|auth|dashboard|settings|landing|data[- ]?table|form|empty[- ]?state|modal|dialog|hero|table|wizard)\b",
            clean,
        )
        if m:
            return f"web template scaffold {normalize_name(m.group(1))}"
        m = re.search(
            r"(?i)\b(?:show|preview|view)\b.*\b(login|auth|dashboard|settings|landing|data[- ]?table|form|empty[- ]?state|modal|dialog)\b",
            clean,
        )
        if m:
            return f"web template show {normalize_name(m.group(1))}"
        if re.search(r"(?i)\b(?:list|show|available|what|common)\b", clean):
            return "web template list"
        m = re.search(
            r"(?i)\b(login|auth|dashboard|settings|landing|data[- ]?table|form|empty[- ]?state|modal|dialog)\b",
            clean,
        )
        if m:
            return f"web template show {normalize_name(m.group(1))}"
        return "web template list"
    if re.search(r"(?i)^web\s+template\s+(list|show|scaffold)\b", clean):
        return clean
    if re.search(r"(?i)\bscaffold\s+(?:the\s+)?(?:dashboard|login|landing|settings|form|modal|data[- ]?table|empty[- ]?state)\s+(?:ui|page|template)\b", clean):
        m = re.search(
            r"(?i)\b(dashboard|login|landing|settings|form|modal|data[- ]?table|empty[- ]?state)\b",
            clean,
        )
        if m:
            return f"web template scaffold {normalize_name(m.group(1))}"
    if re.search(r"(?i)\bweb\s+template\s+(login|auth|dashboard|settings|landing|data[- ]?table|form|empty[- ]?state|modal)\b", clean):
        m = re.search(
            r"(?i)\bweb\s+template\s+(login|auth|dashboard|settings|landing|data[- ]?table|form|empty[- ]?state|modal)\b",
            clean,
        )
        if m:
            return f"web template show {normalize_name(m.group(1))}"
    return None


def nl_to_argv(text: str) -> list[str]:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return []
    routed = route_command(clean)
    if routed:
        return shlex.split(routed)[1:]  # drop leading "web"
    clean.lower()
    if re.search(r"(?i)\blist\b.*\b(?:web|ui)\s+templates?\b", clean):
        return ["template", "list"]
    m = re.search(
        r"(?i)\b(?:show|preview)\b.*\b(login|auth|dashboard|settings|landing|data[- ]?table|form|empty[- ]?state|modal)\b",
        clean,
    )
    if m:
        return ["template", "show", normalize_name(m.group(1))]
    m = re.search(
        r"(?i)\b(?:scaffold|use)\b.*\b(login|auth|dashboard|settings|landing|data[- ]?table|form|empty[- ]?state|modal)\b",
        clean,
    )
    if m:
        return ["template", "scaffold", normalize_name(m.group(1))]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka web template")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List available web UI templates")
    show = sub.add_parser("show", help="Show template HTML, tokens, and README")
    show.add_argument("name")
    scaffold = sub.add_parser("scaffold", help="Copy template files to an output directory")
    scaffold.add_argument("name")
    scaffold.add_argument("--output", "-o", default=".", help="Output directory (default: .)")
    scaffold.add_argument("--dry-run", action="store_true", help="Print paths without writing files")
    scaffold.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args(argv)

    if args.command == "list":
        for item in list_templates():
            print(f"{item['name']}\t{item['title']}\t{item['description']}")
        return 0
    if args.command == "show":
        try:
            payload = show_template(args.name)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        print(json.dumps(payload, indent=2))
        return 0
    try:
        created = scaffold_template(
            args.name,
            args.output,
            dry_run=args.dry_run,
            force=args.force,
        )
    except (FileNotFoundError, FileExistsError) as exc:
        parser.error(str(exc))
    prefix = "would create" if args.dry_run else "created"
    for path in created:
        print(f"{prefix} {path}")
    return 0


WEB_TEMPLATE_CLI_HEADS = frozenset({"web"})


def is_web_template_cli_argv(argv: list[str]) -> bool:
    return len(argv) >= 2 and argv[0] == "web" and argv[1] in {"template", "templates"}


def run_web_template_cli(argv: list[str]) -> int:
    return main(argv[2:] if len(argv) > 2 else ["list"])
