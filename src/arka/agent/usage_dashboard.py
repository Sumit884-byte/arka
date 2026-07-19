"""Generate a local HTML dashboard from Arka's privacy-preserving usage counters."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def build(output: str = "arka-usage-dashboard.html") -> dict[str, object]:
    from arka.core.skill_usage import report
    data = report()
    rows = "".join(f"<tr><td>{html.escape(str(name))}</td><td>{count}</td></tr>" for name, count in data["skills"])
    document = f"""<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Arka usage</title><style>body{{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 20px;background:#0b1020;color:#edf2ff}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{background:#17213c;padding:18px;border-radius:12px;min-width:160px}}table{{margin-top:24px;width:100%;border-collapse:collapse}}td{{padding:10px;border-bottom:1px solid #2b385d}}.muted{{color:#9eacce}}</style><h1>Arka usage dashboard</h1><p class='muted'>Local counters only; prompts and arguments are never stored.</p><div class='cards'><div class='card'><b>Total invocations</b><h2>{data['total']}</h2></div><div class='card'><b>Tracking</b><h2>{'on' if data['enabled'] else 'off'}</h2></div><div class='card'><b>Skills used</b><h2>{len(data['skills'])}</h2></div></div><table><tr><td><b>Skill</b></td><td><b>Uses</b></td></tr>{rows or '<tr><td colspan=2>No usage recorded yet.</td></tr>'}</table>"""
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return {"output": str(path), "total": data["total"], "skills": len(data["skills"]), "tracking": data["enabled"]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka usage dashboard")
    p.add_argument("--output", default="arka-usage-dashboard.html")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = build(args.output)
    print(json.dumps(result, indent=2) if args.json else f"Usage dashboard: {result['output']}")
    return 0
