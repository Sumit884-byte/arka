#!/usr/bin/env python3
"""Arka Intelligence — live entity/relationship graph for remember/recall.

Extracts entities and relations from facts (symbolic rules + heuristics), stores a
local knowledge graph, and recalls via graph traversal instead of chunk similarity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass

GRAPH_FILE = cache_dir() / "memory_graph.json"
USER_ENTITY_ID = "user"

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "what",
        "who",
        "how",
        "when",
        "where",
        "why",
        "which",
        "do",
        "does",
        "did",
        "can",
        "could",
        "would",
        "should",
        "will",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "as",
        "and",
        "or",
        "but",
        "if",
        "that",
        "this",
        "it",
        "its",
        "me",
        "my",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "about",
        "tell",
        "remember",
        "recall",
        "user",
        "users",
        "prefer",
        "prefers",
        "named",
        "name",
        "called",
    }
)

_PREDICATE_LABELS: dict[str, str] = {
    "named": "is named",
    "prefer": "prefers",
    "favorite": "favorites",
    "live_in": "lives in",
    "from": "is from",
    "city": "is based in",
    "work_at": "works at",
    "is_a": "is a",
    "allergic": "is allergic to",
    "speak_lang": "speaks",
    "prefer_model": "prefers model",
    "event_at": "has event",
    "email": "email is",
    "phone": "phone is",
    "has": "has",
    "birthday": "birthday is",
    "remember": "noted",
}


def enabled() -> bool:
    return os.environ.get("ARKA_GRAPH_MEMORY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return slug[:48] or "entity"


def _entity_id(label: str, *, kind: str = "") -> str:
    base = _slug(label)
    if kind:
        return f"{kind}_{base}"[:56]
    return base[:56]


def _now() -> float:
    return time.time()


def _empty_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now(),
        "entities": [
            {
                "id": USER_ENTITY_ID,
                "label": "User",
                "kind": "person",
                "aliases": ["me", "I"],
            }
        ],
        "edges": [],
    }


def load_graph() -> dict[str, Any]:
    try:
        if GRAPH_FILE.is_file():
            data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entities"), list):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return _empty_graph()


def save_graph(graph: dict[str, Any]) -> None:
    graph["updated_at"] = _now()
    GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_FILE.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")


def _find_entity(graph: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    for row in graph.get("entities") or []:
        if isinstance(row, dict) and row.get("id") == entity_id:
            return row
    return None


def _ensure_entity(
    graph: dict[str, Any],
    label: str,
    *,
    kind: str = "thing",
    aliases: list[str] | None = None,
) -> str:
    label = (label or "").strip()
    if not label:
        return USER_ENTITY_ID
    eid = _entity_id(label, kind=kind) if kind not in ("person", "thing", "") else _entity_id(label)
    existing = _find_entity(graph, eid)
    if existing:
        alias_set = {a.lower() for a in existing.get("aliases") or []}
        for alias in aliases or []:
            a = alias.strip()
            if a and a.lower() not in alias_set:
                existing.setdefault("aliases", []).append(a)
        return eid
    graph.setdefault("entities", []).append(
        {
            "id": eid,
            "label": label,
            "kind": kind or "thing",
            "aliases": aliases or [],
        }
    )
    return eid


def _parse_predicate(predicate: str) -> tuple[str, str, str]:
    """Parse 'named(user.entity, name)' → ('user', 'entity', 'name')."""
    pred = (predicate or "").strip()
    if "(" not in pred:
        return USER_ENTITY_ID, pred or "related", "object"
    head, _, tail = pred.partition("(")
    head = head.strip()
    args = tail.rstrip(")").split(",")
    if len(args) >= 2:
        subj = args[0].strip()
        obj = args[1].strip()
        if "." in subj:
            base, field = subj.split(".", 1)
            return base.strip() or USER_ENTITY_ID, head or "related", obj.strip()
        return subj or USER_ENTITY_ID, head or "related", obj.strip()
    if len(args) == 1:
        return USER_ENTITY_ID, head or "related", args[0].strip()
    return USER_ENTITY_ID, head or "related", "object"


def _human_predicate(predicate: str) -> str:
    key = (predicate or "").strip().lower()
    return _PREDICATE_LABELS.get(key, key.replace("_", " "))


@dataclass
class ExtractedTriple:
    subject: str
    predicate: str
    object_label: str
    object_kind: str = "thing"
    fact: str = ""


def _extract_from_detect(text: str) -> list[ExtractedTriple]:
    try:
        from arka.core.memory_detect import detect_memories
    except ImportError:
        return []
    triples: list[ExtractedTriple] = []
    for hit in detect_memories(text, existing=[]):
        subj_field, pred, obj_field = _parse_predicate(hit.predicate)
        fact = hit.text
        if pred == "named" and subj_field == "user" and obj_field == "name":
            m = re.search(r"(?i)user'?s?\s+(\w+)\s+is\s+named\s+(.+)$", fact)
            if m:
                triples.append(
                    ExtractedTriple(
                        USER_ENTITY_ID,
                        f"has_{m.group(1).lower()}",
                        m.group(2).strip(),
                        object_kind=m.group(1).lower(),
                        fact=fact,
                    )
                )
                continue
            m = re.search(r"(?i)user'?s?\s+name\s+is\s+(.+)$", fact)
            if m:
                triples.append(
                    ExtractedTriple(
                        USER_ENTITY_ID,
                        "named",
                        m.group(1).strip(),
                        object_kind="person",
                        fact=fact,
                    )
                )
                continue
        if pred in {"prefer", "favorite", "live_in", "from", "city", "work_at", "is_a"}:
            m = re.search(r"(?i)(?:user\s+)?(.+)$", fact)
            obj = m.group(1).strip() if m else obj_field
            triples.append(
                ExtractedTriple(USER_ENTITY_ID, pred, obj, object_kind="concept", fact=fact)
            )
            continue
        if pred in {"allergic", "speak_lang", "prefer_model", "event_at", "email", "phone", "has", "birthday"}:
            m = re.search(r"(?i)user\s+(.+)$", fact)
            obj = m.group(1).strip() if m else obj_field
            triples.append(
                ExtractedTriple(USER_ENTITY_ID, pred, obj, object_kind="attribute", fact=fact)
            )
            continue
        triples.append(
            ExtractedTriple(
                USER_ENTITY_ID,
                pred,
                obj_field.replace("_", " "),
                object_kind="thing",
                fact=fact,
            )
        )
    return triples


def _extract_heuristic(text: str) -> list[ExtractedTriple]:
    """Fallback relation patterns when symbolic detect misses."""
    raw = " ".join((text or "").split()).strip()
    if not raw:
        return []
    patterns: list[tuple[re.Pattern[str], str, str, str]] = [
        (
            re.compile(r"(?i)^(.+?)\s+works\s+(?:at|for)\s+(.+)$"),
            "subject",
            "works_at",
            "org",
        ),
        (
            re.compile(r"(?i)^(.+?)\s+(?:is\s+)?(?:friends\s+with|knows)\s+(.+)$"),
            "subject",
            "knows",
            "person",
        ),
        (
            re.compile(r"(?i)^(.+?)\s+prefers\s+(.+)$"),
            "subject",
            "prefer",
            "concept",
        ),
        (
            re.compile(r"(?i)^(.+?)\s+lives\s+in\s+(.+)$"),
            "subject",
            "live_in",
            "place",
        ),
    ]
    triples: list[ExtractedTriple] = []
    for pattern, _, pred, kind in patterns:
        m = pattern.match(raw)
        if not m:
            continue
        subj = m.group(1).strip()
        obj = m.group(2).strip().rstrip(".")
        subj_id = USER_ENTITY_ID if subj.lower() in {"i", "user", "me", "my"} else subj
        triples.append(
            ExtractedTriple(subj_id, pred, obj, object_kind=kind, fact=raw)
        )
        return triples
    return [
        ExtractedTriple(USER_ENTITY_ID, "noted", raw[:120], object_kind="fact", fact=raw)
    ]


def extract_triples(text: str) -> list[ExtractedTriple]:
    triples = _extract_from_detect(text)
    if triples:
        return triples
    return _extract_heuristic(text)


def _edge_id(subject: str, predicate: str, obj_id: str, fact: str) -> str:
    raw = f"{subject}|{predicate}|{obj_id}|{fact}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def ingest_text(
    text: str,
    *,
    memory_id: str | None = None,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract entities/relations from text and merge into the graph."""
    if not enabled():
        return {"ingested": False, "reason": "disabled"}
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return {"ingested": False, "reason": "empty"}

    g = graph if graph is not None else load_graph()
    triples = extract_triples(cleaned)
    added_edges = 0
    added_entities = 0
    entity_count_before = len(g.get("entities") or [])

    for triple in triples:
        if triple.subject == USER_ENTITY_ID or triple.subject.lower() in {"user", "i", "me"}:
            subj_id = USER_ENTITY_ID
        else:
            subj_id = _ensure_entity(g, triple.subject, kind="person")
        obj_id = _ensure_entity(g, triple.object_label, kind=triple.object_kind)
        eid = _edge_id(subj_id, triple.predicate, obj_id, triple.fact or cleaned)
        edges = g.setdefault("edges", [])
        if any(isinstance(e, dict) and e.get("id") == eid for e in edges):
            continue
        edges.append(
            {
                "id": eid,
                "subject": subj_id,
                "predicate": triple.predicate,
                "object": obj_id,
                "fact": triple.fact or cleaned,
                "memory_id": memory_id,
                "ts": _now(),
            }
        )
        added_edges += 1

    added_entities = len(g.get("entities") or []) - entity_count_before
    if graph is None:
        save_graph(g)
    return {
        "ingested": added_edges > 0 or added_entities > 0,
        "edges_added": added_edges,
        "entities_added": added_entities,
        "triples": len(triples),
    }


def graph_remember(text: str, *, memory_id: str | None = None) -> dict[str, Any]:
    return ingest_text(text, memory_id=memory_id)


def _entity_label(graph: dict[str, Any], entity_id: str) -> str:
    row = _find_entity(graph, entity_id)
    if row:
        return str(row.get("label") or entity_id)
    return entity_id


def _entity_kind(graph: dict[str, Any], entity_id: str) -> str:
    row = _find_entity(graph, entity_id)
    if row:
        return str(row.get("kind") or "thing")
    return "thing"


def _query_terms(goal: str) -> list[str]:
    terms = [
        w
        for w in re.findall(r"[a-z0-9+#]+(?:'[a-z0-9]+)?", (goal or "").lower())
        if len(w) >= 2 and w not in _STOP_WORDS
    ]
    return terms


def _entity_matches(graph: dict[str, Any], entity_id: str, terms: list[str]) -> float:
    row = _find_entity(graph, entity_id)
    if not row:
        return 0.0
    hay = " ".join(
        [
            str(row.get("label") or ""),
            str(row.get("kind") or ""),
            " ".join(str(a) for a in row.get("aliases") or []),
        ]
    ).lower()
    score = 0.0
    for term in terms:
        if term in hay or re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", hay):
            score += 1.0
    return score


def _edge_matches(edge: dict[str, Any], graph: dict[str, Any], terms: list[str]) -> float:
    fact = str(edge.get("fact") or "").lower()
    pred = str(edge.get("predicate") or "").lower()
    subj = _entity_label(graph, str(edge.get("subject") or "")).lower()
    obj = _entity_label(graph, str(edge.get("object") or "")).lower()
    hay = f"{fact} {pred} {subj} {obj}"
    score = 0.0
    for term in terms:
        if term in hay:
            score += 1.0
    return score


def _format_edge(graph: dict[str, Any], edge: dict[str, Any]) -> str:
    subj = _entity_label(graph, str(edge.get("subject") or ""))
    obj = _entity_label(graph, str(edge.get("object") or ""))
    pred = _human_predicate(str(edge.get("predicate") or ""))
    fact = str(edge.get("fact") or "").strip()
    if fact:
        return f"{subj} → {pred} → {obj} ({fact})"
    return f"{subj} → {pred} → {obj}"


def _traverse(
    graph: dict[str, Any],
    seed_entities: list[str],
    *,
    max_depth: int = 2,
    max_edges: int = 12,
) -> list[dict[str, Any]]:
    edges = [e for e in graph.get("edges") or [] if isinstance(e, dict)]
    if not edges:
        return []
    by_subject: dict[str, list[dict[str, Any]]] = {}
    by_object: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        subj = str(edge.get("subject") or "")
        obj = str(edge.get("object") or "")
        by_subject.setdefault(subj, []).append(edge)
        by_object.setdefault(obj, []).append(edge)

    visited_edges: set[str] = set()
    collected: list[dict[str, Any]] = []
    frontier = list(dict.fromkeys(seed_entities))

    for depth in range(max_depth + 1):
        if not frontier or len(collected) >= max_edges:
            break
        next_frontier: list[str] = []
        for eid in frontier:
            for edge in by_subject.get(eid, []) + by_object.get(eid, []):
                edge_id = str(edge.get("id") or "")
                if edge_id in visited_edges:
                    continue
                visited_edges.add(edge_id)
                collected.append(edge)
                if len(collected) >= max_edges:
                    break
                other = str(edge.get("object") if edge.get("subject") == eid else edge.get("subject") or "")
                if other and other not in next_frontier:
                    next_frontier.append(other)
            if len(collected) >= max_edges:
                break
        frontier = next_frontier
    return collected


def graph_recall(goal: str, *, limit_chars: int = 1200) -> tuple[str, dict[str, Any]]:
    """Traverse the knowledge graph for a goal. Returns (narrative, meta)."""
    meta: dict[str, Any] = {
        "backend": "graph",
        "path": "entity_match → edge_traversal → narrative",
        "entities_matched": [],
        "edges_traversed": 0,
    }
    if not enabled():
        return "", {**meta, "enabled": False}

    graph = load_graph()
    terms = _query_terms(goal)
    if not terms:
        return "", {**meta, "reason": "empty_query"}

    entity_scores: list[tuple[float, str]] = []
    for row in graph.get("entities") or []:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("id") or "")
        score = _entity_matches(graph, eid, terms)
        if score > 0:
            entity_scores.append((score, eid))
    entity_scores.sort(key=lambda x: x[0], reverse=True)

    edge_scores: list[tuple[float, dict[str, Any]]] = []
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        score = _edge_matches(edge, graph, terms)
        if score > 0:
            edge_scores.append((score, edge))
    edge_scores.sort(key=lambda x: x[0], reverse=True)

    seeds = [eid for _, eid in entity_scores[:4]]
    if not seeds and edge_scores:
        for _, edge in edge_scores[:3]:
            seeds.append(str(edge.get("subject") or ""))
            seeds.append(str(edge.get("object") or ""))
        seeds = list(dict.fromkeys(s for s in seeds if s))

    if not seeds and not edge_scores:
        return "", {**meta, "hits": 0}

    meta["entities_matched"] = [
        {"id": eid, "label": _entity_label(graph, eid), "score": score}
        for score, eid in entity_scores[:5]
    ]

    traversed = _traverse(graph, seeds, max_depth=2, max_edges=10)
    seen_ids = {str(e.get("id") or "") for e in traversed}
    for _, edge in edge_scores[:5]:
        eid = str(edge.get("id") or "")
        if eid not in seen_ids:
            traversed.insert(0, edge)
            seen_ids.add(eid)
        if len(traversed) >= 10:
            break

    meta["edges_traversed"] = len(traversed)
    if not traversed:
        return "", {**meta, "hits": 0}

    lines = [_format_edge(graph, edge) for edge in traversed]
    narrative = "Knowledge graph (relational recall):\n" + "\n".join(f"- {line}" for line in lines)
    if len(narrative) > limit_chars:
        narrative = narrative[: limit_chars - 3].rstrip() + "..."
    meta["hits"] = len(traversed)
    return narrative, meta


def rebuild_from_memory_file() -> dict[str, Any]:
    """Re-ingest all facts from memory.json into the graph."""
    memory_file = cache_dir() / "memory.json"
    try:
        rows = json.loads(memory_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rows = []
    if not isinstance(rows, list):
        return {"rebuilt": False, "reason": "no_memory_file"}
    graph = _empty_graph()
    total_edges = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        result = ingest_text(text, memory_id=str(row.get("id") or ""), graph=graph)
        total_edges += int(result.get("edges_added") or 0)
    save_graph(graph)
    return {
        "rebuilt": True,
        "facts": len(rows),
        "edges": total_edges,
        "entities": len(graph.get("entities") or []),
    }


def status(*, verbose: bool = False) -> dict[str, Any]:
    graph = load_graph()
    entities = graph.get("entities") or []
    edges = graph.get("edges") or []
    info: dict[str, Any] = {
        "enabled": enabled(),
        "backend": "local_graph",
        "graph_file": str(GRAPH_FILE),
        "entities": len(entities),
        "edges": len(edges),
        "updated_at": graph.get("updated_at"),
        "recall_path": "entity_match → BFS traversal → relational narrative",
        "vision": {
            "live_graph": True,
            "chunk_rag": False,
            "autonomous_distill": "on_remember (symbolic + heuristic extraction)",
            "vector_similarity": False,
        },
    }
    if verbose:
        info["sample_edges"] = [
            _format_edge(graph, e)
            for e in edges[-5:]
            if isinstance(e, dict)
        ]
    return info


def export_mermaid(*, limit: int = 40) -> str:
    graph = load_graph()
    lines = ["graph LR", "  user((User))"]
    seen: set[str] = {USER_ENTITY_ID}
    for edge in (graph.get("edges") or [])[:limit]:
        if not isinstance(edge, dict):
            continue
        subj = str(edge.get("subject") or USER_ENTITY_ID)
        obj = str(edge.get("object") or "")
        pred = _human_predicate(str(edge.get("predicate") or ""))
        subj_label = _entity_label(graph, subj).replace('"', "'")
        obj_label = _entity_label(graph, obj).replace('"', "'")
        sid = re.sub(r"[^a-zA-Z0-9_]", "_", subj)
        oid = re.sub(r"[^a-zA-Z0-9_]", "_", obj)
        if sid not in seen:
            lines.append(f'  {sid}["{subj_label}"]')
            seen.add(sid)
        if oid not in seen:
            lines.append(f'  {oid}["{obj_label}"]')
            seen.add(oid)
        lines.append(f'  {sid} -->|{pred}| {oid}')
    return "\n".join(lines)


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Arka Intelligence — entity/relationship graph memory"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("remember", help="Ingest text into the knowledge graph")
    p.add_argument("text")

    p = sub.add_parser("recall", help="Graph traversal recall")
    p.add_argument("goal")
    p.add_argument("--limit-chars", type=int, default=1200)

    sub.add_parser("status", help="Graph stats and recall path")
    sub.add_parser("rebuild", help="Rebuild graph from memory.json facts")
    p = sub.add_parser("export", help="Export graph as mermaid or json")
    p.add_argument("--format", choices=["mermaid", "json"], default="mermaid")

    args = parser.parse_args(argv)
    if args.cmd == "remember":
        print(json.dumps(graph_remember(args.text), indent=2))
        return 0
    if args.cmd == "recall":
        text, meta = graph_recall(args.goal, limit_chars=args.limit_chars)
        if args.limit_chars and text:
            print(text)
        elif text:
            print(text)
        else:
            print("(no graph matches)")
        if os.environ.get("ARKA_GRAPH_VERBOSE") == "1":
            print(json.dumps(meta, indent=2), file=sys.stderr)
        return 0
    if args.cmd == "status":
        print(json.dumps(status(verbose=True), indent=2))
        return 0
    if args.cmd == "rebuild":
        print(json.dumps(rebuild_from_memory_file(), indent=2))
        return 0
    if args.cmd == "export":
        if args.format == "json":
            print(json.dumps(load_graph(), indent=2))
        else:
            print(export_mermaid())
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
