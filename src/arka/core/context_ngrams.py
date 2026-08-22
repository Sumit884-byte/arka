"""N-gram and multigram shortcuts for fast semantic context selection."""

from __future__ import annotations

import re
from typing import Any

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "for", "with", "about", "what", "how", "why",
        "when", "where", "who", "are", "is", "was", "were", "be", "been", "being", "have",
        "has", "had", "do", "does", "did", "will", "would", "could", "should", "can", "may",
        "might", "must", "that", "this", "these", "those", "your", "you", "they", "them",
        "their", "from", "into", "onto", "over", "under", "not", "also", "just", "like",
        "some", "any", "all", "one", "two", "more", "most", "other", "such", "only", "own",
        "same", "than", "then", "there", "here", "very", "much", "many", "tell", "give",
        "explain", "please", "could", "would", "want", "need",
    }
)

_NGRAM_WEIGHTS = (1.0, 2.5, 4.0)  # unigram, bigram, trigram
_LIST_ITEM_RE = re.compile(
    r"(?im)^\s*(?:\*\*)?(?:#{1,3}\s*)?(?:\d+[.)]|[-*•])\s*(.+?)(?:\*\*)?\s*$"
)
_SUBTOPICS_RE = re.compile(r"(?im)^SUBTOPICS:\s*(.+)$")


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[-_/]", " ", text)
    return " ".join(text.split())


def word_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9']{2,}", normalize(text))
        if token not in _STOPWORDS
    ]


def multigrams(text: str, *, max_n: int = 3) -> dict[int, set[str]]:
    """Unigrams, bigrams, and trigrams for lexical + phrase matching."""
    words = word_tokens(text)
    out: dict[int, set[str]] = {n: set() for n in range(1, max_n + 1)}
    for word in words:
        out[1].add(word)
    for n in range(2, max_n + 1):
        for idx in range(len(words) - n + 1):
            out[n].add(" ".join(words[idx : idx + n]))
    return out


def overlap_score(
    query: str,
    document: str,
    *,
    weights: tuple[float, float, float] = _NGRAM_WEIGHTS,
) -> float:
    """Score query↔document overlap; multigrams count more than unigrams."""
    q = multigrams(query)
    d = multigrams(document)
    score = 0.0
    for n, weight in enumerate(weights, start=1):
        shared = q[n] & d[n]
        if shared:
            score += weight * len(shared)
    if q[1] and d[1]:
        score += 0.75 * len(q[1] & d[1]) / max(1, min(len(q[1]), len(d[1])))
    return score


def query_relates_to_texts(query: str, texts: list[str], *, threshold: float = 1.25) -> bool:
    """True when query n-grams overlap any prior text above threshold."""
    if not texts:
        return False
    return max(overlap_score(query, blob) for blob in texts if blob) >= threshold


def match_subtopic(query: str, subtopics: list[str], *, threshold: float = 2.0) -> str | None:
    """Return best matching subtopic slug/label for a short user drill-down."""
    best_name = ""
    best_score = 0.0
    for sub in subtopics:
        label = str(sub or "").strip()
        if not label:
            continue
        score = overlap_score(query, label.replace("-", " "))
        if score > best_score:
            best_score = score
            best_name = label
    return best_name if best_score >= threshold else None


def extract_list_item(text: str, index: int) -> str | None:
    """Pull numbered/bulleted list item *index* (1-based) from assistant text."""
    if index < 1:
        return None
    items: list[str] = []
    for match in _LIST_ITEM_RE.finditer(text or ""):
        body = " ".join(match.group(1).split()).strip(" *:")
        if body and len(body) > 3:
            items.append(body)
    if 1 <= index <= len(items):
        return items[index - 1]
    return None


def list_item_index_from_query(query: str) -> int | None:
    match = re.search(
        r"(?i)(?:point|item|option|#|no\.?)\s*(\d+)|^(\d+)\.?$",
        (query or "").strip(),
    )
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _exchange_blocks(rows: list[tuple[str, str]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] = {"user": "", "assistant": "", "rows": []}
    for role, content in rows:
        if role == "user":
            if current["user"] or current["assistant"]:
                blocks.append(current)
                current = {"user": "", "assistant": "", "rows": []}
            current["user"] = content
            current["rows"].append((role, content))
        elif role == "assistant":
            current["assistant"] = content
            current["rows"].append((role, content))
    if current["user"] or current["assistant"]:
        blocks.append(current)
    return blocks


def score_exchange(query: str, block: dict[str, Any], *, recency_boost: float = 0.0) -> float:
    blob = f"{block.get('user', '')} {block.get('assistant', '')}".strip()
    score = overlap_score(query, blob)
    sub_match = _SUBTOPICS_RE.search(str(block.get("assistant") or ""))
    if sub_match:
        for part in sub_match.group(1).split(","):
            score += overlap_score(query, part.strip()) * 1.5
    return score + recency_boost


def _is_bare_continue(query: str) -> bool:
    t = " ".join((query or "").strip().split())
    if not t:
        return False
    try:
        from arka.core.chat_context_gate import _CONTINUE_FOLLOWUP

        if _CONTINUE_FOLLOWUP.match(t):
            return True
    except ImportError:
        pass
    return t.lower() in {
        "tell more",
        "tell me more",
        "say more",
        "continue",
        "go on",
        "keep going",
        "what else",
        "next",
    }


def select_relevant_rows(
    query: str,
    rows: list[tuple[str, str]],
    *,
    max_turns: int = 8,
    max_chars: int = 8000,
    always_include_last: bool = True,
) -> list[tuple[str, str]]:
    """Pick chat turns whose n-grams best match the query (multigram semantic shortcut)."""
    if not rows:
        return []

    try:
        from arka.core.chat_context_gate import (
            is_answer_to_assistant_question,
            is_list_item_followup,
            is_short_followup,
        )

        if (
            is_short_followup(query)
            or is_list_item_followup(query)
            or _is_bare_continue(query)
            or is_answer_to_assistant_question(query, rows)
        ):
            return rows[-max_turns * 2 :]
    except ImportError:
        if list_item_index_from_query(query) is not None:
            return rows[-max_turns * 2 :]

    blocks = _exchange_blocks(rows)
    if len(blocks) <= 1:
        return rows[-max_turns * 2 :]

    scored: list[tuple[float, int, dict[str, Any]]] = []
    last_idx = len(blocks) - 1
    for idx, block in enumerate(blocks):
        boost = 2.0 if idx == last_idx else 0.0
        scored.append((score_exchange(query, block, recency_boost=boost), idx, block))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)

    chosen: list[tuple[str, str]] = []
    used_chars = 0
    seen_indices: set[int] = set()

    if always_include_last:
        last_block = blocks[-1]
        for pair in last_block["rows"]:
            chosen.append(pair)
            used_chars += len(pair[1]) + 8
        seen_indices.add(last_idx)

    for score, idx, block in scored:
        if idx in seen_indices:
            continue
        if score < 1.0 and always_include_last:
            continue
        block_rows = block["rows"]
        block_len = sum(len(content) + 8 for _, content in block_rows)
        if used_chars + block_len > max_chars and chosen:
            continue
        for pair in block_rows:
            if pair not in chosen:
                chosen.append(pair)
        used_chars += block_len
        seen_indices.add(idx)
        if len(chosen) >= max_turns * 2:
            break

    if not chosen:
        return rows[-max_turns * 2 :]

    # Preserve chronological order
    order = {pair: i for i, pair in enumerate(rows)}
    chosen.sort(key=lambda pair: order.get(pair, 10_000))
    return chosen


def format_rows(rows: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"{'User' if role == 'user' else 'Assistant'}: {content}" for role, content in rows
    )


def select_context_from_turns(
    query: str,
    turns: list[dict[str, Any]],
    *,
    limit_chars: int = 3000,
) -> str:
    """Rank stored session turns by n-gram overlap and return the best-matching slice."""
    rows: list[tuple[str, str]] = []
    for turn in turns:
        role = str(turn.get("role") or "user").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = str(turn.get("text") or turn.get("content") or "").strip()
        if text:
            rows.append((role, text))
    if not rows:
        return ""
    picked = select_relevant_rows(query, rows, max_turns=6, max_chars=limit_chars)
    out = format_rows(picked)
    if len(out) > limit_chars:
        out = out[-limit_chars:]
    return out


def context_hint_for_query(
    query: str,
    rows: list[tuple[str, str]],
    *,
    subtopics: list[str] | None = None,
) -> str:
    """Optional one-line n-gram hint (matched subtopic or list item)."""
    hints: list[str] = []
    sub = match_subtopic(query, subtopics or [])
    if sub:
        hints.append(f"Matched subtopic: {sub}")
    idx = list_item_index_from_query(query)
    if idx is not None:
        for role, content in reversed(rows):
            if role != "assistant":
                continue
            item = extract_list_item(content, idx)
            if item:
                hints.append(f"List item {idx}: {item[:200]}")
                break
    return "; ".join(hints)
