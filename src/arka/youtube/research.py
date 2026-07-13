#!/usr/bin/env python3
"""YouTube research mode — search, fetch all transcripts, synthesize a unified answer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from arka.media.batch import (
    DEFAULT_MAX_ITEMS,
    YT_FETCH_DELAY,
    _merge_digest,
    _research_allow_no_caption,
    _summarize_transcript,
)
from arka.media.transcript import _load_fish_env
from arka.core.progress import ProgressBar, progress_enabled, progress_note
from arka.youtube.transcript import fetch_transcript_with_source, youtube_search

CACHE = Path.home() / ".cache" / "fish-agent" / "youtube-research"
DEFAULT_LIMIT = int(os.environ.get("YT_RESEARCH_MAX", "2"))
DEFAULT_POOL_MAX = 50


def _research_pool_size(target: int) -> int:
    """How many search hits to scan when filling a target of N captioned videos."""
    raw = os.environ.get("YT_RESEARCH_POOL", "").strip()
    if raw:
        try:
            pool = int(raw)
        except ValueError:
            pool = max(target * 5, target + 3, 10)
    else:
        pool = max(target * 5, target + 3, 10)
    return max(target, min(pool, DEFAULT_POOL_MAX))

_WORD_NUMS: dict[str, int] = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

_LIMIT_PREFIX_RE = re.compile(
    r"(?i)^(?:do\s+(?:a\s+|an\s+)?)?"
    r"(?:analyze|analyse|research|summarize|summarise|study|review|check)\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a|an)\s+"
    r"(?:youtube\s+)?videos?\s*(?:on|about|for|of)?\s*"
)
_LIMIT_INLINE_RE = re.compile(
    r"(?i)\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
    r"(?:youtube\s+)?videos?\s*(?:on|about|for|of)\s+"
)
_LIMIT_FROM_SUFFIX_RE = re.compile(
    r"(?i)^(.+?)\s+from\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
    r"(?:youtube\s+)?videos?\s*$"
)
_LIMIT_TRAILING_NUM_RE = re.compile(r"^(.+?\S)\s+(\d{1,2})$")


def _word_to_int(token: str) -> int | None:
    token = token.lower().strip()
    if token.isdigit():
        n = int(token)
        return n if n > 0 else None
    return _WORD_NUMS.get(token)


def _parse_query_limit(raw: str) -> tuple[str, int | None]:
    """Extract optional video count from NL query, e.g. 'analyze 5 videos on react' → ('react', 5)."""
    q = (raw or "").strip()
    if not q:
        return q, None

    m = _LIMIT_PREFIX_RE.match(q)
    if m:
        limit = _word_to_int(m.group(1))
        q = q[m.end() :].strip()
        return q, limit

    m = _LIMIT_INLINE_RE.search(q)
    if m:
        limit = _word_to_int(m.group(1))
        q = (q[: m.start()] + q[m.end() :]).strip()
        return q, limit

    m = _LIMIT_FROM_SUFFIX_RE.match(q)
    if m:
        limit = _word_to_int(m.group(2))
        q = m.group(1).strip()
        return q, limit

    m = _LIMIT_TRAILING_NUM_RE.match(q)
    if m:
        limit = _word_to_int(m.group(2))
        # Trailing "react 5" → 5 videos; avoid "react 19" (framework version) → keep full query
        if limit is not None and 1 <= limit <= 12:
            q = m.group(1).strip()
            return q, limit

    return q, None

RESEARCH_PER_ITEM = (
    "Summarize this video in 4–7 bullet points for research. "
    "Include: main thesis, key facts/claims, evidence cited, and speaker/channel perspective. "
    "Note anything controversial or uncertain."
)
RESEARCH_MERGE = (
    "You are synthesizing a YouTube research report from multiple video summaries. "
    "Write a cohesive research brief: (1) one-paragraph overview, (2) key findings grouped by theme, "
    "(3) areas of agreement vs disagreement across creators, (4) gaps or weak evidence, "
    "(5) short 'so what' conclusion. Attribute important claims to video titles in parentheses. "
    "Be factual; do not invent content not present in the summaries."
)


def _emit(msg: str) -> None:
    if not progress_enabled():
        print(msg, file=sys.stderr)


def _slug(query: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40] or "query"
    h = hashlib.sha256(query.encode()).hexdigest()[:8]
    return f"{base}-{h}"


def _save_session(query: str, entries: list[dict], digest: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    sid = _slug(query)
    path = CACHE / f"{sid}.json"
    payload = {
        "query": query,
        "saved": time.time(),
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "videos": entries,
        "digest": digest,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _index_for_qa(query: str, entries: list[dict]) -> str | None:
    try:
        from arka.stock.turboquant_rag import index_media_transcript, use_turboquant
    except ImportError:
        return None
    if not use_turboquant():
        return None
    slug = f"yt-research-{_slug(query)}"
    combined_parts: list[str] = []
    for row in entries:
        text = row.get("transcript") or ""
        if not text.strip():
            continue
        title = row.get("title") or row.get("video_id") or "video"
        channel = row.get("channel") or ""
        header = f"Video: {title}"
        if channel:
            header += f" (channel: {channel})"
        header += f"\nURL: https://youtube.com/watch?v={row.get('video_id', '')}"
        combined_parts.append(f"{header}\n\n{text}")
    if not combined_parts:
        return None
    combined = "\n\n---\n\n".join(combined_parts)
    if index_media_transcript(combined, slug):
        return slug
    return None


def _answer_from_index(slug: str, question: str) -> str:
    from arka.llm.cli import llm_complete
    from arka.media.qa import answer_system_prompt
    from arka.stock.turboquant_rag import _media_store

    store = _media_store(slug)
    if not store.chunks:
        return ""
    ctx = store.search(question, max_chars=14000)
    if not ctx.strip():
        return ""
    return llm_complete(
        answer_system_prompt(question),
        f"Context:\n{ctx}\n\nQuestion: {question}",
        task="research",
    ).strip()


def _apply_research_env() -> None:
    """Prefer YouTube caption API over rate-limited yt-dlp for research runs."""
    os.environ.setdefault("YT_WHISPER_FALLBACK", "auto")
    os.environ.setdefault("YT_PLAYER_CLIENT", "android_vr,mweb,web")
    os.environ.setdefault("YT_RESEARCH_DELAY", "3")
    os.environ.setdefault("YT_RESEARCH_ALLOW_NO_CAPTION", "0")
    # Override .env values that force yt-dlp-only (slow, 429-prone on macOS)
    if os.environ.get("YT_SKIP_TRANSCRIPT_API", "").lower() in {"1", "true", "yes", "on"}:
        print(
            "arka_youtube_research: using caption API first (unset ARKA_YT_SKIP_TRANSCRIPT_API to persist)",
            file=sys.stderr,
        )
    os.environ["YT_SKIP_TRANSCRIPT_API"] = "0"
    os.environ["YT_PREFER_YTDLP"] = "0"


def cmd_research(args: argparse.Namespace) -> int:
    _load_fish_env()
    _apply_research_env()

    query = args.query.strip()
    parsed_limit: int | None = None
    if query:
        query, parsed_limit = _parse_query_limit(query)
    if not query:
        print("Provide a YouTube search query.", file=sys.stderr)
        return 1

    limit = args.limit or parsed_limit or DEFAULT_LIMIT
    limit = max(1, min(int(limit), DEFAULT_MAX_ITEMS))

    allow_no_caption = _research_allow_no_caption()
    pool = _research_pool_size(limit)
    mode = "captions or STT" if allow_no_caption else "captions only"
    _emit(
        f"Searching YouTube: {query!r} "
        f"({limit} video{'s' if limit != 1 else ''}, {mode}, scanning up to {pool} results)"
    )
    try:
        hits = youtube_search(query, limit=pool)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    if not hits:
        print(f"No YouTube results for: {query}", file=sys.stderr)
        return 1

    per_q = args.question or RESEARCH_PER_ITEM
    if args.focus:
        per_q = f"{per_q}\n\nResearch focus: {args.focus}"
    merge_q = args.merge_question or RESEARCH_MERGE
    if args.focus:
        merge_q = f"{merge_q}\n\nAnswer this research question: {args.focus}"

    items: list[tuple[str, str]] = []
    session_entries: list[dict] = []
    errors: list[tuple[str, str]] = []
    skipped_no_captions: list[str] = []
    candidates_scanned = 0
    bar = ProgressBar("Research", total=limit) if progress_enabled() else None

    for i, (vid, title, channel) in enumerate(hits, start=1):
        candidates_scanned = i
        if len(items) >= limit:
            break

        label = title or vid
        sub = f" ({channel})" if channel else ""
        display = f"{label}{sub}"
        if bar is not None:
            bar.set(len(items), total=limit, label=f"→ {label[:32]}")
        else:
            _emit(f"[candidate {i}/{len(hits)}] {display}")

        row: dict = {
            "video_id": vid,
            "title": title,
            "channel": channel,
            "url": f"https://youtube.com/watch?v={vid}",
        }
        try:
            if YT_FETCH_DELAY > 0:
                time.sleep(YT_FETCH_DELAY)
            text, src = fetch_transcript_with_source(
                vid,
                research=True,
                allow_whisper=allow_no_caption,
            )
            if not text:
                if allow_no_caption:
                    raise RuntimeError("no transcript available")
                row["error"] = "no captions — skipped"
                skipped_no_captions.append(display)
                session_entries.append(row)
                progress_note(f"  skip (no captions): {display[:72]}")
                continue

            row["transcript_source"] = src
            row["transcript_words"] = len(text.split())
            row["transcript"] = text
            summary = _summarize_transcript(text, display, per_q, None)
            row["summary"] = summary
            items.append((display, summary))
            if bar is not None:
                bar.set(len(items), total=limit, label=label[:36])
            if args.show_items or not progress_enabled():
                print(f"\n── {display} ──\n{summary}\n", file=sys.stderr if progress_enabled() else sys.stdout)
        except Exception as exc:
            err_msg = str(exc).strip() or exc.__class__.__name__
            row["error"] = err_msg
            errors.append((display, err_msg))
            progress_note(f"⚠ Error — {display}: {err_msg}")

        session_entries.append(row)

    if bar is not None:
        bar.set(len(items), total=limit, label="Synthesizing")

    ok_items = [(label, summary) for label, summary in items]
    if not ok_items:
        print("No transcripts available for any search result.", file=sys.stderr)
        if skipped_no_captions:
            print(
                f"\nSkipped {len(skipped_no_captions)} video(s) without captions "
                f"(scanned {candidates_scanned} of {len(hits)} results).",
                file=sys.stderr,
            )
        if errors:
            print("\n━━━ Errors ━━━", file=sys.stderr)
            for disp, err in errors:
                print(f"  • {disp}: {err}", file=sys.stderr)
        print(
            "Tips: media_transcript --setup-local  |  "
            "ARKA_YT_COOKIES_BROWSER=chrome  |  "
            "ARKA_YT_RESEARCH_ALLOW_NO_CAPTION=1  |  "
            "pip install youtube-transcript-api",
            file=sys.stderr,
        )
        return 1

    if len(ok_items) == 1:
        merge_q = (
            f"{merge_q}\n\nNote: only one video was analyzed — write a focused brief from that source."
        )

    digest = _merge_digest(ok_items, merge_q)
    if bar is not None:
        bar.done("Done")

    scanned = candidates_scanned
    print("━━━ YouTube research ━━━")
    print(f"Query: {query}")
    parts = [f"Videos: {len(ok_items)} of {limit} target ({scanned} candidates scanned)"]
    if skipped_no_captions:
        parts.append(f"{len(skipped_no_captions)} skipped (no captions)")
    if errors:
        parts.append(f"{len(errors)} failed")
    print(", ".join(parts))
    print()
    print(digest)

    if errors:
        print("\n━━━ Errors (continued with successful videos) ━━━", file=sys.stderr)
        for disp, err in errors:
            print(f"  • {disp}: {err}", file=sys.stderr)

    path = _save_session(query, session_entries, digest)
    print(f"\nSaved session: {path}", file=sys.stderr)

    if args.index:
        slug = _index_for_qa(query, session_entries)
        if slug:
            print(f"Indexed for Q&A: {slug}  →  transcript_ask / doc_ask with TurboQuant media slug", file=sys.stderr)
        else:
            print("TurboQuant indexing skipped (backend off or no text).", file=sys.stderr)

    if args.ask and args.index:
        slug = f"yt-research-{_slug(query)}"
        answer = _answer_from_index(slug, args.ask)
        if answer:
            print("\n━━━ Follow-up answer ━━━")
            print(answer)

    return 0


def cmd_list_sessions(_args: argparse.Namespace) -> int:
    if not CACHE.is_dir():
        print("No saved YouTube research sessions.")
        return 0
    files = sorted(CACHE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("No saved YouTube research sessions.")
        return 0
    for path in files[:15]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        n = len([v for v in data.get("videos") or [] if v.get("summary")])
        print(f"{path.stem}  {data.get('when', '?')}  ({n} videos)")
        print(f"  {data.get('query', '')[:100]}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    path = CACHE / f"{args.session}.json"
    if not path.is_file():
        matches = list(CACHE.glob(f"*{args.session}*.json"))
        if len(matches) == 1:
            path = matches[0]
        else:
            print(f"Session not found: {args.session}", file=sys.stderr)
            return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    query = data.get("query") or ""
    slug = f"yt-research-{_slug(query)}"
    if not _index_for_qa(query, data.get("videos") or []):
        print("Could not load index; re-run with --index", file=sys.stderr)
        return 1
    answer = _answer_from_index(slug, args.question)
    if not answer:
        print("No answer generated.", file=sys.stderr)
        return 1
    print(answer)
    return 0


def cmd_links(args: argparse.Namespace) -> int:
    """Search YouTube and print video URLs (no transcripts / LLM)."""
    raw = args.query
    query = " ".join(raw) if isinstance(raw, list) else str(raw or "").strip()
    if not query:
        print("Provide a YouTube search query.", file=sys.stderr)
        return 1
    limit = max(1, min(int(args.limit or 8), 20))
    try:
        hits = youtube_search(query, limit=limit)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    if not hits:
        print(f"No YouTube results for: {query}", file=sys.stderr)
        return 1

    lines = [f"YouTube videos for: {query}", ""]
    for i, (vid, title, channel) in enumerate(hits, start=1):
        url = f"https://youtube.com/watch?v={vid}"
        ch = f" — {channel}" if channel else ""
        lines.append(f"{i}. {title}{ch}")
        lines.append(f"   {url}")
    print("\n".join(lines))
    return 0


def main() -> int:
    _load_fish_env()
    parser = argparse.ArgumentParser(description="YouTube search → transcript → research digest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="Search YouTube and summarize all result transcripts")
    p.add_argument("query", nargs="+", help="YouTube search query")
    p.add_argument("--limit", "-n", type=int, default=0, help=f"Max videos (default {DEFAULT_LIMIT}; or 'analyze N videos on …' in query)")
    p.add_argument("-q", "--question", help="Per-video summary instructions")
    p.add_argument("--merge-question", help="Final synthesis instructions")
    p.add_argument("--focus", "-f", help="Research question to answer in the final digest")
    p.add_argument("--show-items", action="store_true", help="Print each video summary")
    p.add_argument("--index", action="store_true", help="Index transcripts in TurboQuant for follow-up Q&A")
    p.add_argument("--ask", help="Follow-up question (requires --index)")
    p.set_defaults(func=cmd_research)

    p_list = sub.add_parser("list", help="List saved research sessions")
    p_list.set_defaults(func=cmd_list_sessions)

    p_ask = sub.add_parser("ask", help="Ask a follow-up about a saved session")
    p_ask.add_argument("session", help="Session id or slug fragment")
    p_ask.add_argument("question", nargs="+")
    p_ask.set_defaults(func=cmd_ask)

    p_links = sub.add_parser("links", help="Search YouTube and list video URLs only (fast, no LLM)")
    p_links.add_argument("query", nargs="+", help="YouTube search query")
    p_links.add_argument("--limit", "-n", type=int, default=8, help="Max results (default 8)")
    p_links.set_defaults(func=cmd_links)

    args = parser.parse_args()
    if args.cmd == "search":
        args.query = " ".join(args.query)
    elif args.cmd == "links":
        args.query = " ".join(args.query)
    elif args.cmd == "ask":
        args.question = " ".join(args.question)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
