#!/usr/bin/env python3
"""Summarize a web page or article URL."""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.parse
import urllib.request

from arka.agent.chat import scrape_url
from arka.llm.cli import llm_complete


def _fetch_text(url: str) -> str:
    body = scrape_url(url)
    if body and len(body.split()) >= 20:
        return body
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; arka/1.0)"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise SystemExit("URL required")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urllib.parse.urlparse(raw)
    if not parsed.netloc:
        raise SystemExit(f"Invalid URL: {raw}")
    return raw


def summarize_url(url: str, question: str = "Summarize the key points") -> str:
    url = _normalize_url(url)
    body = _fetch_text(url)
    if not body or len(body.split()) < 20:
        raise SystemExit(f"Could not extract readable text from {url}")

    system = (
        "You summarize web articles accurately. Be concise: lead with the main point, "
        "then 3-6 bullets. Mention source context if obvious. If asked a question, answer it."
    )
    user = f"URL: {url}\nQuestion: {question}\n\nArticle text:\n{body[:12000]}"
    return llm_complete(system, user, temperature=0.2, task="summarize").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a web page")
    parser.add_argument("url", help="Page URL")
    parser.add_argument("-q", "--question", default="Summarize the key points")
    args = parser.parse_args()

    print(f"Fetching {args.url} …", file=sys.stderr)
    summary = summarize_url(args.url, args.question)
    print("━━━ Summary ━━━")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
