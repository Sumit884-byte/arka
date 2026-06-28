#!/usr/bin/env python3
"""Transcript Q&A retrieval — TurboQuant + Ollama embeddings."""

from __future__ import annotations

import os
import re
from pathlib import Path

from arka_turboquant_rag import (
    DEFAULT_CONTEXT as _DEFAULT_CONTEXT,
    retrieve_transcript_context as _tq_retrieve,
)

QA_CONTEXT_CHARS = int(os.environ.get("ARKA_MEDIA_QA_CONTEXT", str(_DEFAULT_CONTEXT)))


def _question_intent(question: str) -> str:
    q = question.lower()
    if re.search(r"\bwho\b", q):
        return "who"
    if re.search(r"\bwhy\b", q):
        return "why"
    if re.search(r"\bhow\b", q):
        return "how"
    if re.search(r"\bwhen\b", q):
        return "when"
    if re.search(r"\bwhere\b", q):
        return "where"
    if re.search(r"\blist\b|name all|characters|who are", q):
        return "list"
    if re.search(r"\bcompare|difference|versus|vs\b", q):
        return "compare"
    if re.search(r"\bwhat happened|what did|what is|what was\b", q):
        return "what"
    return "general"


def answer_system_prompt(question: str) -> str:
    intent = _question_intent(question)
    base = (
        "Answer the user's question using ONLY the transcript excerpts provided. "
        "Do NOT summarize the whole video or give a general plot overview unless explicitly asked. "
        "Do NOT invent characters, events, or motives absent from the excerpts. "
        "Use names exactly as they appear in the transcript. "
        "If excerpts conflict or are unclear, say so briefly."
    )
    hints = {
        "who": " Focus on identifying people and their roles/relationships.",
        "why": " Explain reasons, motivations, and cause-and-effect from the excerpts.",
        "how": " Explain the sequence of actions or mechanism step by step.",
        "when": " Give timing or order of events when present in the excerpts.",
        "where": " Identify places or settings mentioned.",
        "what": " State what happened relevant to the question; stay specific.",
        "list": " Use a short bullet list if multiple items are requested.",
        "compare": " Contrast the entities or events asked about; note similarities and differences.",
        "general": " Be direct and concise; answer exactly what was asked.",
    }
    return base + hints.get(intent, hints["general"])


def retrieve_transcript_context(
    text: str,
    question: str,
    *,
    src: Path | None = None,
    max_chars: int = QA_CONTEXT_CHARS,
) -> str:
    return _tq_retrieve(text, question, src=src, max_chars=max_chars)
