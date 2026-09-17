"""Memory must only come back when it matches the current question."""

from __future__ import annotations

from unittest.mock import patch

from arka.agent.chat import build_session_context, prior_session_context, topic_overlap
from arka.agent.daily_brief import news_summary_looks_off_topic
from arka.core.habitat import should_skip_memory_recall


_CUDA = (
    "NVIDIA's domain-specific library approach helps developers transition "
    "from CPU programming to CUDA by providing cuDNN and TensorRT."
)
_GTC = (
    "Jensen Huang opened GTC by introducing Vera Rubin as Blackwell's successor "
    "for AI factories."
)
_US_NEWS = "The Senate passed a stopgap funding bill after overnight talks."


def test_topic_overlap_keeps_related_memory() -> None:
    assert topic_overlap("what did jensen announce at gtc", _GTC)
    assert not topic_overlap("what happened in usa today", _CUDA)


def test_usa_today_skips_memory_recall() -> None:
    assert should_skip_memory_recall("what happened in usa today")
    assert should_skip_memory_recall("latest breaking news")
    assert not should_skip_memory_recall("what did jensen announce at gtc")


def test_prior_session_drops_unrelated_cuda() -> None:
    history = [
        {"role": "user", "content": "what happened in nvidia gtc"},
        {"role": "assistant", "content": _CUDA},
        {"role": "user", "content": "what happened in usa today"},
    ]
    with patch("arka.agent.chat.load_session", return_value=history):
        _items, relevant = prior_session_context("what happened in usa today")
    assert not any("CUDA" in (msg.get("content") or "") for msg in relevant)


def test_prior_session_keeps_gtc_follow_up() -> None:
    history = [
        {"role": "user", "content": "what happened in nvidia gtc"},
        {"role": "assistant", "content": _GTC},
    ]
    with patch("arka.agent.chat.load_session", return_value=history):
        _items, relevant = prior_session_context("what did jensen announce at gtc")
    assert any("Vera Rubin" in (msg.get("content") or "") for msg in relevant)


def test_session_context_does_not_paste_cuda_into_usa_news() -> None:
    history = [
        {"role": "user", "content": "what happened in nvidia gtc"},
        {"role": "assistant", "content": _CUDA},
    ]
    with (
        patch("arka.agent.chat.get_live_location", return_value={"location_string": "Test"}),
        patch("arka.agent.chat.load_session", return_value=history),
        patch("arka.agent.core.memory_context_for", return_value=_CUDA),
    ):
        ctx = build_session_context("what happened in usa today")
    assert "CUDA" not in ctx
    assert "cuDNN" not in ctx


def test_session_context_retrieves_matching_gtc_memory() -> None:
    history = [
        {"role": "user", "content": "what happened in nvidia gtc"},
        {"role": "assistant", "content": _GTC},
    ]
    with (
        patch("arka.agent.chat.get_live_location", return_value={"location_string": "Test"}),
        patch("arka.agent.chat.load_session", return_value=history),
        patch("arka.agent.core.memory_context_for", return_value=_GTC),
    ):
        ctx = build_session_context("what did jensen announce at gtc")
    assert "Vera Rubin" in ctx


def test_cuda_recap_is_off_topic_for_usa_news() -> None:
    assert news_summary_looks_off_topic("what happened in usa today", _CUDA)
    assert not news_summary_looks_off_topic("what happened in usa today", _US_NEWS)


def test_live_news_does_not_fall_through_to_memory() -> None:
    from arka.agent.chat import answer_question

    with patch("arka.agent.daily_brief.summarize_news_web", return_value=""):
        _prov, answer = answer_question("what happened in usa today", use_session=False)
    assert "CUDA" not in answer
    assert "article-quality" in answer.lower() or "headlines" in answer.lower()
    assert "[FROM MEMORY]" not in answer
