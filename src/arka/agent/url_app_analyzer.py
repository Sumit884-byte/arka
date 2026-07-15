"""Analyze a web app URL and render an interactive design review dashboard."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def collect(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https")
    data = {"url": url, "host": parsed.netloc, "title": "", "status": None, "viewport_checks": [], "signals": []}
    try:
        with urlopen(Request(url, headers={"User-Agent": "Arka-Design-Analyzer/1.0"}), timeout=15) as response:
            body = response.read(500_000).decode("utf-8", errors="replace")
            data["status"] = response.status
            data["title"] = (body.split("<title>", 1)[1].split("</title>", 1)[0].strip() if "<title>" in body else parsed.netloc)
            data["signals"] = [
                "Missing viewport meta tag" if "viewport" not in body.lower() else "Responsive viewport meta tag found",
                "No obvious heading found" if "<h1" not in body.lower() else "Primary heading found",
                "Images should have alt text review" if "<img" in body.lower() and "alt=" not in body.lower() else "Image alt coverage looks plausible",
            ]
    except Exception as exc:
        data["signals"] = [f"Fetch unavailable: {exc}"]
    return data


def render(data: dict[str, object], output: str) -> Path:
    cards = "".join(f"<li>{html.escape(str(signal))}</li>" for signal in data["signals"])
    document = f"""<!doctype html><meta charset='utf-8'><title>Arka design review</title><style>body{{font:16px system-ui;max-width:960px;margin:auto;padding:2rem;background:#10131d;color:#eef}}.card{{background:#1c2233;padding:1.2rem;border-radius:16px;margin:1rem 0;box-shadow:0 8px 30px #0004}}button{{padding:.7rem;border:0;border-radius:10px;background:#6d5dfc;color:white}}li{{margin:.7rem}}</style><h1>Design review: {html.escape(str(data['title']))}</h1><p>{html.escape(str(data['url']))} · HTTP {data['status']}</p><button onclick="document.body.classList.toggle('light')">Toggle theme</button><section class='card'><h2>Signals</h2><ul>{cards}</ul></section><section class='card'><h2>Prioritized improvement prompts</h2><ol><li>Check mobile, tablet, and desktop layout independently; change only the failing viewport.</li><li>Improve hierarchy and primary action clarity without changing button order.</li><li>Verify keyboard focus, contrast, loading states, and error recovery.</li><li>Measure interaction latency and remove visual clutter before adding animation.</li></ol></section>"""
    target = Path(output).expanduser().resolve()
    target.write_text(document, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka url-app")
    parser.add_argument("url")
    parser.add_argument("--output", default="arka-design-review.html")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = collect(args.url)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(render(data, args.output))
        return 0
    except (OSError, ValueError) as exc:
        print(f"url-app: {exc}")
        return 2
