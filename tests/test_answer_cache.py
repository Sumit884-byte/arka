"""Tests for encyclopedic answer cache."""

from __future__ import annotations

import time
from pathlib import Path
from unittest import mock

import pytest

from arka.core import answer_cache


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setattr(answer_cache, "config_dir", lambda: cfg)
    monkeypatch.setenv("ARKA_ANSWER_CACHE", "1")
    monkeypatch.setenv("ARKA_ANSWER_CACHE_TTL", "86400")
    answer_cache.clear_answer_cache()
    return cfg


def test_normalize_cache_key() -> None:
    assert answer_cache.normalize_cache_key("Who Is Elon?") == "who is elon"
    assert answer_cache.normalize_cache_key("  what   is  python  ") == "what is python"


def test_is_encyclopedic_query() -> None:
    assert answer_cache.is_encyclopedic_query("who is elon")
    assert answer_cache.is_encyclopedic_query("what is python")
    assert not answer_cache.is_encyclopedic_query("install fish")


def test_cache_miss_then_hit(cache_dir: Path) -> None:
    assert answer_cache.get_cached_answer("who is elon") is None
    answer_cache.set_cached_answer("who is elon", "[FROM MEMORY] Elon Musk is …")
    assert answer_cache.get_cached_answer("who is elon") == "[FROM MEMORY] Elon Musk is …"
    assert answer_cache.get_cached_answer("Who Is Elon?") == "[FROM MEMORY] Elon Musk is …"


def test_cache_respects_ttl(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARKA_ANSWER_CACHE_TTL", "1")
    answer_cache.set_cached_answer("what is rust", "A systems language.")
    assert answer_cache.get_cached_answer("what is rust") == "A systems language."
    old = time.time() - 5
    store = answer_cache._load_store()
    store["entries"]["what is rust"]["updated"] = old
    answer_cache._save_store(store)
    assert answer_cache.get_cached_answer("what is rust") is None


def test_answer_question_uses_cache_without_llm(cache_dir: Path) -> None:
    from arka.agent import chat

    answer_cache.set_cached_answer("who is elon", "[FROM MEMORY] Cached Elon answer.")

    with mock.patch("arka.agent.chat.llm_complete") as llm_mock:
        prov, text = chat.answer_question("who is elon", use_session=False)

    assert prov == "cache"
    assert text == "[FROM MEMORY] Cached Elon answer."
    llm_mock.assert_not_called()


def test_answer_question_stores_llm_answer(cache_dir: Path) -> None:
    from arka.agent import chat

    with mock.patch("arka.agent.chat.llm_complete", return_value="[FROM MEMORY] Fresh answer."):
        with mock.patch("arka.agent.chat.get_intent", return_value=("ANSWER", "who is elon")):
            with mock.patch("arka.agent.chat.snippet_lookup", return_value=""):
                with mock.patch("arka.agent.chat.build_session_context", return_value=""):
                    prov, text = chat.answer_question("who is elon", use_session=False)

    assert prov == "memory"
    assert text == "[FROM MEMORY] Fresh answer."
    assert answer_cache.get_cached_answer("who is elon") == "[FROM MEMORY] Fresh answer."
