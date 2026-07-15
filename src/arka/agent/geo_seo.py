"""Lightweight GEO/SEO audit for local websites and documentation."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

def audit(root: Path) -> dict:
    files = list(root.rglob("*.html")) + list(root.rglob("*.mdx")) + list(root.rglob("*.md"))
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files[:200])
    checks = {
        "title": bool(re.search(r"<title>|^title:\s*", text, re.M | re.I)),
        "description": bool(re.search(r"description:\s*|meta[^>]+description", text, re.I)),
        "structured_data": bool(re.search(r"application/ld\+json|schema\.org", text, re.I)),
        "faq_content": bool(re.search(r"faq|frequently asked", text, re.I)),
        "ai_context": (root / "llms.txt").is_file() or (root / "docs" / "llms.txt").is_file(),
        "citation_ready": any(120 <= len(block.split()) <= 220 for block in re.split(r"\n\s*\n", text) if block.strip()),
    }
    score = round(sum(checks.values()) / len(checks) * 100)
    return {"score": score, "checks": checks, "files": len(files), "recommendations": [f"Add {name.replace('_', ' ')}" for name, ok in checks.items() if not ok]}

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audit a site for AI-search visibility and SEO foundations")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = audit(Path(args.path).expanduser().resolve())
    print(json.dumps(result, indent=2) if args.json else f"GEO/SEO score: {result['score']}/100\n" + "\n".join(f"- {x}" for x in result["recommendations"]) or "No recommendations")
    return 0
