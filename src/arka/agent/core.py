#!/usr/bin/env python3
"""Arka agentic layer — memory, trace, research, watches, handoff, fanout, code agent."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from datetime import date, datetime
from pathlib import Path

CACHE = Path.home() / ".cache" / "fish-agent"
MEMORY_FILE = CACHE / "memory.json"
TRACE_FILE = CACHE / "trace.json"
LOOP_STATE_DIR = CACHE / "loop_states"
HANDOFF_FILE = CACHE / "handoff.json"
WATCH_FILE = CACHE / "watches.json"
ROUTINE_FILE = CACHE / "routines.json"
FISH_DIR = Path.home() / ".config" / "fish"
VENV_PY = FISH_DIR / "venv-arka" / "bin" / "python3"


def _py() -> str:
    return str(VENV_PY if VENV_PY.is_file() else sys.executable)


def load_json(path: Path, default: object) -> object:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _llm(system: str, user: str, temperature: float = 0.2, *, task: str = "agent") -> str:
    try:
        from arka.llm.cli import llm_complete

        out = llm_complete(system, user, temperature, task=task).strip()
        if out:
            return re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", out)
    except ImportError:
        pass
    from arka.paths import entry_script

    proc = subprocess.run(
        [_py(), str(entry_script("arka_llm.py")), "complete", "--system", system, "--user", user, "--temperature", str(temperature), "--task", task],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        return ""
    return re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", out.strip())


# ── Memory ────────────────────────────────────────────────────────────────────

def memory_remember(
    text: str,
    *,
    tags: list[str] | None = None,
    provenance: dict | None = None,
    trust_tier: str = "global",
) -> None:
    try:
        from arka.integrations.supermemory import remember_print

        remember_print(text, tags=tags, provenance=provenance, trust_tier=trust_tier)
        return
    except ImportError:
        pass
    except Exception as exc:
        if (os.environ.get("MEMORY") or "auto").strip().lower() in ("supermemory", "cloud", "api"):
            print(f"Supermemory error: {exc}", file=sys.stderr)
            raise

    if memory_remember_silent(
        text,
        tags=tags,
        source="cli",
        provenance=provenance,
        trust_tier=trust_tier,
    ):
        items = load_json(MEMORY_FILE, [])
        if isinstance(items, list) and items:
            print(f"Remembered ({items[-1].get('id', '?')}): {text[:120]}")
        else:
            print(f"Remembered: {text[:120]}")


def memory_remember_silent(
    text: str,
    *,
    tags: list[str] | None = None,
    source: str = "auto",
    provenance: dict | None = None,
    trust_tier: str = "global",
) -> bool:
    """Store a memory without printing. Returns True if stored."""
    text = text.strip()
    if not text:
        return False
    tier = (trust_tier or "global").strip().lower()
    if tier not in ("global", "team", "workflow", "run"):
        tier = "global"
    try:
        from arka.integrations.supermemory import remember

        remember(text, tags=tags, provenance=provenance, trust_tier=tier)
        return True
    except ImportError:
        pass
    except Exception as exc:
        if (os.environ.get("MEMORY") or "auto").strip().lower() in ("supermemory", "cloud", "api"):
            print(f"Supermemory error: {exc}", file=sys.stderr)
            raise

    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list):
        items = []
    entry = {
        "id": hashlib.sha256(f"{text}{time.time()}".encode()).hexdigest()[:12],
        "text": text,
        "tags": tags or [],
        "ts": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "trust_tier": tier,
    }
    if provenance:
        entry["provenance"] = provenance
    items.append(entry)
    save_json(MEMORY_FILE, items[-200:])
    try:
        import importlib

        mod = importlib.import_module("arka_talents")
        mod.memory_reindex()
    except Exception:
        pass
    return True


def memory_auto_detect(text: str, *, quiet: bool = True) -> list[str]:
    """Symbolically detect and store memorable facts from natural language."""
    try:
        from arka.core.memory_detect import auto_remember

        return auto_remember(text, quiet=quiet)
    except ImportError:
        return []


def memory_list(limit: int = 20) -> None:
    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list) or not items:
        print("No memories stored.")
        return
    for row in items[-limit:]:
        tags = ", ".join(row.get("tags") or [])
        tag_s = f" [{tags}]" if tags else ""
        print(f"{row.get('id', '?')}{tag_s}  {row.get('when', '')}")
        print(f"  {row.get('text', '')}")
        print()


def memory_recall(query: str, *, limit: int = 5) -> None:
    try:
        from arka.integrations.supermemory import recall

        recall(query, limit=limit)
        return
    except ImportError:
        pass
    except Exception as exc:
        if (os.environ.get("MEMORY") or "auto").strip().lower() in ("supermemory", "cloud", "api"):
            print(f"Supermemory error: {exc}", file=sys.stderr)
            raise

    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list) or not items:
        print("No memories.")
        return
    q = query.lower()
    scored: list[tuple[float, dict]] = []
    for row in items:
        text = (row.get("text") or "").lower()
        tags = " ".join(row.get("tags") or []).lower()
        score = 0.0
        for word in q.split():
            if len(word) < 2:
                continue
            if word in text:
                score += 2.0
            if word in tags:
                score += 1.5
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        print("No matching memories.")
        return
    for _, row in scored[:limit]:
        print(f"• {row.get('text', '')}")


def memory_forget(ref: str) -> None:
    try:
        from arka.integrations.supermemory import forget

        forget(ref)
        return
    except ImportError:
        pass

    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list):
        print("Nothing to forget.")
        return
    ref_l = ref.lower()
    kept = [r for r in items if ref_l not in (r.get("id") or "").lower() and ref_l not in (r.get("text") or "").lower()]
    if len(kept) == len(items):
        print(f"No memory matched: {ref}")
        return
    save_json(MEMORY_FILE, kept)
    print(f"Removed {len(items) - len(kept)} memory entries.")


def memory_context_for(goal: str, *, limit: int = 3) -> str:
    body = _memory_context_body(goal, limit=limit)
    rules = ""
    try:
        from arka.core.project_rules import context_for as project_rules_context

        rules = project_rules_context(goal, limit_chars=2000)
    except ImportError:
        pass
    if rules and body:
        return f"{rules}\n\n{body}"
    return rules or body


def _memory_context_body(goal: str, *, limit: int = 3) -> str:
    try:
        from arka.core.unified_memory import _enabled as unified_enabled
        from arka.core.unified_memory import recall as unified_recall

        if unified_enabled():
            ctx = unified_recall(goal, limit_chars=3500, include_channel=True)
            if ctx:
                return ctx
    except ImportError:
        pass

    try:
        from arka.integrations.supermemory import context_for

        ctx = context_for(goal, limit_chars=3500)
        if ctx:
            return ctx
    except ImportError:
        pass
    except Exception:
        pass

    session_ctx = ""
    try:
        from arka.core.session_memory import context_for as session_context_for

        session_ctx = session_context_for(goal)
    except ImportError:
        pass

    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list) or not items:
        if session_ctx:
            return session_ctx
        return _channel_memory_fallback()
    q = goal.lower()
    scored: list[tuple[float, str]] = []
    for row in items:
        text = row.get("text") or ""
        score = sum(1 for w in q.split() if len(w) > 2 and w in text.lower())
        if score:
            scored.append((score, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        if session_ctx:
            return session_ctx
        return _channel_memory_fallback()
    lines = [t for _, t in scored[:limit]]
    local = "Relevant memories:\n" + "\n".join(f"- {l}" for l in lines)
    if session_ctx:
        return session_ctx + "\n\n" + local
    return local


def _channel_memory_fallback() -> str:
    try:
        from arka.integrations.message_sessions import (
            _enabled,
            cli_channel,
            cli_chat_id,
            context_for,
        )

        if not _enabled():
            return ""
        ctx = context_for(cli_channel(), cli_chat_id())
        if ctx:
            return "Channel session (recent turns):\n" + ctx
    except ImportError:
        pass
    return ""


# ── Trace ─────────────────────────────────────────────────────────────────────

def trace_log(*, input_text: str, interpreted: str, source: str, why: str = "") -> None:
    entry = {
        "ts": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
        "input": input_text,
        "interpreted": interpreted,
        "source": source,
        "why": why,
    }
    save_json(TRACE_FILE, entry)
    hist = load_json(CACHE / "trace_history.json", [])
    if not isinstance(hist, list):
        hist = []
    hist.append(entry)
    save_json(CACHE / "trace_history.json", hist[-50:])


def trace_last() -> None:
    entry = load_json(TRACE_FILE, {})
    if not isinstance(entry, dict) or not entry:
        print("No routing trace yet.")
        return
    print(f"When:   {entry.get('when', '?')}")
    print(f"Input:  {entry.get('input', '')}")
    print(f"Route:  {entry.get('interpreted', '')}")
    print(f"Source: {entry.get('source', '')}")
    if entry.get("why"):
        print(f"Why:    {entry.get('why')}")


def trace_why() -> None:
    entry = load_json(TRACE_FILE, {})
    if not isinstance(entry, dict) or not entry:
        print("No routing decision recorded.")
        return
    src = entry.get("source", "unknown")
    inp = entry.get("input", "")
    out = entry.get("interpreted", "")
    why = entry.get("why") or f"Routed via {src} matcher."
    print(f"You asked: {inp}")
    print(f"Arka chose: {out}")
    print(f"Because: {why}")


# ── Loop resume state ─────────────────────────────────────────────────────────

def loop_save(goal: str, *, cwd: str, history: str, iter_n: int, max_iter: int) -> str:
    LOOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    sid = hashlib.sha256(f"{goal}{cwd}{time.time()}".encode()).hexdigest()[:10]
    state = {
        "id": sid,
        "goal": goal,
        "cwd": cwd,
        "history": history,
        "iter": iter_n,
        "max_iter": max_iter,
        "ts": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
    }
    path = LOOP_STATE_DIR / f"{sid}.json"
    save_json(path, state)
    save_json(LOOP_STATE_DIR / "latest.json", state)
    return sid


def loop_list() -> None:
    LOOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    states = sorted(LOOP_STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    states = [p for p in states if p.name != "latest.json"]
    if not states:
        print("No saved loop states.")
        return
    for path in states[:10]:
        data = load_json(path, {})
        if isinstance(data, dict):
            print(f"{data.get('id', path.stem)}  step {data.get('iter', '?')}/{data.get('max_iter', '?')}  {data.get('when', '')}")
            print(f"  {data.get('goal', '')[:80]}")
            print()


def loop_load(ref: str | None = None) -> dict | None:
    LOOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if ref in (None, "", "latest"):
        data = load_json(LOOP_STATE_DIR / "latest.json", None)
        return data if isinstance(data, dict) else None
    path = LOOP_STATE_DIR / f"{ref}.json"
    if not path.is_file():
        for p in LOOP_STATE_DIR.glob("*.json"):
            data = load_json(p, {})
            if isinstance(data, dict) and data.get("id") == ref:
                return data
    data = load_json(path, None)
    return data if isinstance(data, dict) else None


def loop_clear(ref: str | None = None) -> None:
    if ref in (None, "", "all"):
        for p in LOOP_STATE_DIR.glob("*.json"):
            p.unlink(missing_ok=True)
        print("Cleared all loop states.")
        return
    (LOOP_STATE_DIR / f"{ref}.json").unlink(missing_ok=True)
    print(f"Cleared loop state {ref}.")


def loop_verify(goal: str, history: str) -> tuple[bool, str]:
    system = (
        "You verify whether a shell agent loop achieved its goal. "
        "Reply with JSON only: {\"done\": true|false, \"summary\": \"brief explanation\"}"
    )
    user = f"GOAL:\n{goal}\n\nEXECUTION HISTORY:\n{history[-8000:]}\n\nWas the goal fully achieved?"
    raw = _llm(system, user, 0.1)
    if not raw:
        return False, "Could not verify (LLM unavailable)."
    try:
        data = json.loads(raw)
        return bool(data.get("done")), str(data.get("summary") or "")
    except json.JSONDecodeError:
        done = "true" in raw.lower() and "false" not in raw.lower()
        return done, raw[:300]


# ── Handoff (phone ↔ PC task queue) ───────────────────────────────────────────

def handoff_add(text: str, *, source: str = "cli") -> None:
    q = load_json(HANDOFF_FILE, [])
    if not isinstance(q, list):
        q = []
    item = {
        "id": uuid.uuid4().hex[:10],
        "text": text.strip(),
        "source": source,
        "status": "pending",
        "created": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
    }
    q.append(item)
    save_json(HANDOFF_FILE, q)
    print(f"Handoff queued ({item['id']}): {text[:100]}")


def handoff_list() -> None:
    q = load_json(HANDOFF_FILE, [])
    if not isinstance(q, list) or not q:
        print("Handoff queue empty.")
        return
    for item in q[-20:]:
        print(f"[{item.get('status', '?')}] {item.get('id', '?')} ({item.get('source', '?')})  {item.get('when', '')}")
        print(f"  {item.get('text', '')}")
        if item.get("result"):
            print(f"  → {str(item.get('result', ''))[:120]}")
        print()


def handoff_run(*, limit: int = 3) -> None:
    q = load_json(HANDOFF_FILE, [])
    if not isinstance(q, list):
        print("Nothing to run.")
        return
    pending = [i for i in q if i.get("status") == "pending"][:limit]
    if not pending:
        print("No pending handoff tasks.")
        return
    for item in pending:
        text = item.get("text", "")
        print(f"━━━ Handoff {item.get('id')} ━━━", file=sys.stderr)
        proc = subprocess.run(
            ["fish", "-ic", f"agent {shlex.quote(text)}"],
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("HANDOFF_TIMEOUT", "600")),
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        item["status"] = "done" if proc.returncode == 0 else "failed"
        item["finished"] = time.time()
        item["exit_code"] = proc.returncode
        item["result"] = out[-2000:]
        print(out)
    save_json(HANDOFF_FILE, q)


def handoff_clear() -> None:
    save_json(HANDOFF_FILE, [])
    print("Handoff queue cleared.")


def handoff_api_add(text: str, source: str = "phone") -> dict:
    q = load_json(HANDOFF_FILE, [])
    if not isinstance(q, list):
        q = []
    item = {
        "id": uuid.uuid4().hex[:10],
        "text": text.strip(),
        "source": source,
        "status": "pending",
        "created": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
    }
    q.append(item)
    save_json(HANDOFF_FILE, q)
    return item


def handoff_api_list(status: str | None = None) -> list[dict]:
    q = load_json(HANDOFF_FILE, [])
    if not isinstance(q, list):
        return []
    if status:
        return [i for i in q if i.get("status") == status]
    return q


# ── Watch (condition → action) ────────────────────────────────────────────────

def _eval_watch_condition(cond: str) -> bool:
    cond = cond.strip()
    m = re.match(r"disk\s+([<>]=?)\s*(\d+)%", cond, re.I)
    if m:
        op, pct = m.group(1), int(m.group(2))
        usage = shutil.disk_usage("/")
        used_pct = int(100 * usage.used / usage.total)
        if op == ">":
            return used_pct > pct
        if op == ">=":
            return used_pct >= pct
        if op == "<":
            return used_pct < pct
        if op == "<=":
            return used_pct <= pct
    m = re.match(r"file\s+exists\s+(.+)", cond, re.I)
    if m:
        return Path(m.group(1).strip()).expanduser().is_file()
    m = re.match(r"process\s+(.+)", cond, re.I)
    if m:
        name = m.group(1).strip()
        proc = subprocess.run(["pgrep", "-f", name], capture_output=True)
        return proc.returncode == 0
    m = re.match(r"queue\s+pending\s+([<>]=?)\s*(\d+)", cond, re.I)
    if m:
        op, n = m.group(1), int(m.group(2))
        q = load_json(CACHE / "deep_queue.json", [])
        count = len([i for i in (q if isinstance(q, list) else []) if i.get("status") == "pending"])
        if op == ">":
            return count > n
        if op == ">=":
            return count >= n
    return False


def watch_add(condition: str, action: str, *, name: str = "") -> None:
    watches = load_json(WATCH_FILE, [])
    if not isinstance(watches, list):
        watches = []
    wid = name or hashlib.sha256(f"{condition}{action}".encode()).hexdigest()[:8]
    watches.append({
        "id": wid,
        "condition": condition,
        "action": action,
        "enabled": True,
        "last_run": None,
        "created": time.time(),
    })
    save_json(WATCH_FILE, watches)
    print(f"Watch added ({wid}): when [{condition}] → {action}")


def watch_list() -> None:
    watches = load_json(WATCH_FILE, [])
    if not isinstance(watches, list) or not watches:
        print("No watches.")
        return
    for w in watches:
        en = "on" if w.get("enabled", True) else "off"
        print(f"[{en}] {w.get('id', '?')}: {w.get('condition', '')} → {w.get('action', '')}")


def watch_run(*, dry: bool = False) -> None:
    watches = load_json(WATCH_FILE, [])
    if not isinstance(watches, list):
        return
    for w in watches:
        if not w.get("enabled", True):
            continue
        if not _eval_watch_condition(w.get("condition", "")):
            continue
        action = w.get("action", "")
        print(f"Watch {w.get('id')} triggered → {action}")
        if dry:
            continue
        subprocess.run(["fish", "-ic", action], timeout=300)
        w["last_run"] = time.time()
    save_json(WATCH_FILE, watches)


def watch_remove(wid: str) -> None:
    watches = load_json(WATCH_FILE, [])
    if not isinstance(watches, list):
        return
    kept = [w for w in watches if w.get("id") != wid]
    save_json(WATCH_FILE, kept)
    print(f"Removed watch {wid}." if len(kept) < len(watches) else f"No watch {wid}.")


# ── Routine (scheduled tasks) ─────────────────────────────────────────────────

from arka.integrations.routines import (  # noqa: E402
    routine_add,
    routine_install,
    routine_list,
    routine_remove,
    routine_run,
)


# ── Fanout (parallel jobs) ────────────────────────────────────────────────────

def fanout_run(jobs: list[str], *, merge_question: str | None = None) -> None:
    if not jobs:
        print("Usage: agent_fanout job1 job2 ...")
        return

    def _run_one(job: str) -> tuple[str, str]:
        proc = subprocess.run(
            ["fish", "-ic", job],
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("FANOUT_TIMEOUT", "900")),
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return job, out[-4000:]

    results: list[tuple[str, str]] = []
    workers = min(len(jobs), int(os.environ.get("FANOUT_WORKERS", "4")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for job, out in pool.map(_run_one, jobs):
            results.append((job, out))
            print(f"━━━ {job} ━━━")
            print(out)
            print()

    if merge_question and len(results) > 1:
        combined = "\n\n".join(f"### {j}\n{o}" for j, o in results)
        merged = _llm(
            "Merge parallel job outputs into one concise digest.",
            f"Merge instruction: {merge_question}\n\n{combined[:12000]}",
        )
        if merged:
            print("━━━ Merged digest ━━━")
            print(merged)


# ── Research (unified RAG + web + media) ──────────────────────────────────────

def _is_path(s: str) -> bool:
    p = Path(s).expanduser()
    return p.exists()


def _research_word_bounds() -> tuple[int, int]:
    from arka.env import env_get

    try:
        lo = int(env_get("RESEARCH_MIN_WORDS", "500"))
    except ValueError:
        lo = 500
    try:
        hi = int(env_get("RESEARCH_MAX_WORDS", "900"))
    except ValueError:
        hi = 900
    if hi < lo:
        hi = lo + 200
    return lo, hi


def _research_length_hint() -> str:
    lo, hi = _research_word_bounds()
    return (
        f"\nWrite a thorough research brief ({lo}–{hi} words). "
        "Use clear sections or numbered bullets. Explain benefits, traditional use, and caveats where relevant. "
        "Synthesize every source provided — do not stop after the first one. "
        "Use plain section titles (e.g. Sources) — not markdown # headings, asterisks, or bullets. "
        "End with one Source: line per site (e.g. Source: Example.com (via web search))."
    )


def _research_scrape_min_words(*, deep: bool) -> int:
    from arka.env import env_get

    default = "700" if deep else "400"
    try:
        return int(env_get("RESEARCH_SCRAPE_MIN_WORDS", default))
    except ValueError:
        return 700 if deep else 400


def _research_scrape_pages(*, deep: bool) -> int:
    from arka.env import env_get

    default = "10" if deep else "6"
    try:
        return int(env_get("RESEARCH_SCRAPE_PAGES", default))
    except ValueError:
        return 10 if deep else 6


def _research_mode(question: str) -> str:
    q = question.lower()
    if re.search(r"\b(meeting|standup|sync)\b", q):
        return "meeting"
    if re.search(r"\b(study|learn|exam|homework)\b", q):
        return "study"
    if re.search(r"\b(inbox|email|mail|unread)\b", q):
        return "inbox"
    if re.search(r"\bcompare|versus|vs\.?\b|difference between", q):
        return "compare"
    if re.search(r"\b(code|repo|function|class|implement)\b", q):
        return "dev"
    if re.search(r"\b(video|transcript|podcast|episode)\b", q):
        return "media"
    return "research"


def _specialist_prompt(mode: str, question: str) -> tuple[str, str]:
    prompts = {
        "meeting": (
            "You are a meeting assistant. Extract action items, decisions, owners, and deadlines.",
            question,
        ),
        "study": (
            "You are a study tutor. Explain clearly, use examples, and end with 3 review questions.",
            question,
        ),
        "inbox": (
            "You are an inbox triage assistant. Prioritize, summarize, and suggest replies.",
            question,
        ),
        "compare": (
            "Compare the topics factually. Use a table or bullet contrast. Cite sources when given.",
            question,
        ),
        "product": (
            "You are a product reviewer analyzing ingredients and product claims. "
            "Use only the provided authoritative sources (INCIDecoder, EWG Skin Deep, "
            "Paula's Choice Ingredient Dictionary, EU CosIng, USDA FoodData Central, "
            "Open Food Facts, FDA, PubMed, and brand ingredient lists as available). "
            "Structure: Summary, Key Ingredients, Concerns/Allergens, Answer to User's Question, "
            "Alternatives (if relevant). Flag uncertainty when sources disagree or data is incomplete. "
            "End with a Sources: section listing each source you relied on "
            "(e.g. Sources: INCIDecoder; EWG Skin Deep; PubMed). "
            "Not medical or dermatological advice — recommend patch-testing new products.",
            question,
        ),
        "dev": (
            "You are a senior developer. Answer with code references when context is provided.",
            question,
        ),
        "media": (
            "Answer from transcript/media context only. Be specific about speakers and events.",
            question,
        ),
    }
    return prompts.get(mode, (
        "You are a research assistant. Synthesize all provided sources into a structured, "
        "in-depth brief. Cite provenance; be thorough, not terse.",
        question,
    ))


def _research_web_context(question: str, *, deep: bool) -> str:
    from arka.agent.chat import scrape_search_results, snippet_lookup

    min_words = _research_scrape_min_words(deep=deep)
    pages = _research_scrape_pages(deep=deep)
    if deep:
        return scrape_search_results(question, min_words=min_words, hard_limit=pages)
    snip = snippet_lookup(question)
    if snip:
        return snip
    # Instant-answer API misses most topics — fall back to scraped search.
    return scrape_search_results(question, min_words=min_words, hard_limit=pages)


def research(
    question: str,
    *,
    doc: str | None = None,
    path: str | None = None,
    deep: bool = False,
    force_mode: str | None = None,
) -> None:
    mode = force_mode or _research_mode(question)
    if mode == "product":
        deep = True
    contexts: list[str] = []
    web_ctx = ""

    # TurboQuant docs
    if doc or mode in {"dev", "research", "compare", "product"}:
        try:
            from arka.stock.turboquant_rag import search_documents, use_turboquant

            if use_turboquant():
                code, ctx = search_documents(question, artifact=doc)
                if code == 0 and ctx.strip():
                    contexts.append(f"[TurboQuant docs]\n{ctx[:8000]}")
        except Exception:
            pass

    # Media transcript path
    media_path = path
    if not media_path:
        for token in question.split():
            if _is_path(token) and Path(token).expanduser().suffix.lower() in {
                ".mp4", ".mkv", ".mp3", ".wav", ".m4a", ".webm", ".mov"
            }:
                media_path = token
                break
    if media_path and Path(media_path).expanduser().is_file():
        try:
            from arka.media.transcript import _load_cached_transcript, transcribe_file
            from arka.media.qa import retrieve_transcript_context

            src = Path(media_path).expanduser()
            text = _load_cached_transcript(src) or transcribe_file(src, force=False)
            if text:
                ctx = retrieve_transcript_context(text, question, src=src)
                if ctx:
                    contexts.append(f"[Media transcript: {src.name}]\n{ctx[:8000]}")
        except Exception as exc:
            contexts.append(f"[Media error: {exc}]")

    # Web — product mode targets authoritative ingredient databases
    try:
        if mode == "product":
            from arka.agent.product_sources import fetch_product_web_context

            web_ctx, source_labels = fetch_product_web_context(question, deep=deep)
            if web_ctx:
                label = "[Product sources"
                if source_labels:
                    label += ": " + ", ".join(source_labels)
                label += "]"
                contexts.append(f"{label}\n{web_ctx[:8000]}")
        else:
            web_ctx = _research_web_context(question, deep=deep)
            if web_ctx:
                label = "[Web search]" if deep or len(web_ctx) > 400 else "[Web snippet]"
                contexts.append(f"{label}\n{web_ctx[:8000]}")
    except Exception:
        pass

    mem = memory_context_for(question)
    if mem:
        contexts.append(mem)

    has_primary = bool(web_ctx) or any(
        c.startswith("[TurboQuant") or c.startswith("[Media transcript") for c in contexts
    )
    if not has_primary:
        try:
            from arka.agent.chat import answer_question
            from arka.output import print_block

            _, answer = answer_question(question, deep=True, use_session=False, cleanup=True)
            if answer and not re.match(r"(?i)^could not ", answer.strip()):
                print_block("Research answer", answer)
                return
        except Exception:
            pass

    system, user_q = _specialist_prompt(mode, question)
    if mode == "research":
        system += (
            " Prefer web and document sources. Personal memories are background only — "
            "never claim memories are the only sources when the question is factual."
        )
        user_q += _research_length_hint()
    elif mode == "product":
        user_q += (
            "\nWrite a thorough product review (400–700 words). "
            "Cite which authoritative sources support each claim. "
            "If evidence is thin or conflicting, say so explicitly. "
            "End with a Sources: section naming every source used."
        )
    if contexts:
        user_q = f"Sources:\n\n" + "\n\n---\n\n".join(contexts) + f"\n\nQuestion: {user_q}"
    task = "research" if mode == "research" else "agent"
    answer = _llm(system, user_q, task=task)
    if not answer:
        print("Research failed — check LLM / embeddings.")
        return
    from arka.output import print_block

    title = "Research answer" if mode == "research" else f"{mode.title()} answer"
    print_block(title, answer)


def transcript_ask(path: str, question: str) -> None:
    research(question, path=path)


def compare_agent(a: str, b: str, *, context: str = "") -> None:
    q = f"Compare and contrast: {a} vs {b}"
    if context:
        q += f"\n\nContext:\n{context}"
    research(q, deep=True)


def product_reviewer(query: str) -> None:
    """Review product ingredients and claims using deep web research."""
    text = query.strip()
    if not text:
        print("Usage: product_reviewer <ingredients or product name> [what you want to know]")
        return
    research(text, deep=True, force_mode="product")


def price_check(query: str) -> None:
    """Look up current retail prices from scraped store listings."""
    text = query.strip()
    if not text:
        print("Usage: price_check <product> [e.g. macbook air m3 | iphone 16 price in india]")
        return

    from arka.agent.price_sources import (
        fetch_price_listings,
        format_price_check_output,
        parse_price_query,
    )
    from arka.output import print_block

    product, region = parse_price_query(text)
    if not product:
        print("Usage: price_check <product> [e.g. macbook air m3 | iphone 16 price in india]")
        return

    listings, source_labels = fetch_price_listings(product, region=region, deep=True)
    today = date.today().isoformat()
    output = format_price_check_output(
        listings,
        product=product,
        region=region,
        searched_labels=source_labels,
        retrieved_on=today,
    )
    print_block("Price check", output)


# ── Code agent ────────────────────────────────────────────────────────────────

def code_agent(goal: str, *, repo: str | None = None, ingest: bool = False) -> int:
    from arka.core.code_project import (
        CodeProjectError,
        apply_env,
        check_shell_scope,
        require_initialized,
    )

    try:
        project_root = require_initialized()
    except CodeProjectError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if repo:
        cwd = Path(repo).expanduser().resolve()
        try:
            cwd.relative_to(project_root)
        except ValueError:
            print(f"Repo {cwd} is outside code project {project_root}", file=sys.stderr)
            return 1
    else:
        cwd = project_root

    apply_env()
    os.chdir(cwd)
    doc_name = cwd.name
    if ingest:
        from arka.paths import entry_script

        proc = subprocess.run(
            [_py(), str(entry_script("arka_pdf_rag.py")), "codebase-ingest", str(cwd), "-n", doc_name],
            timeout=600,
        )
        if proc.returncode != 0:
            print("Codebase ingest failed.")
            return proc.returncode

    ctx = ""
    try:
        from arka.stock.turboquant_rag import search_documents, use_turboquant

        if use_turboquant():
            _, ctx = search_documents(goal, artifact=f"codebase-{doc_name}")
    except Exception:
        pass

    mem = memory_context_for(goal)
    plan_system = (
        "You are a repo-scoped coding agent. Return JSON only: "
        '{"steps":["shell command or skill", ...], "summary":"plan"}'
    )
    plan_user = f"Repo: {cwd}\nGoal: {goal}\n"
    if mem:
        plan_user += mem + "\n"
    if ctx:
        plan_user += f"Relevant code context:\n{ctx[:6000]}\n"
    plan_raw = _llm(plan_system, plan_user)
    steps: list[str] = []
    if plan_raw:
        try:
            data = json.loads(re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", plan_raw.strip()))
            steps = [str(s) for s in (data.get("steps") or []) if s]
            if data.get("summary"):
                print(f"Plan: {data['summary']}")
        except json.JSONDecodeError:
            pass
    if not steps:
        cmd = f"cd {shlex.quote(str(cwd))}; goal -n 10 {shlex.quote(goal)}"
        return subprocess.run(["fish", "-ic", cmd]).returncode

    os.chdir(cwd)
    for i, step in enumerate(steps, 1):
        print(f"━━━ Code step {i}/{len(steps)} ━━━")
        print(f"→ {step}")
        scope_ok, scope_reason = check_shell_scope(step, root=cwd)
        if not scope_ok:
            print(scope_reason, file=sys.stderr)
            return 1
        proc = subprocess.run(["fish", "-ic", step], cwd=cwd, timeout=300)
        if proc.returncode != 0:
            print(f"Step failed (exit {proc.returncode}).")
            return proc.returncode
    return 0


# ── Nudge (proactive hints) ───────────────────────────────────────────────────

def nudge(*, quiet: bool = False) -> None:
    hints: list[str] = []
    usage = shutil.disk_usage("/")
    used_pct = int(100 * usage.used / usage.total)
    if used_pct >= 90:
        hints.append(f"Disk {used_pct}% full — try: disk_breakdown")

    q = load_json(CACHE / "deep_queue.json", [])
    pending = len([i for i in (q if isinstance(q, list) else []) if i.get("status") == "pending"])
    if pending:
        hints.append(f"{pending} deep_queue task(s) pending — deep_queue run")

    handoff = load_json(HANDOFF_FILE, [])
    hp = len([i for i in (handoff if isinstance(handoff, list) else []) if i.get("status") == "pending"])
    if hp:
        hints.append(f"{hp} handoff task(s) — agent_handoff run")

    if not hints:
        if not quiet:
            print("All clear — no nudges.")
        return
    for h in hints:
        print(f"💡 {h}")


# ── Browser agent (goal-oriented web) ───────────────────────────────────────

def browser_agent(goal: str) -> None:
    """Plan web steps via LLM; fall back to browse_web skill."""
    system = (
        "Plan a short web research task. Return JSON: "
        '{"search_queries":["..."], "summary":"what to look for"}'
    )
    raw = _llm(system, goal)
    queries: list[str] = []
    if raw:
        try:
            data = json.loads(re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", raw.strip()))
            queries = [str(q) for q in (data.get("search_queries") or []) if q]
            if data.get("summary"):
                print(f"Goal: {data['summary']}")
        except json.JSONDecodeError:
            pass

    if queries:
        from arka.agent.chat import scrape_search_results

        merged = []
        for q in queries[:3]:
            page = scrape_search_results(q, min_words=200, hard_limit=4)
            if page:
                merged.append(page)
        if merged:
            answer = _llm(
                "Answer the user's web goal using only the scraped content.",
                f"Goal: {goal}\n\nContent:\n" + "\n\n".join(merged)[:12000],
            )
            if answer:
                print(answer)
                return

    subprocess.run(["fish", "-ic", f"browse_web {shlex.quote(goal)}"])


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Arka agentic features")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("remember")
    p.add_argument("text")
    p.add_argument("--tag", action="append", default=[])

    p = sub.add_parser("recall")
    p.add_argument("query")

    sub.add_parser("memory-list")

    p = sub.add_parser("forget")
    p.add_argument("ref")

    p = sub.add_parser("memory-context")
    p.add_argument("goal")

    p = sub.add_parser("memory-detect")
    p.add_argument("text")

    p = sub.add_parser("memory-auto")
    p.add_argument("text")
    p.add_argument("--verbose", action="store_true")

    p = sub.add_parser("trace-log")
    p.add_argument("--input", required=True)
    p.add_argument("--interpreted", required=True)
    p.add_argument("--source", default="unknown")
    p.add_argument("--why", default="")

    sub.add_parser("trace-last")
    sub.add_parser("trace-why")

    p = sub.add_parser("loop-save")
    p.add_argument("goal")
    p.add_argument("--cwd", required=True)
    p.add_argument("--history", default="")
    p.add_argument("--iter", type=int, required=True)
    p.add_argument("--max", type=int, required=True)

    sub.add_parser("loop-list")
    p = sub.add_parser("loop-load")
    p.add_argument("ref", nargs="?", default="latest")
    p = sub.add_parser("loop-clear")
    p.add_argument("ref", nargs="?", default="all")

    p = sub.add_parser("loop-verify")
    p.add_argument("goal")
    p.add_argument("--history", required=True)

    p = sub.add_parser("handoff-add")
    p.add_argument("text")
    p.add_argument("--source", default="cli")
    sub.add_parser("handoff-list")
    sub.add_parser("handoff-run")
    sub.add_parser("handoff-clear")

    p = sub.add_parser("watch-add")
    p.add_argument("condition")
    p.add_argument("action")
    p.add_argument("--name", default="")
    sub.add_parser("watch-list")
    p = sub.add_parser("watch-run")
    p.add_argument("--dry", action="store_true")
    p = sub.add_parser("watch-remove")
    p.add_argument("id")

    p = sub.add_parser("routine-add")
    p.add_argument("schedule")
    p.add_argument("action")
    p.add_argument("--name", default="")
    sub.add_parser("routine-list")
    sub.add_parser("routine-install")
    p = sub.add_parser("routine-remove")
    p.add_argument("id")

    p = sub.add_parser("fanout")
    p.add_argument("jobs", nargs="+")
    p.add_argument("--merge", default="")

    p = sub.add_parser("research")
    p.add_argument("question", nargs="+")
    p.add_argument("--doc", default="")
    p.add_argument("--path", default="")
    p.add_argument("--deep", action="store_true")

    p = sub.add_parser("transcript-ask")
    p.add_argument("path")
    p.add_argument("question", nargs="+")

    p = sub.add_parser("compare")
    p.add_argument("a")
    p.add_argument("b")

    p = sub.add_parser("code")
    p.add_argument("goal", nargs="+")
    p.add_argument("--repo", default="")
    p.add_argument("--ingest", action="store_true")

    p = sub.add_parser("nudge")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("browser")
    p.add_argument("goal", nargs="+")

    p = sub.add_parser("meeting")
    p.add_argument("notes", nargs="+")

    p = sub.add_parser("study")
    p.add_argument("topic", nargs="+")

    p = sub.add_parser("inbox")
    p.add_argument("text", nargs="+")

    p = sub.add_parser("product-reviewer")
    p.add_argument("query", nargs="+")

    p = sub.add_parser("price-check")
    p.add_argument("query", nargs="+")

    p = sub.add_parser("goal")
    p.add_argument("goal", nargs="*")
    p.add_argument("-n", "--max", type=int, default=None)
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("-v", "--verify", action="store_true")
    p.add_argument("--butterfish", action="store_true")
    p.add_argument("--unsafe", action="store_true")

    args = parser.parse_args()

    if args.cmd == "remember":
        memory_remember(args.text, tags=args.tag)
    elif args.cmd == "recall":
        memory_recall(args.query)
    elif args.cmd == "memory-list":
        memory_list()
    elif args.cmd == "forget":
        memory_forget(args.ref)
    elif args.cmd == "memory-context":
        ctx = memory_context_for(args.goal)
        print(ctx)
        return 0
    elif args.cmd == "memory-detect":
        try:
            from arka.core.memory_detect import extract_fact

            fact = extract_fact(args.text)
            if fact:
                print(fact)
        except ImportError:
            pass
        return 0
    elif args.cmd == "memory-auto":
        stored = memory_auto_detect(args.text, quiet=not args.verbose)
        if args.verbose:
            for fact in stored:
                print(f"Auto-remembered: {fact}")
        return 0
    elif args.cmd == "trace-log":
        trace_log(input_text=args.input, interpreted=args.interpreted, source=args.source, why=args.why)
    elif args.cmd == "trace-last":
        trace_last()
    elif args.cmd == "trace-why":
        trace_why()
    elif args.cmd == "loop-save":
        sid = loop_save(args.goal, cwd=args.cwd, history=args.history, iter_n=args.iter, max_iter=args.max)
        print(sid)
    elif args.cmd == "loop-list":
        loop_list()
    elif args.cmd == "loop-load":
        data = loop_load(args.ref)
        if data:
            print(json.dumps(data))
        else:
            print("{}", file=sys.stderr)
            return 1
    elif args.cmd == "loop-clear":
        loop_clear(args.ref)
    elif args.cmd == "loop-verify":
        done, summary = loop_verify(args.goal, args.history)
        print(json.dumps({"done": done, "summary": summary}))
    elif args.cmd == "handoff-add":
        handoff_add(args.text, source=args.source)
    elif args.cmd == "handoff-list":
        handoff_list()
    elif args.cmd == "handoff-run":
        handoff_run()
    elif args.cmd == "handoff-clear":
        handoff_clear()
    elif args.cmd == "watch-add":
        watch_add(args.condition, args.action, name=args.name)
    elif args.cmd == "watch-list":
        watch_list()
    elif args.cmd == "watch-run":
        watch_run(dry=args.dry)
    elif args.cmd == "watch-remove":
        watch_remove(args.id)
    elif args.cmd == "routine-add":
        routine_add(args.schedule, args.action, name=args.name)
    elif args.cmd == "routine-list":
        routine_list()
    elif args.cmd == "routine-install":
        routine_install()
    elif args.cmd == "routine-remove":
        routine_remove(args.id)
    elif args.cmd == "fanout":
        fanout_run(args.jobs, merge_question=args.merge or None)
    elif args.cmd == "research":
        research(" ".join(args.question), doc=args.doc or None, path=args.path or None, deep=args.deep)
    elif args.cmd == "transcript-ask":
        transcript_ask(args.path, " ".join(args.question))
    elif args.cmd == "compare":
        compare_agent(args.a, args.b)
    elif args.cmd == "code":
        return code_agent(" ".join(args.goal), repo=args.repo or None, ingest=args.ingest)
    elif args.cmd == "nudge":
        nudge(quiet=args.quiet)
    elif args.cmd == "browser":
        browser_agent(" ".join(args.goal))
    elif args.cmd == "meeting":
        research(" ".join(args.notes), deep=False)
    elif args.cmd == "study":
        research("study: " + " ".join(args.topic), deep=True)
    elif args.cmd == "inbox":
        research("inbox triage: " + " ".join(args.text), deep=False)
    elif args.cmd == "product-reviewer":
        product_reviewer(" ".join(args.query))
    elif args.cmd == "price-check":
        price_check(" ".join(args.query))
    elif args.cmd == "goal":
        from arka.agent.goal import DEFAULT_MAX, run_goal
        from arka.integrations.butterfish import launch_shell

        goal_text = " ".join(args.goal).strip()
        if args.butterfish or os.environ.get("GOAL_ENGINE", "auto").strip().lower() == "butterfish":
            return launch_shell(goal=goal_text, unsafe=args.unsafe, auto_yes=args.yes)
        return run_goal(
            goal_text,
            max_steps=args.max or DEFAULT_MAX,
            auto_yes=args.yes,
            verify=args.verify,
        )
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
