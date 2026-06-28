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

from arka_batch_summarize import (
    DEFAULT_MAX_ITEMS,
    MERGE_QUESTION,
    PER_ITEM_QUESTION,
    _merge_digest,
    _summarize_transcript,
    _youtube_transcript,
)
from arka_media import _load_fish_env
from arka_progress import ProgressBar, progress_enabled
from arka_youtube import youtube_search

CACHE = Path.home() / ".cache" / "fish-agent" / "youtube-research"
DEFAULT_LIMIT = int(os.environ.get("ARKA_YT_RESEARCH_MAX", "12"))

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
        from arka_turboquant_rag import index_media_transcript, use_turboquant
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
    from arka_llm import llm_complete
    from arka_media_qa import answer_system_prompt
    from arka_turboquant_rag import _media_store

    store = _media_store(slug)
    if not store.chunks:
        return ""
    ctx = store.search(question, max_chars=14000)
    if not ctx.strip():
        return ""
    return llm_complete(
        answer_system_prompt(question),
        f"Context:\n{ctx}\n\nQuestion: {question}",
    ).strip()


def cmd_check(_args: argparse.Namespace) -> int:
    _load_fish_env()
    os.environ.setdefault("ARKA_YT_SKIP_TRANSCRIPT_API", "1")
    os.environ.setdefault("ARKA_YT_WHISPER_FALLBACK", "auto")
    os.environ.setdefault("ARKA_YT_PLAYER_CLIENT", "android_vr")

    from arka_youtube import (
        _node_js_runtime_args,
        _ytdlp_path,
        _yt_env,
        fetch_transcript_with_source,
    )

    print("━━━ YouTube transcript check ━━━")
    ytdlp = _ytdlp_path()
    print(f"yt-dlp: {ytdlp or 'NOT FOUND'}")
    print(f"node runtime: {'yes' if _node_js_runtime_args() else 'no (install node for better yt-dlp)'}")
    print(f"player client: {_yt_env('ARKA_YT_PLAYER_CLIENT', 'android_vr')}")
    print(f"whisper fallback: {_yt_env('ARKA_YT_WHISPER_FALLBACK', 'auto')}")
    print(f"skip caption API: {_yt_env('ARKA_YT_SKIP_TRANSCRIPT_API', '1')}")
    test_id = _yt_env("ARKA_YT_TEST_VIDEO", "Uwmp16aSgdk")
    print(f"\nTesting transcript fetch: {test_id}")
    text, src = fetch_transcript_with_source(test_id)
    if text:
        print(f"OK — source={src}, words={len(text.split())}")
        return 0
    print("FAILED — captions blocked; ensure GROQ_API_KEY or SARVAM_API_KEY for whisper STT", file=sys.stderr)
    return 1


def cmd_research(args: argparse.Namespace) -> int:
    _load_fish_env()
    os.environ.setdefault("ARKA_YT_SKIP_TRANSCRIPT_API", "1")
    os.environ.setdefault("ARKA_YT_WHISPER_FALLBACK", "auto")
    os.environ.setdefault("ARKA_YT_PLAYER_CLIENT", "android_vr")

    query = args.query.strip()
    if not query:
        print("Provide a YouTube search query.", file=sys.stderr)
        return 1

    limit = args.limit or DEFAULT_LIMIT
    if limit > DEFAULT_MAX_ITEMS and not args.limit:
        limit = DEFAULT_MAX_ITEMS

    _emit(f"Searching YouTube: {query!r} (up to {limit} videos)")
    try:
        hits = youtube_search(query, limit=limit)
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
    bar = ProgressBar("YouTube research", total=len(hits)) if progress_enabled() else None

    for i, (vid, title, channel) in enumerate(hits, start=1):
        label = title or vid
        sub = f" ({channel})" if channel else ""
        display = f"{label}{sub}"
        if bar is not None:
            bar.set(i - 1, total=len(hits), label=label[:36])
        else:
            _emit(f"[{i}/{len(hits)}] {display}")

        row: dict = {
            "video_id": vid,
            "title": title,
            "channel": channel,
            "url": f"https://youtube.com/watch?v={vid}",
        }
        try:
            text = _youtube_transcript(vid)
            row["transcript_source"] = "captions"
            row["transcript_words"] = len(text.split())
            row["transcript"] = text
            summary = _summarize_transcript(text, display, per_q, None)
            row["summary"] = summary
            items.append((display, summary))
            if args.show_items or not progress_enabled():
                print(f"\n── {display} ──\n{summary}\n", file=sys.stderr if progress_enabled() else sys.stdout)
        except Exception as exc:
            row["error"] = str(exc)
            print(f"Skipped {display}: {exc}", file=sys.stderr)

        session_entries.append(row)

    if bar is not None:
        bar.set(len(hits), total=len(hits), label="Synthesizing")

    ok_items = [(l, s) for l, s in items]
    if not ok_items:
        print("No transcripts available for any search result.", file=sys.stderr)
        print(
            "Tips: export ARKA_YT_SKIP_TRANSCRIPT_API=1  "
            "ARKA_YT_COOKIES_BROWSER=chrome  "
            "ARKA_YT_COOKIES=~/.config/fish/youtube-cookies.txt  "
            "ARKA_YT_WHISPER_FALLBACK=1",
            file=sys.stderr,
        )
        return 1

    digest = _merge_digest(ok_items, merge_q)
    if bar is not None:
        bar.done("Done")

    skipped = len(hits) - len(ok_items)
    print("━━━ YouTube research ━━━")
    print(f"Query: {query}")
    print(f"Videos: {len(ok_items)} summarized" + (f", {skipped} skipped (no captions)" if skipped else ""))
    print()
    print(digest)

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


def main() -> int:
    _load_fish_env()
    parser = argparse.ArgumentParser(description="YouTube search → transcript → research digest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="Search YouTube and summarize all result transcripts")
    p.add_argument("query", nargs="+", help="YouTube search query")
    p.add_argument("--limit", "-n", type=int, default=0, help=f"Max videos (default {DEFAULT_LIMIT})")
    p.add_argument("-q", "--question", help="Per-video summary instructions")
    p.add_argument("--merge-question", help="Final synthesis instructions")
    p.add_argument("--focus", "-f", help="Research question to answer in the final digest")
    p.add_argument("--show-items", action="store_true", help="Print each video summary")
    p.add_argument("--index", action="store_true", help="Index transcripts in TurboQuant for follow-up Q&A")
    p.add_argument("--ask", help="Follow-up question (requires --index)")
    p.set_defaults(func=cmd_research)

    p_list = sub.add_parser("list", help="List saved research sessions")
    p_list.set_defaults(func=cmd_list_sessions)

    p_check = sub.add_parser("check", help="Verify yt-dlp + transcript/whisper pipeline")
    p_check.set_defaults(func=cmd_check)

    p_ask = sub.add_parser("ask", help="Ask a follow-up about a saved session")
    p_ask.add_argument("session", help="Session id or slug fragment")
    p_ask.add_argument("question", nargs="+")
    p_ask.set_defaults(func=cmd_ask)

    args = parser.parse_args()
    if args.cmd == "search":
        args.query = " ".join(args.query)
    elif args.cmd == "ask":
        args.question = " ".join(args.question)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
