#!/usr/bin/env python3
"""Summarize a folder of media files or a YouTube playlist."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from arka.media.transcript import (
    MEDIA_EXTENSIONS,
    _load_cached_transcript,
    _load_fish_env,
    summarize_text,
    transcribe_file,
)
from arka.core.progress import ProgressBar, progress_enabled
from arka.youtube.transcript import (
    _ytdlp_path,
    confirm_download_transcribe,
    extract_video_id,
    fetch_transcript_text,
    fetch_transcript_with_source,
)

DEFAULT_MAX_ITEMS = int(os.environ.get("BATCH_MAX_ITEMS", "25"))
YT_FETCH_DELAY = float(os.environ.get("YT_RESEARCH_DELAY", "2") or "0")
PER_ITEM_QUESTION = (
    "Summarize this video or audio in 3–6 bullet points. "
    "Include title/theme, main characters or speakers, and key events or ideas."
)
MERGE_QUESTION = (
    "Combine these per-item summaries into one cohesive digest. "
    "Use a short intro, then grouped bullets or sections by theme. "
    "Note recurring themes and how items relate. Keep it concise (~300 words unless asked otherwise."
)


def _emit(msg: str) -> None:
    if not progress_enabled():
        print(msg, file=sys.stderr)


def _discover_media(folder: Path, *, recursive: bool) -> list[Path]:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise SystemExit(f"Not a directory: {folder}")
    out: list[Path] = []
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    for path in sorted(iterator):
        if not path.is_file():
            continue
        if path.suffix.lower() in MEDIA_EXTENSIONS:
            out.append(path)
    return out


def _playlist_entries(url: str, limit: int | None) -> list[tuple[str, str]]:
    ytdlp = _ytdlp_path()
    if not ytdlp:
        raise SystemExit("yt-dlp not found — install yt-dlp or use youtube_bulk project venv")
    url = url.strip()
    if extract_video_id(url) and "list=" not in url.lower():
        vid = extract_video_id(url)
        return [(vid, url)]

    cmd = [ytdlp, "--no-update", "--flat-playlist", "--print", "%(id)s\t%(title)s", url]
    if limit and limit > 0:
        cmd.insert(1, f"--playlist-end={limit}")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "yt-dlp failed").strip()
        raise SystemExit(err[:500])
    entries: list[tuple[str, str]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        vid = vid.strip()
        if len(vid) == 11:
            entries.append((vid, title.strip()))
    if not entries:
        raise SystemExit(f"No playlist entries found for: {url}")
    if limit and limit > 0:
        entries = entries[:limit]
    return entries


def _research_allow_no_caption() -> bool:
    return os.environ.get("YT_RESEARCH_ALLOW_NO_CAPTION", "0").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _transcribe_override(args: argparse.Namespace) -> bool | None:
    if getattr(args, "no_transcribe", False):
        return False
    if getattr(args, "yes_transcribe", False):
        return True
    if _research_allow_no_caption():
        return True
    return None


def _summarize_transcript(text: str, label: str, question: str, src: Path | None) -> str:
    q = f"{question}\n\nItem: {label}"
    return summarize_text(text, q, src=src)


def _summarize_media_file(path: Path, question: str, *, retranscribe: bool) -> str:
    cached = None if retranscribe else _load_cached_transcript(path)
    if cached:
        _emit(f"  {path.name}: cached transcript ({len(cached.split())} words)")
        text = cached
    else:
        _emit(f"  {path.name}: transcribing…")
        text = transcribe_file(path)
    return _summarize_transcript(text, path.name, question, path)


def _merge_digest(items: list[tuple[str, str]], question: str) -> str:
    from arka.llm.cli import llm_complete

    if not items:
        return ""
    if len(items) == 1:
        return items[0][1]
    body = "\n\n".join(f"## {label}\n{summary}" for label, summary in items)
    user = f"User focus: {question}\n\nPer-item summaries:\n{body[:50000]}"
    return llm_complete(
        "You merge multiple media summaries into one readable digest.",
        user,
        temperature=0.2,
        task="research",
    ).strip()


def cmd_folder(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    files = _discover_media(folder, recursive=args.recursive)
    if not files:
        print(f"No media files found in {folder}", file=sys.stderr)
        return 1
    if args.limit and args.limit > 0:
        files = files[: args.limit]
    if len(files) > DEFAULT_MAX_ITEMS and not args.limit:
        print(f"Limiting to {DEFAULT_MAX_ITEMS} files (use --limit to override)", file=sys.stderr)
        files = files[:DEFAULT_MAX_ITEMS]

    per_q = args.question or PER_ITEM_QUESTION
    merge_q = args.merge_question or (args.question or MERGE_QUESTION)
    items: list[tuple[str, str]] = []
    bar = ProgressBar("Folder", total=len(files)) if progress_enabled() else None

    for i, path in enumerate(files, start=1):
        if bar is not None:
            bar.set(i - 1, total=len(files), label=f"→ {path.name[:32]}")
        else:
            _emit(f"[{i}/{len(files)}] {path.name}")
        try:
            summary = _summarize_media_file(path, per_q, retranscribe=args.retranscribe)
            items.append((path.name, summary))
            if not progress_enabled():
                print(f"\n── {path.name} ──\n{summary}\n", file=sys.stderr)
        except Exception as exc:
            print(f"Skipped {path.name}: {exc}", file=sys.stderr)
        finally:
            if bar is not None:
                bar.set(i, total=len(files), label=path.name[:36])

    if bar is not None:
        bar.set(len(files), total=len(files), label="Merging")
    if not items:
        print("No items summarized.", file=sys.stderr)
        return 1

    digest = _merge_digest(items, merge_q)
    if bar is not None:
        bar.done("Summarized")
    print("━━━ Folder digest ━━━")
    print(digest)
    return 0


def cmd_playlist(args: argparse.Namespace) -> int:
    if args.folder:
        return cmd_folder(argparse.Namespace(
            folder=args.folder,
            recursive=False,
            limit=args.limit,
            question=args.question,
            merge_question=args.merge_question,
            retranscribe=args.retranscribe,
            yes_transcribe=getattr(args, "yes_transcribe", False),
            no_transcribe=getattr(args, "no_transcribe", False),
        ))

    if not args.url:
        print("Provide --url PLAYLIST or --folder PATH", file=sys.stderr)
        return 1

    entries = _playlist_entries(args.url, args.limit or DEFAULT_MAX_ITEMS)
    per_q = args.question or PER_ITEM_QUESTION
    merge_q = args.merge_question or (args.question or MERGE_QUESTION)
    transcribe = _transcribe_override(args)
    items: list[tuple[str, str]] = []
    pending: list[tuple[str, str]] = []
    bar = ProgressBar("Playlist", total=len(entries)) if progress_enabled() else None

    for i, (vid, title) in enumerate(entries, start=1):
        label = title or vid
        if bar is not None:
            bar.set(i - 1, total=len(entries), label=f"→ {label[:32]}")
        else:
            _emit(f"[{i}/{len(entries)}] {label}")
        try:
            text, source = fetch_transcript_with_source(vid, research=True, allow_whisper=False)
            if text:
                summary = _summarize_transcript(text, label, per_q, None)
                items.append((label, summary))
                if not progress_enabled():
                    print(f"\n── {label} ──\n{summary}\n", file=sys.stderr)
            else:
                pending.append((vid, label))
        except Exception as exc:
            print(f"Skipped {label}: {exc}", file=sys.stderr)
        finally:
            if bar is not None:
                bar.set(i, total=len(entries), label=label[:36])

    if pending:
        do_transcribe = transcribe
        if do_transcribe is None:
            do_transcribe = confirm_download_transcribe(
                pending[0][1],
                count=len(pending),
            )
        if do_transcribe:
            tbar = ProgressBar("Transcribe", total=len(pending)) if progress_enabled() else None
            for j, (vid, label) in enumerate(pending, start=1):
                if tbar is not None:
                    tbar.set(j - 1, label=f"→ {label[:32]}")
                try:
                    text = fetch_transcript_text(vid, research=True, allow_whisper=True)
                    if not text:
                        print(f"Skipped {label}: transcribe failed", file=sys.stderr)
                        continue
                    summary = _summarize_transcript(text, label, per_q, None)
                    items.append((label, summary))
                    if not progress_enabled():
                        print(f"\n── {label} (transcribed) ──\n{summary}\n", file=sys.stderr)
                except Exception as exc:
                    print(f"Skipped {label}: {exc}", file=sys.stderr)
                finally:
                    if tbar is not None:
                        tbar.set(j, label=label[:36])
            if tbar is not None:
                tbar.done("Transcribed")
        else:
            for _vid, label in pending:
                print(f"Skipped {label}: no captions", file=sys.stderr)

    if bar is not None:
        bar.set(len(entries), total=len(entries), label="Merging…")
    if not items:
        print("No playlist items summarized.", file=sys.stderr)
        return 1

    digest = _merge_digest(items, merge_q)
    if bar is not None:
        bar.done("Summarized")
    print("━━━ Playlist digest ━━━")
    print(digest)
    return 0


def main() -> int:
    _load_fish_env()
    parser = argparse.ArgumentParser(description="Summarize media folders or YouTube playlists")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_folder = sub.add_parser("folder", help="Summarize all media in a directory")
    p_folder.add_argument("folder")
    p_folder.add_argument("-r", "--recursive", action="store_true")
    p_folder.add_argument("--limit", type=int, default=0)
    p_folder.add_argument("-q", "--question", help="Per-item summary focus")
    p_folder.add_argument("--merge-question", help="Final merge instructions")
    p_folder.add_argument("--retranscribe", action="store_true")
    p_folder.set_defaults(func=cmd_folder)

    p_pl = sub.add_parser("playlist", help="Summarize YouTube playlist URL or local playlist folder")
    p_pl.add_argument("--url", help="YouTube playlist URL")
    p_pl.add_argument("--folder", help="Local folder of downloaded playlist videos")
    p_pl.add_argument("--limit", type=int, default=0)
    p_pl.add_argument("-q", "--question")
    p_pl.add_argument("--merge-question")
    p_pl.add_argument("--retranscribe", action="store_true")
    p_pl.add_argument(
        "--yes-transcribe",
        action="store_true",
        help="Download + transcribe when captions missing (no prompt)",
    )
    p_pl.add_argument(
        "--no-transcribe",
        action="store_true",
        help="Skip videos without captions (never download audio)",
    )
    p_pl.set_defaults(func=cmd_playlist)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
