#!/usr/bin/env python3
"""Summarize a whole website by crawling bounded same-site links."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass
from html.parser import HTMLParser

USER_AGENT = "arka-site-summary/1.0"
SOCIAL_DOMAINS = {
    "facebook.com",
    "fb.com",
    "instagram.com",
    "linkedin.com",
    "lnkd.in",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "discord.gg",
    "discord.com",
    "reddit.com",
    "pinterest.com",
    "threads.net",
    "medium.com",
    "substack.com",
}


@dataclass
class PageSummary:
    url: str
    title: str
    words: int
    summary: str


@dataclass
class SiteSummary:
    start_url: str
    pages_seen: int
    pages_summarized: int
    skipped_social: int
    skipped_offsite: int
    pages: list[PageSummary]
    overview: str


class ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        clean = " ".join(html.unescape(data or "").split())
        if not clean or self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(clean)
        elif len(clean) > 1:
            self.text_parts.append(clean)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self.text_parts).strip()


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not re.match(r"(?i)^https?://", raw):
        raw = "https://" + raw
    parsed = urllib.parse.urlparse(raw)
    path = parsed.path or "/"
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def registrable_host(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_social_url(url: str) -> bool:
    host = registrable_host(url)
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_DOMAINS)


def same_site(url: str, start_url: str) -> bool:
    return registrable_host(url) == registrable_host(start_url)


def should_skip_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True
    path = parsed.path.lower()
    return bool(
        re.search(
            r"\.(?:jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|gz|tar|mp4|mp3|mov|avi|css|js|woff2?)$",
            path,
        )
    )


def fetch_html(url: str, *, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type and "text/" not in content_type:
            return ""
        raw = resp.read(1_500_000)
    return raw.decode("utf-8", errors="replace")


def parse_html(doc: str) -> tuple[str, str, list[str]]:
    parser = ReadableHTMLParser()
    parser.feed(doc or "")
    return parser.title, parser.text, parser.links


def split_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if len(s.strip()) > 30]


def summarize_text(text: str, *, max_sentences: int = 4) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return "No readable page text found."
    picked = sentences[:max_sentences]
    return " ".join(picked)


def summarize_site(start_url: str, *, max_pages: int = 12, max_depth: int = 1, timeout: int = 12) -> SiteSummary:
    start = normalize_url(start_url)
    if not start:
        raise ValueError("missing URL")
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    seen: set[str] = set()
    pages: list[PageSummary] = []
    skipped_social = 0
    skipped_offsite = 0

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        url = normalize_url(url)
        if not url or url in seen or should_skip_url(url):
            continue
        seen.add(url)
        if is_social_url(url):
            skipped_social += 1
            continue
        if not same_site(url, start):
            skipped_offsite += 1
            continue
        try:
            doc = fetch_html(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        title, text, links = parse_html(doc)
        words = len(text.split())
        if words:
            pages.append(
                PageSummary(
                    url=url,
                    title=title or urllib.parse.urlparse(url).path or url,
                    words=words,
                    summary=summarize_text(text),
                )
            )
        if depth >= max_depth:
            continue
        for href in links:
            absolute = normalize_url(urllib.parse.urljoin(url, href))
            if not absolute or absolute in seen:
                continue
            if is_social_url(absolute):
                skipped_social += 1
                continue
            if not same_site(absolute, start):
                skipped_offsite += 1
                continue
            if not should_skip_url(absolute):
                queue.append((absolute, depth + 1))

    overview_source = " ".join(f"{p.title}. {p.summary}" for p in pages)
    overview = summarize_text(overview_source, max_sentences=6)
    return SiteSummary(
        start_url=start,
        pages_seen=len(seen),
        pages_summarized=len(pages),
        skipped_social=skipped_social,
        skipped_offsite=skipped_offsite,
        pages=pages,
        overview=overview,
    )


def render_text(summary: SiteSummary) -> str:
    lines = [
        "━━━ Site summary ━━━",
        f"Start: {summary.start_url}",
        f"Pages summarized: {summary.pages_summarized}  ·  skipped social: {summary.skipped_social}  ·  skipped offsite: {summary.skipped_offsite}",
        "",
        "Overview:",
        summary.overview,
        "",
        "Pages:",
    ]
    for idx, page in enumerate(summary.pages, 1):
        lines.extend(
            [
                f"{idx}. {page.title}",
                f"   {page.url}",
                f"   {page.words} words · {page.summary}",
            ]
        )
    return "\n".join(lines)


def route_site_summary(text: str) -> str | None:
    if not re.search(r"(?i)\b(?:summari[sz]e|digest|overview|explain)\b", text or ""):
        return None
    if not re.search(r"(?i)\b(?:entire|whole|full|all|site|website|sitemap|sublinks?|pages?)\b", text or ""):
        return None
    match = re.search(r"https?://[^\s\"'<>]+|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s\"'<>]*)?", text or "", re.I)
    if not match:
        return None
    return "site_summary " + match.group(0).rstrip(".,)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize a bounded same-site crawl without social/offsite links.")
    parser.add_argument("url")
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = summarize_site(
            args.url,
            max_pages=max(1, min(args.max_pages, 50)),
            max_depth=max(0, min(args.depth, 3)),
            timeout=max(2, min(args.timeout, 60)),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        print(render_text(summary))
    return 0 if summary.pages_summarized else 1


if __name__ == "__main__":
    raise SystemExit(main())
