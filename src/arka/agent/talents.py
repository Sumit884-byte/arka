#!/usr/bin/env python3
"""Arka talents: unified ask, semantic memory, speak_research, voice_session, handoff_notify, predictions."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from arka.agent.core import (
    CACHE,
    FISH_DIR,
    HANDOFF_FILE,
    MEMORY_FILE,
    _llm,
    _py,
    load_json,
    memory_context_for,
    memory_remember,
    research,
    save_json,
)

from arka.agent.voice import (
    voice_ack,
    voice_format,
    voice_help,
    voice_prepare,
    voice_progress,
    voice_session_clear as _voice_clear,
    voice_session_enrich,
    voice_session_record as _voice_record,
    voice_session_status as _voice_status,
)

NOTIFY_FILE = CACHE / "handoff_notifications.json"
MEMORY_INDEX_SLUG = "agent-memory"


def _load_fish_env() -> None:
    try:
        import arka.paths as arka_paths

        arka_paths.load_env_file()
        return
    except ImportError:
        pass
    env_path = FISH_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def _wants_youtube(question: str) -> bool:
    q = question.lower()
    return bool(
        re.search(r"\b(youtube|yt\b|video reviews?|summarize.*videos?)\b", q)
        or re.search(r"\bresearch.*(on|from)\s+youtube\b", q)
    )


def _strip_youtube_prefix(question: str) -> str:
    q = question.strip()
    for pat in (
        r"^(?:research|summarize|search)\s+(?:on\s+)?youtube\s+(?:videos?\s+)?(?:about\s+|on\s+|for\s+)?",
        r"^youtube\s+(?:research|videos?)\s+(?:about\s+|on\s+|for\s+)?",
    ):
        q = re.sub(pat, "", q, flags=re.I).strip()
    return q or question.strip()


def memory_reindex() -> bool:
    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list) or not items:
        return False
    try:
        from arka.stock.turboquant_rag import index_media_transcript, use_turboquant
    except ImportError:
        return False
    if not use_turboquant():
        return False
    body = "\n\n".join(
        f"Memory {row.get('id', '?')} ({row.get('when', '')}): {row.get('text', '')}"
        for row in items
    )
    return bool(index_media_transcript(body, MEMORY_INDEX_SLUG))


def memory_semantic_context(query: str, *, limit_chars: int = 3500) -> str:
    try:
        from arka.integrations.supermemory import context_for

        return context_for(query, limit_chars=limit_chars)
    except ImportError:
        pass
    try:
        from arka.stock.turboquant_rag import _media_store, use_turboquant
    except ImportError:
        return memory_context_for(query)
    if not use_turboquant():
        return memory_context_for(query)
    store = _media_store(MEMORY_INDEX_SLUG)
    if not store.chunks:
        memory_reindex()
        store = _media_store(MEMORY_INDEX_SLUG)
    if store.chunks:
        ctx = store.search(query, max_chars=limit_chars)
        if ctx.strip():
            return "Relevant memories (semantic):\n" + ctx.strip()
    return memory_context_for(query)


def semantic_remember(text: str, *, tags: list[str] | None = None) -> None:
    memory_remember(text, tags=tags)
    if memory_reindex():
        print("Indexed in TurboQuant for semantic recall.", file=sys.stderr)


def unified_ask(
    question: str,
    *,
    deep: bool = False,
    youtube: bool = False,
    doc: str | None = None,
    speak: bool = False,
) -> str:
    question = question.strip()
    if not question:
        return ""

    contexts: list[str] = []
    sources_used: list[str] = []

    mem = memory_semantic_context(question)
    if mem:
        contexts.append(mem)
        sources_used.append("memory")

    try:
        from arka.stock.turboquant_rag import search_documents, use_turboquant

        if use_turboquant():
            code, ctx = search_documents(question, artifact=doc)
            if code == 0 and ctx.strip():
                contexts.append(f"[Your documents / codebase]\n{ctx[:9000]}")
                sources_used.append("turboquant")
    except Exception:
        pass

    yt_query = _strip_youtube_prefix(question)
    if youtube or _wants_youtube(question):
        try:
            from arka.youtube.research import cmd_research
            import io
            from contextlib import redirect_stdout

            limit = int(os.environ.get("ARKA_ASK_YT_LIMIT", "4"))
            args = argparse.Namespace(
                query=yt_query,
                limit=limit,
                question="",
                merge_question="",
                focus=question if not _wants_youtube(question) else "",
                show_items=False,
                index=False,
                ask="",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                if cmd_research(args) == 0:
                    yt_out = buf.getvalue()
                    digest = yt_out.split("━━━ YouTube research ━━━", 1)
                    if len(digest) > 1:
                        contexts.append(f"[YouTube research]\n{digest[1][:10000]}")
                        sources_used.append("youtube")
        except Exception as exc:
            contexts.append(f"[YouTube research unavailable: {exc}]")

    try:
        if deep:
            from arka.agent.chat import scrape_search_results

            web = scrape_search_results(question, min_words=350)
            if web:
                contexts.append(f"[Web search]\n{web[:9000]}")
                sources_used.append("web-deep")
        else:
            from arka.agent.chat import snippet_lookup

            snip = snippet_lookup(question)
            if snip:
                contexts.append(f"[Web snippet]\n{snip}")
                sources_used.append("web")
            if not snip or deep:
                from arka.agent.chat import scrape_search_results

                web = scrape_search_results(question, min_words=200, hard_limit=4)
                if web:
                    contexts.append(f"[Web search]\n{web[:6000]}")
                    if "web" not in sources_used:
                        sources_used.append("web")
    except Exception:
        pass

    if not contexts:
        answer = _llm(
            "Answer helpfully and concisely. Say if you are unsure.",
            question,
        )
    else:
        src_line = ", ".join(sources_used) if sources_used else "general"
        system = (
            "You are Arka, a unified personal assistant. Synthesize ALL provided sources. "
            "Cite source types in parentheses: (memory), (docs), (youtube), (web). "
            "Be direct and accurate; do not invent facts absent from sources."
        )
        user = (
            f"Sources used: {src_line}\n\n"
            + "\n\n---\n\n".join(contexts)
            + f"\n\nQuestion: {question}"
        )
        answer = _llm(system, user)

    if not answer:
        answer = "I couldn't generate an answer. Check LLM API keys."

    print("━━━ Answer ━━━")
    print(answer)
    if sources_used:
        print(f"\n[Sources: {', '.join(sources_used)}]", file=sys.stderr)

    if speak:
        tts_text = _llm(
            "Rewrite for spoken TTS in 2-4 short sentences. Same language as input. No markdown.",
            answer[:4000],
            0.1,
        ) or answer[:450]
        _speak(tts_text)

    return answer


def _speak(text: str) -> None:
    text = re.sub(r"\s+", " ", text.strip())[:500]
    if not text:
        return
    subprocess.run(
        ["fish", "-ic", f"speak_aloud {shlex.quote(text)}"],
        capture_output=True,
        text=True,
        timeout=120,
    )


def speak_research(query: str, *, limit: int = 5, speak: bool = True) -> int:
    _load_fish_env()
    os.environ.setdefault("ARKA_YT_WHISPER_FALLBACK", "auto")

    py = _py()
    from arka.paths import entry_script

    proc = subprocess.run(
        [py, str(entry_script("arka_youtube_research.py")), "search", query, "--limit", str(limit)],
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("ARKA_SPEAK_RESEARCH_TIMEOUT", "3600")),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    print(proc.stdout or "", end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")

    if proc.returncode != 0:
        return proc.returncode

    digest = out
    if "━━━ YouTube research ━━━" in out:
        digest = out.split("━━━ YouTube research ━━━", 1)[1]

    if speak:
        lang_hint = os.environ.get("ARKA_SPEAK_LANG", "hi-IN")
        tts = _llm(
            f"Summarize this YouTube research for spoken TTS in language matching {lang_hint}. "
            "3-6 short sentences, conversational, no markdown, no bullet symbols.",
            digest[:8000],
            0.15,
        )
        if tts:
            print("\n━━━ Speaking ━━━", file=sys.stderr)
            _speak(tts)
    return 0


# ── Voice session (see arka_voice.py) ─────────────────────────────────────────

def voice_session_clear() -> None:
    print(_voice_clear())


def voice_session_record(user_text: str, assistant_text: str) -> None:
    _voice_record(user_text, assistant_text)


def voice_session_status() -> None:
    print(_voice_status())


# ── Handoff notify ────────────────────────────────────────────────────────────

def _speak_text_from_result(result: str) -> str:
    return voice_format(result)


def handoff_notify_item(item: dict) -> None:
    notifs = load_json(NOTIFY_FILE, [])
    if not isinstance(notifs, list):
        notifs = []
    speak_text = _speak_text_from_result(str(item.get("result") or ""))
    if not speak_text and item.get("status") == "done":
        speak_text = f"Finished: {item.get('text', 'task')[:120]}"
    entry = {
        "id": item.get("id"),
        "task": item.get("text", ""),
        "status": item.get("status"),
        "speak_text": speak_text,
        "result_preview": str(item.get("result") or "")[:500],
        "when": datetime.now().isoformat(timespec="seconds"),
        "read": False,
    }
    notifs.append(entry)
    save_json(NOTIFY_FILE, notifs[-30:])

    title = "Arka handoff done" if item.get("status") == "done" else "Arka handoff failed"
    body = speak_text[:200] if speak_text else item.get("text", "")[:200]
    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "-a", "Arka", title, body],
            capture_output=True,
            timeout=5,
        )


def handoff_notifications_list(*, unread_only: bool = False) -> list[dict]:
    notifs = load_json(NOTIFY_FILE, [])
    if not isinstance(notifs, list):
        return []
    if unread_only:
        return [n for n in notifs if not n.get("read")]
    return notifs


def handoff_notifications_mark_read(nid: str | None = None) -> None:
    notifs = load_json(NOTIFY_FILE, [])
    if not isinstance(notifs, list):
        return
    for n in notifs:
        if nid is None or n.get("id") == nid:
            n["read"] = True
    save_json(NOTIFY_FILE, notifs)


def handoff_run_with_notify(*, limit: int = 3) -> int:
    from arka.agent.core import handoff_run

    q_before = load_json(HANDOFF_FILE, [])
    if not isinstance(q_before, list):
        q_before = []
    pending_ids = {i.get("id") for i in q_before if i.get("status") == "pending"}

    handoff_run(limit=limit)

    q_after = load_json(HANDOFF_FILE, [])
    if not isinstance(q_after, list):
        return 0
    for item in q_after:
        if item.get("id") in pending_ids and item.get("status") in {"done", "failed"}:
            handoff_notify_item(item)
    return 0


def main() -> int:
    _load_fish_env()
    parser = argparse.ArgumentParser(description="Arka talents")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ask", help="Unified ask: memory + RAG + web + optional YouTube")
    p.add_argument("question", nargs="+")
    p.add_argument("--deep", action="store_true")
    p.add_argument("--youtube", "-y", action="store_true")
    p.add_argument("--doc", default="")
    p.add_argument("--speak", action="store_true")

    p = sub.add_parser("speak-research")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", "-n", type=int, default=5)
    p.add_argument("--no-speak", action="store_true")

    p = sub.add_parser("semantic-remember")
    p.add_argument("text")
    p.add_argument("--tag", action="append", default=[])

    p = sub.add_parser("semantic-recall")
    p.add_argument("query")

    sub.add_parser("memory-reindex")

    p = sub.add_parser("voice-enrich")
    p.add_argument("text")

    p = sub.add_parser("voice-prepare")
    p.add_argument("text")

    p = sub.add_parser("voice-field")
    p.add_argument("field", choices=["action", "route_text", "llm_context", "ack"])
    p.add_argument("text")

    p = sub.add_parser("voice-format")
    p.add_argument("text")

    p = sub.add_parser("voice-ack")
    p.add_argument("text")

    p = sub.add_parser("voice-progress")
    p.add_argument("--skill", required=True)

    sub.add_parser("voice-help")

    p = sub.add_parser("voice-record")
    p.add_argument("--user", required=True)
    p.add_argument("--assistant", required=True)

    sub.add_parser("voice-clear")
    sub.add_parser("voice-status")

    sub.add_parser("handoff-run-notify")
    p = sub.add_parser("handoff-notify-list")
    p.add_argument("--unread", action="store_true")

    p = sub.add_parser("handoff-notify-read")
    p.add_argument("id", nargs="?", default="")

    p = sub.add_parser("predict", help="Opportunity predictions: antiques, stocks, strategy")
    p.add_argument("query", nargs="*")
    p.add_argument("--domain", "-d", default="auto", choices=["auto", "antiques", "stocks", "strategy", "all"])
    p.add_argument("--deep", action="store_true")
    p.add_argument("--horizon", default=os.environ.get("ARKA_PREDICT_HORIZON", "3-6 months"))
    p.add_argument("--history", action="store_true", help="List past predictions instead of running")
    p.add_argument("--limit", "-n", type=int, default=10)

    args = parser.parse_args()

    if args.cmd == "ask":
        unified_ask(
            " ".join(args.question),
            deep=args.deep,
            youtube=args.youtube,
            doc=args.doc or None,
            speak=args.speak,
        )
    elif args.cmd == "speak-research":
        return speak_research(" ".join(args.query), limit=args.limit, speak=not args.no_speak)
    elif args.cmd == "semantic-remember":
        semantic_remember(args.text, tags=args.tag)
    elif args.cmd == "semantic-recall":
        ctx = memory_semantic_context(args.query)
        print(ctx or "No matching memories.")
    elif args.cmd == "memory-reindex":
        ok = memory_reindex()
        print("Memory index updated." if ok else "Memory index skipped (TurboQuant off or empty).")
    elif args.cmd == "voice-enrich":
        print(voice_session_enrich(args.text))
    elif args.cmd == "voice-prepare":
        print(json.dumps(voice_prepare(args.text), ensure_ascii=False))
    elif args.cmd == "voice-field":
        prep = voice_prepare(args.text)
        print(prep.get(args.field, ""))
    elif args.cmd == "voice-format":
        print(voice_format(args.text))
    elif args.cmd == "voice-ack":
        print(voice_ack(args.text))
    elif args.cmd == "voice-progress":
        print(voice_progress(args.skill))
    elif args.cmd == "voice-help":
        print(voice_help())
    elif args.cmd == "voice-record":
        voice_session_record(args.user, args.assistant)
    elif args.cmd == "voice-clear":
        voice_session_clear()
    elif args.cmd == "voice-status":
        voice_session_status()
    elif args.cmd == "handoff-run-notify":
        return handoff_run_with_notify()
    elif args.cmd == "handoff-notify-list":
        for row in handoff_notifications_list(unread_only=args.unread):
            mark = " " if row.get("read") else "*"
            print(f"{mark} [{row.get('status')}] {row.get('id')}  {row.get('when')}")
            print(f"  {row.get('task', '')[:100]}")
            if row.get("speak_text"):
                print(f"  → {row.get('speak_text', '')[:120]}")
    elif args.cmd == "handoff-notify-read":
        handoff_notifications_mark_read(args.id or None)
        print("Marked read.")
    elif args.cmd == "predict":
        from arka.stock.predictions import run_prediction, list_history

        if getattr(args, "history", False):
            list_history(getattr(args, "limit", 10))
        elif not args.query:
            print("Usage: predict [--domain antiques|stocks|strategy] [--deep] <question>", file=sys.stderr)
            return 1
        else:
            domain = args.domain if args.domain != "auto" else "auto"
            result = run_prediction(
                " ".join(args.query),
                domain=domain,
                deep=args.deep,
                horizon=args.horizon,
            )
            print(result)
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
