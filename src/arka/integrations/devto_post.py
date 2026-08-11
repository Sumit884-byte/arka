#!/usr/bin/env python3
"""Write and publish dev.to articles from research, digests, or markdown files."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_DEVTO_API = "https://dev.to/api"
_DEFAULT_TAGS = ["programming", "research"]
_MAX_TAGS = 4

_POST_TRIGGER = re.compile(
    r"(?i)\b(?:post|publish|share|write)\b.*\b(?:on|for|to)\s+dev\.?to\b"
    r"|\bdev\.?to\b.*\b(?:post|publish|write|article|research)\b"
    r"|\bwrite\s+(?:an?\s+)?(?:article|post|research)\s+(?:on|for|about)\b"
)

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
_SOURCE_BULLET_RE = re.compile(
    r"^[-*]\s+(?:\[(https?://[^\]]+)\]\((https?://[^)]+)\)|(https?://\S+))\s*$",
    re.M,
)
_HTML_COMMENT_RE = re.compile(r"^<!--.*-->\s*$", re.M)
_PRIOR_LINKS_RE = re.compile(r"(?i)^\*{0,2}links to prior research\*{0,2}:?\s*$")

ARTICLE_SYSTEM = """You write engaging dev.to technical articles from research notes.
Rules:
- Output ONLY the article body in GitHub-flavored markdown (no YAML frontmatter).
- Start with a compelling hook paragraph — no "Introduction" heading.
- Use ## and ### headings; keep sections scannable.
- Include a short comparison table when comparing technologies (markdown table).
- Cite sources inline as markdown links where facts are used.
- End with ## Key takeaways (3–5 bullets) and ## Further reading (linked sources).
- Tone: practical, developer-adjacent, wearable-tech curious — not marketing fluff.
- Length: 900–1400 words.
- Do NOT include "Links to prior research" or HTML comments.
- Do NOT invent battery numbers not present in the research material.
"""


def api_key() -> str:
    return (os.environ.get("DEVTO_API_KEY") or os.environ.get("DEV_TO_API_KEY") or "").strip()


def devto_configured() -> bool:
    return bool(api_key())


def parse_devto_request(text: str) -> dict[str, str] | None:
    t = (text or "").strip()
    if not t or not _POST_TRIGGER.search(t):
        return None
    session = ""
    m = re.search(r"(?i)\bsession\s+([\w-]+)\b", t)
    if m:
        session = m.group(1)
    topic = ""
    m = re.search(
        r"(?i)\bresearch\s+(?:on\s+|about\s+)?(.+?)(?:\s+(?:to|for|on)\s+dev|\s+session\b|$)",
        t,
    )
    if m:
        topic = m.group(1).strip(" .")
    if not topic:
        m = re.search(r"(?i)\b(?:article|post)\s+(?:on|about)\s+(.+?)(?:\s+for\s+dev|\s+to\s+dev|$)", t)
        if m:
            topic = m.group(1).strip(" .")
    topic = re.sub(r"(?i)^(?:an?\s+)?(?:article|post)\s+(?:on|about)\s+", "", topic).strip()
    return {"session": session, "topic": topic, "raw": t}


def build_devto_argv_from_nl(text: str) -> list[str]:
    parsed = parse_devto_request(text)
    if not parsed:
        return []
    argv = ["write"]
    if parsed.get("session"):
        argv.extend(["--session", str(parsed["session"])])
    elif parsed.get("topic"):
        argv.extend(["--topic", str(parsed["topic"])])
    if re.search(r"(?i)\b(?:publish|post)\b", text) and not re.search(r"(?i)\bdraft\b", text):
        argv.append("--post")
    return argv


def _resolve_session_id(explicit: str | None = None, topic: str | None = None) -> str | None:
    try:
        from arka.agent.day_research import list_sessions, resolve_session_id

        if explicit:
            return explicit
        if topic:
            needle = topic.strip().lower()
            for row in list_sessions():
                if needle in str(row.get("topic") or "").lower():
                    return str(row["id"])
        return resolve_session_id(None)
    except ImportError:
        return explicit


def _session_root(session_id: str) -> Path | None:
    try:
        from arka.agent.day_research import session_dir

        return session_dir(session_id)
    except ImportError:
        return None


def extract_sources(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        m = _SOURCE_BULLET_RE.match(stripped)
        if not m:
            continue
        url = (m.group(2) or m.group(3) or m.group(1) or "").rstrip(".,;)")
        key = url.lower()
        if url and key not in seen:
            seen.add(key)
            urls.append(url)
    return urls


def clean_notes_for_prompt(text: str) -> str:
    lines: list[str] = []
    skip_prior = False
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            lines.append("")
            continue
        if _HTML_COMMENT_RE.match(stripped):
            continue
        if _PRIOR_LINKS_RE.match(stripped):
            skip_prior = True
            continue
        if skip_prior:
            if re.match(r"^[-*]\s+", stripped):
                continue
            if re.match(r"(?i)^\*{0,2}sources:\*{0,2}\s*$", stripped):
                skip_prior = False
            elif re.match(r"^#{1,6}\s+", stripped) or re.fullmatch(r"\*{2}.+\*{2}", stripped):
                skip_prior = False
            else:
                continue
        if re.match(r"(?i)^\*{0,2}sources:\*{0,2}\s*$", stripped):
            continue
        if _SOURCE_BULLET_RE.match(stripped):
            continue
        lines.append(raw)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def load_research_bundle(session_id: str) -> dict[str, Any]:
    root = _session_root(session_id)
    if not root or not root.is_dir():
        raise SystemExit(f"Unknown research session: {session_id}")

    bundle: dict[str, Any] = {"session_id": session_id, "root": str(root)}
    session_file = root / "session.json"
    if session_file.is_file():
        bundle["session"] = json.loads(session_file.read_text(encoding="utf-8"))
        bundle["topic"] = str(bundle["session"].get("topic") or "Research")

    for name in ("digest.md", "notes.md", "state.json"):
        path = root / name
        if path.is_file():
            if name.endswith(".json"):
                bundle[name.replace(".json", "")] = json.loads(path.read_text(encoding="utf-8"))
            else:
                bundle[name.replace(".md", "")] = path.read_text(encoding="utf-8")

    notes = str(bundle.get("notes") or "")
    digest = str(bundle.get("digest") or "")
    bundle["sources"] = extract_sources(notes) + [
        u for u in extract_sources(digest) if u not in extract_sources(notes)
    ]

    credits = bundle.get("session", {}).get("image_credits") if isinstance(bundle.get("session"), dict) else []
    if isinstance(credits, list) and credits:
        cover = next((c for c in credits if isinstance(c, dict) and c.get("file") == "cover"), None)
        if cover:
            bundle["cover_image_url"] = str(cover.get("photo_url") or "")

    return bundle


def suggest_tags(topic: str, state: dict[str, Any] | None = None) -> list[str]:
    tags: list[str] = []
    topic_l = (topic or "").lower()
    if "smartwatch" in topic_l or "wearable" in topic_l:
        tags.extend(["smartwatch", "wearables", "hardware"])
    if "battery" in topic_l:
        tags.append("battery")
    if state:
        for row in state.get("themes") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").lower()
            if "display" in name and "displays" not in tags:
                tags.append("displays")
    for fallback in _DEFAULT_TAGS:
        if fallback not in tags:
            tags.append(fallback)
    return tags[:_MAX_TAGS]


def suggest_title(topic: str, state: dict[str, Any] | None = None) -> str:
    thesis = str((state or {}).get("thesis") or "").strip()
    topic_clean = (topic or "Research").strip().title()
    if "mip" in thesis.lower() and "smartwatch" in topic.lower():
        return "Why MIP Displays Beat OLED for Smartwatch Battery Life"
    if "battery" in thesis.lower():
        return f"What {topic_clean} Battery Research Actually Shows"
    return f"A Deep Dive into {topic_clean}"


def write_article_markdown(
    bundle: dict[str, Any],
    *,
    title: str = "",
    tags: list[str] | None = None,
) -> tuple[str, str, list[str]]:
    topic = str(bundle.get("topic") or "Research")
    state = bundle.get("state") if isinstance(bundle.get("state"), dict) else {}
    digest = str(bundle.get("digest") or "")
    notes = clean_notes_for_prompt(str(bundle.get("notes") or ""))
    sources = bundle.get("sources") or []
    source_block = "\n".join(f"- {u}" for u in sources) if sources else "(none listed)"

    article_title = title or suggest_title(topic, state)
    article_tags = tags or suggest_tags(topic, state)

    user = (
        f"Title: {article_title}\n"
        f"Topic: {topic}\n"
        f"Tags: {', '.join(article_tags)}\n\n"
        f"Research state:\n{json.dumps(state, ensure_ascii=False)[:4000]}\n\n"
        f"Digest:\n{digest[:6000]}\n\n"
        f"Notes (cleaned):\n{notes[:12000]}\n\n"
        f"Sources to link in Further reading:\n{source_block}\n"
    )

    body = ""
    try:
        from arka.llm.cli import llm_complete

        body = (llm_complete(ARTICLE_SYSTEM, user, 0.45, task="summarize", skill="devto_post") or "").strip()
    except ImportError:
        pass

    if not body or len(body) < 400:
        body = _fallback_article(bundle, title=article_title, sources=sources)

    body = re.sub(r"^#+\s*.+\n+", "", body, count=1).strip()
    return article_title, body, article_tags


def _fallback_article(bundle: dict[str, Any], *, title: str, sources: list[str]) -> str:
    state = bundle.get("state") if isinstance(bundle.get("state"), dict) else {}
    thesis = str(state.get("thesis") or "").strip()
    findings = [str(x) for x in (state.get("confident_findings") or [])[:8]]
    opens = [str(x) for x in (state.get("open_questions") or [])[:4]]
    digest = str(bundle.get("digest") or "").strip()

    lines = [
        thesis or digest or "Research summary unavailable.",
        "",
        "## What the research found",
        "",
    ]
    for item in findings:
        lines.append(f"- {item}")
    lines.extend(["", "## Display architecture in plain terms", ""])
    lines.append(
        "MIP (Memory-in-Pixel) panels store the current pixel value in each cell. "
        "Power is spent when a pixel **changes**, not every frame. OLED and AMOLED panels "
        "must refresh continuously—even for a static watch face—so always-on display modes "
        "tax the battery differently."
    )
    lines.extend(
        [
            "",
            "| Technology | Typical vendors | Always-on behavior | Battery profile |",
            "| --- | --- | --- | --- |",
            "| MIP | Garmin, COROS | Face can stay on; dimming instead of full off | Strong for multi-day use |",
            "| OLED / AMOLED | Apple, Samsung | Often dims or refreshes aggressively | Strong UX; shorter cycles |",
            "",
            "## Open questions",
            "",
        ]
    )
    for item in opens:
        lines.append(f"- {item}")
    lines.extend(["", "## Key takeaways", ""])
    lines.extend(f"- {item}" for item in findings[:5])
    if sources:
        lines.extend(["", "## Further reading", ""])
        for url in sources:
            host = urlparse(url).netloc.replace("www.", "")
            lines.append(f"- [{host}]({url})")
    return "\n".join(lines)


def publish_article(
    *,
    title: str,
    body_markdown: str,
    tags: list[str],
    published: bool = False,
    cover_image: str = "",
    description: str = "",
) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise RuntimeError(
            "DEVTO_API_KEY not configured.\n"
            "  Get one at https://dev.to/settings/extensions\n"
            "  Then: integration setup devto --key YOUR_KEY"
        )

    article: dict[str, Any] = {
        "title": title,
        "body_markdown": body_markdown,
        "tags": tags[:_MAX_TAGS],
        "published": bool(published),
    }
    if cover_image:
        article["main_image"] = cover_image
    if description:
        article["description"] = description[:500]

    payload = json.dumps({"article": article}).encode("utf-8")
    req = urllib.request.Request(
        f"{_DEVTO_API}/articles",
        data=payload,
        method="POST",
        headers={
            "api-key": key,
            "Content-Type": "application/json",
            "User-Agent": "arka-devto-post/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"dev.to API HTTP {exc.code}: {detail[:500]}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected dev.to response: {data!r}")
    return data


def save_article_draft(path: Path, title: str, body: str, tags: list[str]) -> None:
    frontmatter = "\n".join(
        [
            "---",
            f'title: "{title.replace(chr(34), chr(39))}"',
            f"tags: {', '.join(tags)}",
            "published: false",
            "---",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter + body.strip() + "\n", encoding="utf-8")


def cmd_parse(args: argparse.Namespace) -> int:
    argv = build_devto_argv_from_nl(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    print("post_devto\tavailable")
    print(f"devto_api_key\t{'yes' if devto_configured() else 'no'}")
    if not devto_configured():
        print("setup_hint\tintegration setup devto — https://dev.to/settings/extensions")
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    session_id = _resolve_session_id(getattr(args, "session", None), getattr(args, "topic", None))
    input_path = (getattr(args, "input", None) or "").strip()
    bundle: dict[str, Any] = {}

    if input_path:
        path = Path(input_path).expanduser()
        if not path.is_file():
            raise SystemExit(f"File not found: {path}")
        raw = path.read_text(encoding="utf-8")
        title = getattr(args, "title", None) or path.stem.replace("-", " ").title()
        body = raw
        tags = [t.strip() for t in (getattr(args, "tags", "") or "").split(",") if t.strip()] or _DEFAULT_TAGS
    elif session_id:
        bundle = load_research_bundle(session_id)
        title_arg = (getattr(args, "title", None) or "").strip()
        tag_arg = [t.strip() for t in (getattr(args, "tags", "") or "").split(",") if t.strip()]
        title, body, tags = write_article_markdown(
            bundle,
            title=title_arg,
            tags=tag_arg or None,
        )
    else:
        raise SystemExit("Provide --session, --topic, or --input FILE")

    out = (getattr(args, "output", None) or "").strip()
    if session_id and not out:
        root = _session_root(session_id)
        out = str(root / "devto-article.md") if root else "devto-article.md"
    elif not out:
        out = "devto-article.md"

    out_path = Path(out).expanduser()
    save_article_draft(out_path, title, body, tags)

    print(f"title: {title}")
    print(f"tags: {', '.join(tags)}")
    print(f"saved: {out_path}")
    print(f"words: {len(body.split())}")
    print("---")
    print(body[:1200] + ("…" if len(body) > 1200 else ""))

    if getattr(args, "post", False) or getattr(args, "publish", False):
        return _do_publish(title, body, tags, bundle if session_id else {}, published=not getattr(args, "draft", False))
    if not devto_configured():
        print("\nDraft saved. Set DEVTO_API_KEY and rerun with --post to publish.", file=sys.stderr)
    return 0


def _do_publish(
    title: str,
    body: str,
    tags: list[str],
    bundle: dict[str, Any],
    *,
    published: bool,
) -> int:
    cover = str(bundle.get("cover_image_url") or "")
    desc = str((bundle.get("state") or {}).get("thesis") or "")[:500]
    if getattr(sys, "_dry_run", False):
        print("dry-run: would publish to dev.to", file=sys.stderr)
        return 0
    result = publish_article(
        title=title,
        body_markdown=body,
        tags=tags,
        published=published,
        cover_image=cover,
        description=desc,
    )
    url = str(result.get("url") or "")
    art_id = result.get("id")
    print("published: yes" if published else "published: draft on dev.to")
    if url:
        print(f"url: {url}")
    if art_id is not None:
        print(f"id: {art_id}")
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    path = Path((args.file or "").strip()).expanduser()
    if not path.is_file():
        raise SystemExit(f"Article file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    title = (args.title or "").strip()
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or _DEFAULT_TAGS
    body = raw
    fm = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if fm:
        body = raw[fm.end() :].strip()
        if not title:
            tm = re.search(r"(?m)^title:\s*[\"']?(.+?)[\"']?\s*$", fm.group(1))
            if tm:
                title = tm.group(1).strip()
        tagm = re.search(r"(?m)^tags:\s*(.+)$", fm.group(1))
        if tagm and not args.tags:
            tags = [t.strip() for t in re.split(r"[,\s]+", tagm.group(1)) if t.strip()]
    if not title:
        raise SystemExit("Title required (--title or frontmatter)")
    published = bool(args.publish) and not bool(args.draft)
    if args.dry_run:
        sys._dry_run = True  # type: ignore[attr-defined]
        print(f"title: {title}")
        print(f"tags: {', '.join(tags)}")
        print(f"published: {published}")
        print(f"words: {len(body.split())}")
        return 0
    return _do_publish(title, body, tags, {}, published=published)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write and publish dev.to articles")
    sub = parser.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse NL into post_devto argv")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(handler=cmd_parse)

    p_status = sub.add_parser("status", help="Show dev.to API status")
    p_status.set_defaults(handler=cmd_status)

    p_write = sub.add_parser("write", help="Write dev.to article from research session or file")
    p_write.add_argument("--session", "-s", help="Day-research session id")
    p_write.add_argument("--topic", help="Find session by topic substring")
    p_write.add_argument("--input", "-i", help="Markdown file to adapt")
    p_write.add_argument("--title", help="Article title override")
    p_write.add_argument("--tags", help="Comma-separated tags (max 4)")
    p_write.add_argument("--output", "-o", help="Output markdown path")
    p_write.add_argument("--post", action="store_true", help="Publish after writing (requires DEVTO_API_KEY)")
    p_write.add_argument("--publish", action="store_true", help="Alias for --post (live, not draft)")
    p_write.add_argument("--draft", action="store_true", help="Create dev.to draft (unpublished)")
    p_write.set_defaults(handler=cmd_write)

    p_post = sub.add_parser("post", help="Publish an existing markdown article")
    p_post.add_argument("file", help="Markdown file (optional YAML frontmatter)")
    p_post.add_argument("--title", help="Title override")
    p_post.add_argument("--tags", help="Comma-separated tags")
    p_post.add_argument("--publish", action="store_true", help="Publish live (default: draft)")
    p_post.add_argument("--draft", action="store_true", help="Save as dev.to draft")
    p_post.add_argument("--dry-run", action="store_true")
    p_post.set_defaults(handler=cmd_post)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 1
    return int(args.handler(args) or 0)


if __name__ == "__main__":
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass
    raise SystemExit(main())
