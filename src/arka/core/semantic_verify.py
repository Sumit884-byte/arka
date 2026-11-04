"""Parse llm.txt ask contracts and score answers with semantic similarity."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

_CASE_RE = re.compile(
    r"(?m)^### case:\s*(?P<id>[a-z0-9-]+)\s*$\n"
    r"^question:\s*(?P<question>.+?)\s*$\n"
    r"(?:^must_mean:\s*(?P<must_mean>.+?)\s*$\n|^must_not:\s*(?P<must_not>.+?)\s*$\n){2}"
    r"^good:\s*(?P<good>.+?)\s*$\n"
    r"^bad:\s*(?P<bad>.+?)\s*$"
)
_WORD_RE = re.compile(r"[a-z0-9]{2,}")
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "not",
        "but",
        "you",
        "your",
        "our",
        "its",
        "after",
        "about",
        "than",
        "then",
        "when",
        "what",
        "who",
        "how",
        "today",
        "latest",
    }
)


@dataclass(frozen=True)
class AskContract:
    case_id: str
    question: str
    must_mean: str
    must_not: tuple[str, ...]
    good: str
    bad: str


@dataclass(frozen=True)
class SemanticVerdict:
    passed: bool
    score: float
    reasons: tuple[str, ...]
    method: str = "bow"


def llm_txt_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "llm.txt"
        if candidate.is_file():
            return candidate
    return Path("llm.txt")


def parse_ask_contracts(text: str) -> list[AskContract]:
    rows: list[AskContract] = []
    for match in _CASE_RE.finditer(text or ""):
        forbidden = tuple(
            part.strip()
            for part in (match.group("must_not") or "").split(";")
            if part.strip()
        )
        rows.append(
            AskContract(
                case_id=match.group("id").strip(),
                question=match.group("question").strip(),
                must_mean=match.group("must_mean").strip(),
                must_not=forbidden,
                good=match.group("good").strip(),
                bad=match.group("bad").strip(),
            )
        )
    return rows


def load_ask_contracts(path: Path | None = None) -> list[AskContract]:
    target = path or llm_txt_path()
    return parse_ask_contracts(target.read_text(encoding="utf-8"))


def _tokens(text: str) -> list[str]:
    return [tok for tok in _WORD_RE.findall((text or "").lower()) if tok not in _STOP]


def bow_cosine(left: str, right: str) -> float:
    """Bag-of-words cosine similarity (offline, no model download)."""
    left_toks = _tokens(left)
    right_toks = _tokens(right)
    if not left_toks or not right_toks:
        return 0.0
    left_counts: dict[str, int] = {}
    right_counts: dict[str, int] = {}
    for tok in left_toks:
        left_counts[tok] = left_counts.get(tok, 0) + 1
    for tok in right_toks:
        right_counts[tok] = right_counts.get(tok, 0) + 1
    keys = set(left_counts) | set(right_counts)
    dot = sum(left_counts.get(key, 0) * right_counts.get(key, 0) for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left_counts.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counts.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def forbidden_hits(answer: str, phrases: tuple[str, ...]) -> list[str]:
    body = (answer or "").lower()
    return [phrase for phrase in phrases if phrase.lower() in body]


def semantic_score(answer: str, *, must_mean: str, good: str) -> float:
    """Blend similarity to the meaning line and the gold example."""
    to_mean = bow_cosine(answer, must_mean)
    to_good = bow_cosine(answer, good)
    return max(to_mean, to_good)


def semantic_ai_enabled() -> bool:
    raw = os.environ.get("ARKA_SEMANTIC_AI", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def ai_semantic_score(question: str, answer: str, must_mean: str) -> float | None:
    """Optional judge model: return 0-1 similarity, or None if unavailable."""
    if not semantic_ai_enabled():
        return None
    try:
        from arka.llm.fallback import llm_complete
    except ImportError:
        return None
    prompt = (
        "Score how well the answer matches the intended meaning. "
        "Reply with only a number between 0 and 1.\n"
        f"Question: {question}\n"
        f"Must mean: {must_mean}\n"
        f"Answer: {answer}\n"
    )
    raw = (
        llm_complete(
            "You score semantic similarity. Output a single decimal 0-1.",
            prompt,
            temperature=0.0,
            task="chat",
        )
        or ""
    )
    match = re.search(r"\b(0(?:\.\d+)?|1(?:\.0+)?)\b", raw)
    if not match:
        return None
    return min(1.0, max(0.0, float(match.group(1))))


def verify_semantic_answer(
    answer: str,
    contract: AskContract,
    *,
    min_score: float = 0.22,
) -> SemanticVerdict:
    reasons: list[str] = []
    hits = forbidden_hits(answer, contract.must_not)
    if hits:
        reasons.append("forbidden: " + "; ".join(hits))
    score = semantic_score(answer, must_mean=contract.must_mean, good=contract.good)
    method = "bow"
    judged = ai_semantic_score(contract.question, answer, contract.must_mean)
    if judged is not None:
        score = max(score, judged)
        method = "bow+ai"
    if score < min_score:
        reasons.append(f"similarity {score:.3f} < {min_score:.2f}")
    return SemanticVerdict(
        passed=not reasons,
        score=score,
        reasons=tuple(reasons),
        method=method,
    )
