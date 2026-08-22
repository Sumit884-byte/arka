"""Per-session topic/subtopic memory for web chat — avoid repeating subtopics."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

CONTINUE_RE = re.compile(
    r"(?i)\b("
    r"next|continue|more|another|go on|keep going|what else|"
    r"tell more|tell me more|say more|go deeper|elaborate|expand|"
    r"next subtopic|next topic|another subtopic|keep learning"
    r")\b"
)
TOPIC_RE = re.compile(
    r"(?i)(?:"
    r"(?:learn|study|teach me|explain|reading on|daily reading on|topic[:\s]+)"
    r"\s+(?:about\s+)?(.+)"
    r"|"
    r"(?:^|\.\s+)(?:about|regarding)\s+(.+?)(?:[.?!]|$)"
    r")"
)
_ON_PHRASE_RE = re.compile(r"(?i)\b(?:working|focus(?:ing)?|depends|based)\s+on\b")
SUBTOPICS_LINE_RE = re.compile(r"(?im)^SUBTOPICS:\s*(.+)$")
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
H3_RE = re.compile(r"^###\s+\*?\*?(.+?)\*?\*?\s*:?\s*$", re.M)
NEW_TOPIC_RE = re.compile(
    r"(?i)\b(switch to|new topic|change topic to|start over with)\s+(.+)$"
)
RESET_RE = re.compile(r"(?i)\b(forget that|start over)\b")
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "for", "with", "about", "what", "how", "why",
        "when", "where", "who", "are", "is", "was", "were", "be", "been", "being", "have",
        "has", "had", "do", "does", "did", "will", "would", "could", "should", "can", "may",
        "might", "must", "that", "this", "these", "those", "your", "you", "they", "them",
        "their", "from", "into", "onto", "over", "under", "not", "also", "just", "like",
        "some", "any", "all", "one", "two", "more", "most", "other", "such", "only", "own",
        "same", "than", "then", "there", "here", "very", "much", "many", "tell", "give",
    }
)


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def memory_root() -> Path:
    return _config_dir() / "web-topic-memory"


def _safe_key(channel: str, chat_id: str) -> str:
    ch = re.sub(r"[^a-zA-Z0-9_.@-]", "_", (channel or "web").strip())[:32]
    cid = re.sub(r"[^a-zA-Z0-9_.@-]", "_", (chat_id or "default").strip())[:64]
    return f"{ch}__{cid}"


def state_path(channel: str, chat_id: str) -> Path:
    return memory_root() / f"{_safe_key(channel, chat_id)}.json"


def load_state(channel: str, chat_id: str) -> dict[str, Any]:
    path = state_path(channel, chat_id)
    default: dict[str, Any] = {
        "channel": channel,
        "chat_id": chat_id,
        "topic": "",
        "covered_subtopics": [],
        "updated_at": 0.0,
    }
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    data.setdefault("topic", "")
    data.setdefault("covered_subtopics", [])
    return data


def save_state(state: dict[str, Any]) -> None:
    root = memory_root()
    root.mkdir(parents=True, exist_ok=True)
    channel = str(state.get("channel") or "web")
    chat_id = str(state.get("chat_id") or "default")
    state["channel"] = channel
    state["chat_id"] = chat_id
    state["updated_at"] = time.time()
    covered = state.get("covered_subtopics") or []
    if isinstance(covered, list):
        state["covered_subtopics"] = [str(x).strip() for x in covered if str(x).strip()][-50:]
    state_path(channel, chat_id).write_text(json.dumps(state, indent=2), encoding="utf-8")


def infer_topic_from_session(session_ctx: str) -> str | None:
    """Best-effort topic from stored chat when the user only says continue/tell more."""
    ctx = (session_ctx or "").strip()
    if not ctx:
        return None
    for line in ctx.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("user:"):
            msg = stripped.split(":", 1)[1].strip()
            if msg and not CONTINUE_RE.search(msg) and len(msg.split()) >= 4:
                return msg[:160]
    for header in H2_RE.findall(ctx) + H3_RE.findall(ctx):
        title = header.strip(" *:")
        if title and len(title) > 3:
            return title[:160]
    return None


def _topic_tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9']{3,}", (text or "").lower())
        if w not in _STOPWORDS
    }


def _clean_inferred_topic(raw: str) -> str | None:
    picked = " ".join((raw or "").split()).strip(" .?!")
    if not picked:
        return None
    if len(picked.split()) > 12:
        return None
    if len(picked) > 80:
        picked = picked[:80].rsplit(" ", 1)[0].strip()
    return picked or None


def covered_related_to_user(user_text: str, covered: list[str] | None) -> bool:
    """True when stored subtopics plausibly belong to the user's current message."""
    subs = [str(x).strip() for x in (covered or []) if str(x).strip()]
    if not subs:
        return True
    try:
        from arka.core.context_ngrams import match_subtopic, overlap_score

        if match_subtopic(user_text, subs):
            return True
        if max(overlap_score(user_text, sub.replace("-", " ")) for sub in subs) >= 1.25:
            return True
    except ImportError:
        pass
    words = _topic_tokens(user_text)
    if not words:
        return False
    for sub in subs[-12:]:
        if words & _topic_tokens(sub):
            return True
    return False


def is_continue_request(user_text: str) -> bool:
    return bool(CONTINUE_RE.search(user_text or ""))


def topics_related(user_text: str, topic: str, covered: list[str] | None = None) -> bool:
    """True when the user's message plausibly continues the stored topic."""
    if not (topic or "").strip():
        return False
    if is_continue_request(user_text):
        return True
    try:
        from arka.core.context_ngrams import match_subtopic, overlap_score, query_relates_to_texts

        subs = [str(x).strip() for x in (covered or []) if str(x).strip()]
        if match_subtopic(user_text, subs):
            return True
        corpus = [topic, *subs]
        if query_relates_to_texts(user_text, corpus, threshold=1.25):
            return True
        if overlap_score(user_text, topic) >= 1.5:
            return True
    except ImportError:
        pass
    words = _topic_tokens(user_text)
    corpus = _topic_tokens(topic)
    for sub in covered or []:
        corpus |= _topic_tokens(str(sub))
    if not words or not corpus:
        return False
    shared = words & corpus
    if len(shared) >= 2:
        return True
    return len(shared) / min(len(words), len(corpus)) >= 0.18


def infer_topic(user_text: str, prior_topic: str | None) -> str | None:
    text = " ".join((user_text or "").split()).strip()
    if not text:
        return None
    switch = NEW_TOPIC_RE.search(text)
    if switch:
        picked = switch.group(2).strip(" .?!")
        return picked[:160] if picked else None
    if RESET_RE.search(text):
        m = TOPIC_RE.search(text)
        if m:
            picked = (m.group(1) or m.group(2) or "").strip(" .?!")
            return picked[:160] if picked else None
        return None
    if prior_topic and is_continue_request(text):
        return prior_topic
    if _ON_PHRASE_RE.search(text):
        return None
    m = TOPIC_RE.search(text)
    if m:
        picked = (m.group(1) or m.group(2) or "").strip(" .?!")
        cleaned = _clean_inferred_topic(picked)
        if cleaned:
            return cleaned
    return None


def parse_subtopics(assistant_text: str) -> list[str]:
    text = assistant_text or ""
    found: list[str] = []
    line_match = SUBTOPICS_LINE_RE.search(text)
    if line_match:
        found.extend(part.strip() for part in line_match.group(1).split(",") if part.strip())
    for header in H2_RE.findall(text) + H3_RE.findall(text):
        title = header.strip(" *:")
        if not title or re.search(r"(?i)follow[- ]?up questions?", title):
            continue
        if title.lower() not in {f.lower() for f in found}:
            found.append(title)
    return found[:12]


def build_system_addon(state: dict[str, Any], *, continuing: bool = False) -> str:
    topic = (state.get("topic") or "").strip()
    if not topic or not continuing:
        return ""
    covered = [str(x).strip() for x in (state.get("covered_subtopics") or []) if str(x).strip()]
    lines = [
        f"Active topic: {topic}",
        "The user asked to continue. Teach or answer using a NEW subtopic they have not received.",
        "Do not repeat already-covered subtopics except for one short bridging sentence.",
    ]
    if covered:
        lines.append("Already covered subtopics (do not repeat): " + "; ".join(covered[-20:]))
    lines.append(
        "End every reply with a line exactly like: SUBTOPICS: short name1, short name2 "
        "(the subtopic(s) you covered this turn)."
    )
    return "\n".join(lines)


def prepare_turn(
    channel: str,
    chat_id: str,
    user_text: str,
    *,
    session_ctx: str = "",
) -> tuple[str, dict[str, Any]]:
    state = load_state(channel, chat_id)
    prior = (state.get("topic") or "").strip()
    covered = [str(x).strip() for x in (state.get("covered_subtopics") or []) if str(x).strip()]
    text = " ".join((user_text or "").split()).strip()
    continuing = is_continue_request(text)

    try:
        from arka.core.chat_context_gate import (
            is_coding_or_game_task,
            is_language_learning_request,
            named_language,
        )

        if is_coding_or_game_task(text) and not is_language_learning_request(text):
            if prior and not is_coding_or_game_task(prior):
                state = {
                    "channel": channel,
                    "chat_id": chat_id,
                    "topic": "",
                    "covered_subtopics": [],
                    "updated_at": time.time(),
                }
                save_state(state)
                prior = ""
                covered = []
        user_lang = named_language(text)
        if user_lang:
            prior_blob = " ".join([prior, *covered])
            prior_lang = named_language(prior_blob)
            if prior_lang and prior_lang != user_lang:
                state = {
                    "channel": channel,
                    "chat_id": chat_id,
                    "topic": "",
                    "covered_subtopics": [],
                    "updated_at": time.time(),
                }
                save_state(state)
                prior = ""
                covered = []
    except ImportError:
        pass

    topic = infer_topic(text, prior or None)
    if continuing and not topic and session_ctx:
        topic = infer_topic_from_session(session_ctx) or ""

    if continuing and topic:
        state["topic"] = topic
        return build_system_addon(state, continuing=True), state

    if topic and topic != prior:
        state = {
            "channel": channel,
            "chat_id": chat_id,
            "topic": topic,
            "covered_subtopics": [],
            "updated_at": time.time(),
        }
        return "", state

    if prior and topics_related(text, prior, covered):
        if covered and not covered_related_to_user(text, covered):
            state = {
                "channel": channel,
                "chat_id": chat_id,
                "topic": "",
                "covered_subtopics": [],
                "updated_at": time.time(),
            }
            save_state(state)
            return "", state
        state["topic"] = prior
        return "", state

    if prior:
        state = {
            "channel": channel,
            "chat_id": chat_id,
            "topic": "",
            "covered_subtopics": [],
            "updated_at": time.time(),
        }
        save_state(state)
    return "", state


def record_turn(state: dict[str, Any], assistant_text: str) -> None:
    if not (state.get("topic") or "").strip():
        subs = parse_subtopics(assistant_text)
        if subs and not state.get("topic"):
            state["topic"] = subs[0][:80]
    new_subs = parse_subtopics(assistant_text)
    if not new_subs:
        return
    covered = [str(x).strip() for x in (state.get("covered_subtopics") or []) if str(x).strip()]
    seen = {c.lower() for c in covered}
    for sub in new_subs:
        if sub.lower() not in seen:
            covered.append(sub)
            seen.add(sub.lower())
    state["covered_subtopics"] = covered[-50:]
    save_state(state)


def reset_state(channel: str, chat_id: str) -> None:
    path = state_path(channel, chat_id)
    if path.is_file():
        path.unlink(missing_ok=True)
