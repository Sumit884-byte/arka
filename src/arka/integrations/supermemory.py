#!/usr/bin/env python3
"""Supermemory cloud memory for Arka — API first, local fallback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:
    def cache_dir():
        return __import__("pathlib").Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass

MEMORY_FILE = cache_dir() / "memory.json"
API_BASE = "https://api.supermemory.ai"
TIMEOUT = 25


def _mode() -> str:
    raw = (os.environ.get("MEMORY") or os.environ.get("SUPERMEMORY_MODE") or "auto").strip().lower()
    if raw in ("supermemory", "cloud", "api"):
        return "supermemory"
    if raw in ("local", "offline"):
        return "local"
    return "auto"


def _api_key() -> str:
    return (os.environ.get("SUPERMEMORY_API_KEY") or os.environ.get("SUPERMEMORY_API_KEY") or "").strip()


def _container_tag() -> str:
    return (
        os.environ.get("SUPERMEMORY_CONTAINER")
        or os.environ.get("SUPERMEMORY_CONTAINER_TAG")
        or os.environ.get("AGENT_NAME")
        or "arka"
    ).strip() or "arka"


def _should_try_api() -> bool:
    mode = _mode()
    if mode == "local":
        return False
    return bool(_api_key())


def load_json(path, default: object) -> object:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default


def save_json(path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _api_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise RuntimeError("SUPERMEMORY_API_KEY not set")

    url = f"{API_BASE.rstrip('/')}{path}"
    if query:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(query)}"

    data = None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

    span_ctx: Any = None
    try:
        from contextlib import nullcontext

        from arka.telemetry import mark_error, mark_ok, span
        from arka.telemetry.supermemory_obs import (
            record_supermemory_request,
            supermemory_api_attrs,
        )
        from arka.telemetry.tracing import set_http_span_attributes

        span_ctx = span(
            "arka.supermemory.api",
            attributes=supermemory_api_attrs(method, path, container=_container_tag()),
        )
    except ImportError:
        from contextlib import nullcontext

        span_ctx = nullcontext()

    with span_ctx as sp:
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if sp is not None:
                    try:
                        set_http_span_attributes(
                            sp,
                            method=method.upper(),
                            status_code=getattr(resp, "status", 200),
                            url=url,
                        )
                        mark_ok(sp)
                        record_supermemory_request(operation=path, success=True)
                    except Exception:
                        pass
                if not raw.strip():
                    return {}
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {"data": parsed}
        except urllib.error.HTTPError as exc:
            if sp is not None:
                try:
                    set_http_span_attributes(
                        sp,
                        method=method.upper(),
                        status_code=exc.code,
                        url=url,
                    )
                    mark_error(sp, f"Supermemory HTTP {exc.code}", exc=exc)
                    record_supermemory_request(operation=path, success=False)
                except Exception:
                    pass
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Supermemory HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            if sp is not None:
                try:
                    mark_error(sp, f"Supermemory network error: {exc.reason}", exc=exc)
                    record_supermemory_request(operation=path, success=False)
                except Exception:
                    pass
            raise RuntimeError(f"Supermemory network error: {exc.reason}") from exc


def _local_remember(
    text: str,
    *,
    tags: list[str] | None = None,
    provenance: dict | None = None,
    trust_tier: str = "global",
) -> str:
    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list):
        items = []
    tier = (trust_tier or "global").strip().lower()
    entry = {
        "id": hashlib.sha256(f"{text}{time.time()}".encode()).hexdigest()[:12],
        "text": text.strip(),
        "tags": tags or [],
        "ts": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
        "source": "local",
        "trust_tier": tier,
    }
    if provenance:
        entry["provenance"] = provenance
    items.append(entry)
    save_json(MEMORY_FILE, items[-200:])
    return entry["id"]


def _local_recall(query: str, *, limit: int = 5) -> list[str]:
    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list) or not items:
        return []
    q = query.lower()
    scored: list[tuple[float, str]] = []
    for row in items:
        text = (row.get("text") or "").lower()
        tag_s = " ".join(row.get("tags") or []).lower()
        score = 0.0
        for word in q.split():
            if len(word) < 2:
                continue
            if word in text:
                score += 2.0
            if word in tag_s:
                score += 1.5
        if score > 0:
            scored.append((score, row.get("text") or ""))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:limit] if t.strip()]


def _local_context(goal: str, *, limit: int = 3) -> str:
    try:
        from arka.telemetry import mark_ok, span
        from arka.telemetry.tracing import duration_ms, set_span_attributes
    except ImportError:
        hits = _local_recall(goal, limit=limit)
        if not hits:
            return ""
        return "Relevant memories (local):\n" + "\n".join(f"- {h}" for h in hits)

    import time

    start = time.perf_counter()
    with span(
        "arka.supermemory.vector_lookup",
        attributes={
            "arka.supermemory.backend": "local",
            "arka.supermemory.operation": "keyword_search",
        },
    ) as sp:
        hits = _local_recall(goal, limit=limit)
        set_span_attributes(
            sp,
            {
                "arka.supermemory.hits": len(hits),
                "arka.supermemory.lookup_ms": duration_ms(start),
            },
        )
        mark_ok(sp)
    if not hits:
        return ""
    return "Relevant memories (local):\n" + "\n".join(f"- {h}" for h in hits)


def _extract_search_lines(data: dict[str, Any], *, limit: int = 5) -> list[str]:
    lines: list[str] = []
    results = data.get("results") or []
    if not isinstance(results, list):
        return lines

    for row in results[:limit]:
        if not isinstance(row, dict):
            continue
        mem = (row.get("memory") or row.get("content") or row.get("summary") or "").strip()
        if not mem:
            chunks = row.get("chunks") or []
            if isinstance(chunks, list) and chunks:
                first = chunks[0]
                if isinstance(first, dict):
                    mem = (first.get("content") or "").strip()
        if mem:
            lines.append(mem)
    return lines


def _parse_profile(data: dict[str, Any], *, limit_chars: int) -> str:
    parts: list[str] = []
    profile = data.get("profile") or {}
    if isinstance(profile, dict):
        for label, key in (("Static profile", "static"), ("Dynamic context", "dynamic")):
            val = profile.get(key)
            items: list[str] = []
            if isinstance(val, list):
                items = [str(x).strip() for x in val if str(x).strip()]
            elif isinstance(val, str) and val.strip():
                items = [val.strip()]
            if items:
                parts.append(f"{label}:")
                parts.extend(f"- {x}" for x in items)

    search_block = data.get("searchResults") or data.get("search_results") or data
    mem_lines = _extract_search_lines(search_block if isinstance(search_block, dict) else data, limit=8)
    if mem_lines:
        parts.append("Relevant memories (Supermemory):")
        parts.extend(f"- {m}" for m in mem_lines)

    text = "\n".join(parts).strip()
    return text[:limit_chars]


def _api_remember(
    text: str,
    *,
    tags: list[str] | None = None,
    provenance: dict | None = None,
    trust_tier: str = "global",
) -> str:
    tag = _container_tag()
    metadata: dict[str, Any] = {"source": "arka", "agent": tag, "trust_tier": trust_tier}
    if tags:
        metadata["tags"] = ",".join(tags)
    if provenance:
        metadata["provenance"] = json.dumps(provenance, ensure_ascii=False)[:2000]
    body = {
        "content": text.strip(),
        "metadata": metadata,
        "containerTags": [tag],
    }
    data = _api_request("POST", "/v3/documents", body=body)
    return str(data.get("id") or data.get("documentId") or "queued")


def _api_search(query: str, *, limit: int = 5) -> list[str]:
    tag = _container_tag()
    body = {"q": query.strip(), "limit": limit, "containerTag": tag, "threshold": 0.5}
    data = _api_request("POST", "/v3/search", body=body)
    return _extract_search_lines(data, limit=limit)


def _api_profile_context(query: str, *, limit_chars: int = 3500) -> str:
    tag = _container_tag()
    body: dict[str, Any] = {"containerTag": tag}
    if query.strip():
        body["q"] = query.strip()
        body["threshold"] = 0.55
    data = _api_request("POST", "/v4/profile", body=body)
    return _parse_profile(data, limit_chars=limit_chars)


def remember(
    text: str,
    *,
    tags: list[str] | None = None,
    provenance: dict | None = None,
    trust_tier: str = "global",
) -> dict[str, Any]:
    """Store memory — Supermemory API when available, always cache locally."""
    text = text.strip()
    if not text:
        raise ValueError("empty memory text")

    try:
        from arka.telemetry import mark_error, mark_ok, set_span_attributes, span
        from arka.telemetry.supermemory_obs import emit_supermemory_log, record_supermemory_op
    except ImportError:
        return _remember_impl(text, tags=tags, provenance=provenance, trust_tier=trust_tier)

    with span(
        "arka.supermemory.remember",
        attributes={"arka.supermemory.mode": _mode(), "arka.supermemory.container": _container_tag()},
    ) as sp:
        try:
            result = _remember_impl(
                text, tags=tags, provenance=provenance, trust_tier=trust_tier
            )
            backend = str(result.get("backend") or "local")
            success = backend == "supermemory+local" or "api_error" not in result
            set_span_attributes(
                sp,
                {
                    "arka.supermemory.backend": backend,
                    "arka.supermemory.success": success,
                },
            )
            record_supermemory_op(operation="remember", backend=backend, success=success)
            emit_supermemory_log(
                f"remember via {backend}",
                operation="remember",
                backend=backend,
                success=success,
            )
            mark_ok(sp)
            return result
        except Exception as exc:
            mark_error(sp, str(exc))
            record_supermemory_op(operation="remember", backend=_mode(), success=False)
            raise


def _remember_impl(
    text: str,
    *,
    tags: list[str] | None = None,
    provenance: dict | None = None,
    trust_tier: str = "global",
) -> dict[str, Any]:
    local_id = _local_remember(
        text, tags=tags, provenance=provenance, trust_tier=trust_tier
    )
    result: dict[str, Any] = {"backend": "local", "local_id": local_id}

    if not _should_try_api():
        return result

    try:
        api_id = _api_remember(
            text, tags=tags, provenance=provenance, trust_tier=trust_tier
        )
        result.update({"backend": "supermemory+local", "api_id": api_id})
        try:
            import importlib

            mod = importlib.import_module("arka_talents")
            mod.memory_reindex()
        except Exception:
            pass
    except Exception as exc:
        result["api_error"] = str(exc)
        if _mode() == "supermemory":
            raise
    return result


def recall(query: str, *, limit: int = 5) -> str:
    """Recall memories — API first, local keyword fallback."""
    query = query.strip()

    try:
        from arka.telemetry import mark_error, mark_ok, set_span_attributes, span
        from arka.telemetry.supermemory_obs import emit_supermemory_log, record_supermemory_op
    except ImportError:
        return _recall_impl(query, limit=limit)

    with span(
        "arka.supermemory.recall",
        attributes={"arka.supermemory.mode": _mode(), "arka.supermemory.container": _container_tag()},
    ) as sp:
        try:
            backend, hits = _recall_impl(query, limit=limit)
            set_span_attributes(
                sp,
                {
                    "arka.supermemory.backend": backend,
                    "arka.supermemory.hits": hits,
                    "arka.supermemory.success": hits > 0 or not query,
                },
            )
            record_supermemory_op(operation="recall", backend=backend, success=True, hits=hits)
            emit_supermemory_log(
                f"recall via {backend} ({hits} hits)",
                operation="recall",
                backend=backend,
                hits=hits,
                success=True,
            )
            mark_ok(sp)
            return backend
        except Exception as exc:
            mark_error(sp, str(exc))
            record_supermemory_op(operation="recall", backend=_mode(), success=False)
            raise


def _recall_impl(query: str, *, limit: int = 5) -> tuple[str, int]:
    if _should_try_api():
        try:
            hits = _api_search(query, limit=limit) if query else []
            if not hits and query:
                hits = _api_search(query, limit=limit)
            if hits:
                for line in hits:
                    print(f"• {line}")
                print(f"(via Supermemory · container {_container_tag()})", file=sys.stderr)
                return "supermemory", len(hits)
        except Exception as exc:
            if _mode() == "supermemory":
                raise RuntimeError(str(exc)) from exc
            print(f"Supermemory unavailable, using local cache: {exc}", file=sys.stderr)

    if not query:
        list_memories(limit=limit)
        items = load_json(MEMORY_FILE, [])
        count = len(items) if isinstance(items, list) else 0
        return "local", count

    hits = _local_recall(query, limit=limit)
    if not hits:
        print("No matching memories.")
        return "local", 0
    for line in hits:
        print(f"• {line}")
    print("(via local cache)", file=sys.stderr)
    return "local", len(hits)


def _turboquant_context(goal: str, *, limit_chars: int) -> str:
    try:
        from arka.stock.turboquant_rag import _media_store, use_turboquant
    except ImportError:
        return ""
    if not use_turboquant():
        return ""
    try:
        from arka.agent.talents import MEMORY_INDEX_SLUG, memory_reindex
    except ImportError:
        return ""

    try:
        from arka.telemetry import mark_ok, span
        from arka.telemetry.tracing import duration_ms, set_span_attributes
    except ImportError:
        store = _media_store(MEMORY_INDEX_SLUG)
        if not store.chunks:
            memory_reindex()
            store = _media_store(MEMORY_INDEX_SLUG)
        if store.chunks:
            ctx = store.search(goal, max_chars=limit_chars)
            if ctx.strip():
                return "Relevant memories (semantic):\n" + ctx.strip()
        return ""

    import time

    start = time.perf_counter()
    with span(
        "arka.supermemory.vector_lookup",
        attributes={
            "arka.supermemory.backend": "turboquant",
            "arka.supermemory.operation": "vector_search",
        },
    ) as sp:
        store = _media_store(MEMORY_INDEX_SLUG)
        if not store.chunks:
            memory_reindex()
            store = _media_store(MEMORY_INDEX_SLUG)
        ctx = ""
        hits = 0
        if store.chunks:
            ctx = store.search(goal, max_chars=limit_chars)
            hits = ctx.count("\n- ") if ctx.strip() else 0
        set_span_attributes(
            sp,
            {
                "arka.supermemory.hits": hits,
                "arka.supermemory.lookup_ms": duration_ms(start),
                "arka.supermemory.chunks": len(store.chunks),
            },
        )
        mark_ok(sp)
    if ctx.strip():
        return "Relevant memories (semantic):\n" + ctx.strip()
    return ""


def context_for(goal: str, *, limit_chars: int = 3500) -> str:
    """Context string for agent prompts — API profile, semantic index, local."""
    goal = goal.strip()
    if not goal:
        return ""

    try:
        from arka.telemetry import mark_error, mark_ok, set_span_attributes, span
        from arka.telemetry.supermemory_obs import emit_supermemory_log, record_supermemory_op
    except ImportError:
        return _context_for_impl(goal, limit_chars=limit_chars)

    with span(
        "arka.supermemory.context",
        attributes={"arka.supermemory.mode": _mode(), "arka.supermemory.container": _container_tag()},
    ) as sp:
        try:
            ctx, backend, hits = _context_for_impl(goal, limit_chars=limit_chars)
            set_span_attributes(
                sp,
                {
                    "arka.supermemory.backend": backend,
                    "arka.supermemory.hits": hits,
                    "arka.supermemory.success": bool(ctx.strip()),
                },
            )
            record_supermemory_op(
                operation="context",
                backend=backend,
                success=bool(ctx.strip()),
                hits=hits,
            )
            emit_supermemory_log(
                f"context via {backend} ({hits} hits, {len(ctx)} chars)",
                operation="context",
                backend=backend,
                hits=hits,
                success=bool(ctx.strip()),
            )
            mark_ok(sp)
            return ctx
        except Exception as exc:
            mark_error(sp, str(exc))
            record_supermemory_op(operation="context", backend=_mode(), success=False)
            raise


def _context_for_impl(goal: str, *, limit_chars: int = 3500) -> tuple[str, str, int]:
    if _should_try_api():
        try:
            ctx = _api_profile_context(goal, limit_chars=limit_chars)
            if ctx.strip():
                hits = ctx.count("\n- ")
                return ctx, "supermemory", hits
        except Exception:
            if _mode() == "supermemory":
                pass

    ctx = _turboquant_context(goal, limit_chars=limit_chars)
    if ctx.strip():
        hits = ctx.count("\n- ")
        return ctx, "turboquant", hits

    local = _local_context(goal)
    hits = local.count("\n- ") if local else 0
    return local, "local", hits


def list_memories(*, limit: int = 20) -> None:
    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list) or not items:
        print("No memories stored locally.")
        return
    print(f"Local memories ({len(items)} total, showing last {limit}):")
    for row in items[-limit:]:
        tags = ", ".join(row.get("tags") or [])
        tag_s = f" [{tags}]" if tags else ""
        print(f"{row.get('id', '?')}{tag_s}  {row.get('when', '')}")
        print(f"  {row.get('text', '')}")
        print()


def forget(ref: str) -> None:
    items = load_json(MEMORY_FILE, [])
    if not isinstance(items, list):
        print("Nothing to forget.")
        return
    ref_l = ref.lower()
    kept = [
        r
        for r in items
        if ref_l not in (r.get("id") or "").lower() and ref_l not in (r.get("text") or "").lower()
    ]
    if len(kept) == len(items):
        print(f"No local memory matched: {ref}")
        return
    save_json(MEMORY_FILE, kept)
    print(f"Removed {len(items) - len(kept)} local memory entries.")
    if _should_try_api():
        print("Note: Supermemory cloud entries are not deleted from this command yet.", file=sys.stderr)


def status() -> None:
    mode = _mode()
    key = _api_key()
    tag = _container_tag()
    items = load_json(MEMORY_FILE, [])
    count = len(items) if isinstance(items, list) else 0
    print(f"Memory mode:     {mode}")
    print(f"Container tag:   {tag}")
    print(f"API key:         {'set' if key else 'not set'}")
    print(f"Local cache:     {MEMORY_FILE} ({count} entries)")
    if mode == "auto":
        print("Behavior:        Supermemory API when key works, else local cache")
    elif mode == "supermemory":
        print("Behavior:        Supermemory API only (errors if unavailable)")
    else:
        print("Behavior:        Local cache only")


def remember_print(
    text: str,
    *,
    tags: list[str] | None = None,
    provenance: dict | None = None,
    trust_tier: str = "global",
) -> None:
    result = remember(text, tags=tags, provenance=provenance, trust_tier=trust_tier)
    backend = result.get("backend", "local")
    local_id = result.get("local_id", "?")
    msg = f"Remembered ({local_id}): {text[:120]}"
    if backend == "supermemory+local":
        api_id = result.get("api_id", "?")
        print(f"{msg}  [Supermemory: {api_id}]")
    else:
        if result.get("api_error"):
            print(f"{msg}  [local fallback — {result['api_error'][:80]}]", file=sys.stderr)
        print(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka Supermemory — cloud + local fallback")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("remember", help="Store a memory")
    p.add_argument("text")
    p.add_argument("--tag", action="append", default=[])

    p = sub.add_parser("recall", help="Search memories")
    p.add_argument("query", nargs="?", default="")

    sub.add_parser("list", help="List local cached memories")
    sub.add_parser("status", help="Show memory backend status")

    p = sub.add_parser("context", help="Print context blob for a goal")
    p.add_argument("goal")

    p = sub.add_parser("forget", help="Remove from local cache")
    p.add_argument("ref")

    args = parser.parse_args()
    if args.cmd == "remember":
        remember_print(args.text, tags=args.tag or None)
        return 0
    if args.cmd == "recall":
        recall(args.query)
        return 0
    if args.cmd == "list":
        list_memories()
        return 0
    if args.cmd == "status":
        status()
        return 0
    if args.cmd == "context":
        ctx = context_for(args.goal)
        print(ctx or "(no context)")
        return 0
    if args.cmd == "forget":
        forget(args.ref)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
