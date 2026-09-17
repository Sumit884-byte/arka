"""Full search fallback chains: Bright Data → Tavily → Brave → Serper → ddgs."""

from __future__ import annotations

import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

from arka.agent import chat
from arka.core.fast_encyclopedia import (
    _office_search_topic,
    _search_extract,
    fast_encyclopedic_answer,
    rewrite_office_search_query,
)
from arka.integrations import web_search


HIT = {
    "id": 0,
    "title": "Minister of Finance (India)",
    "link": "https://en.wikipedia.org/wiki/Minister_of_Finance_(India)",
    "snippet": "Nirmala Sitharaman is the current Finance Minister of India and has served since 2019.",
}
STUB = {
    "id": 0,
    "title": "List of current finance ministers",
    "link": "https://en.wikipedia.org/wiki/List_of_current_finance_ministers",
    "snippet": "This is a list of current finance ministers of the 193 United Nations member states.",
}
DDGS_HIT = {
    "id": 0,
    "title": "Finance Minister of India",
    "link": "https://example.com/fm",
    "snippet": "Nirmala Sitharaman is India's finance minister, appointed in May 2019 after Arun Jaitley.",
}


@pytest.fixture
def isolated_search_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(web_search, "_load_keys", lambda: None)
    for name in ("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "SERPER_API_KEY", "ARKA_SEARCH_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(chat, "_ddgs_retry_count", lambda: 1)
    monkeypatch.setattr(chat, "_ddgs_timeout_seconds", lambda: 5)


def _set_keys(monkeypatch: pytest.MonkeyPatch, *providers: str) -> None:
    mapping = {
        "tavily": "TAVILY_API_KEY",
        "brave": "BRAVE_SEARCH_API_KEY",
        "serper": "SERPER_API_KEY",
    }
    for name in mapping.values():
        monkeypatch.delenv(name, raising=False)
    for provider in providers:
        monkeypatch.setenv(mapping[provider], f"{provider}-test-key")


def _row(source: str) -> dict[str, Any]:
    return {
        "id": 0,
        "title": f"{source} title about the Taj Mahal in Agra",
        "link": f"https://example.com/{source}",
        "snippet": f"{source} result: Shah Jahan commissioned the Taj Mahal in Agra, India.",
    }


# --- Tavily → Brave → Serper -------------------------------------------------


def test_api_chain_skips_missing_keys(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch, "serper")
    called: list[str] = []

    monkeypatch.setattr(web_search, "tavily_search", lambda *a, **k: called.append("tavily") or [])
    monkeypatch.setattr(web_search, "brave_search", lambda *a, **k: called.append("brave") or [])
    monkeypatch.setattr(web_search, "serper_search", lambda *a, **k: called.append("serper") or [_row("serper")])

    rows = web_search.configured_api_search("who is the current finance minister")
    assert rows[0]["link"] == "https://example.com/serper"
    assert called == ["serper"]


def test_api_chain_tavily_wins_before_brave_and_serper(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch, "tavily", "brave", "serper")
    called: list[str] = []

    def tavily(query, max_results=5):
        called.append("tavily")
        return [_row("tavily")]

    def later(name):
        def fn(query, max_results=5):
            called.append(name)
            return [_row(name)]

        return fn

    monkeypatch.setattr(web_search, "tavily_search", tavily)
    monkeypatch.setattr(web_search, "brave_search", later("brave"))
    monkeypatch.setattr(web_search, "serper_search", later("serper"))

    rows = web_search.configured_api_search("taj mahal")
    assert rows[0]["title"].startswith("tavily")
    assert called == ["tavily"]


def test_api_chain_empty_tavily_falls_to_brave(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch, "tavily", "brave", "serper")
    called: list[str] = []
    monkeypatch.setattr(web_search, "tavily_search", lambda *a, **k: called.append("tavily") or [])
    monkeypatch.setattr(web_search, "brave_search", lambda *a, **k: called.append("brave") or [_row("brave")])
    monkeypatch.setattr(web_search, "serper_search", lambda *a, **k: called.append("serper") or [_row("serper")])

    rows = web_search.configured_api_search("finance minister")
    assert rows[0]["title"].startswith("brave")
    assert called == ["tavily", "brave"]


def test_api_chain_errors_continue_to_next_provider(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch, "tavily", "brave", "serper")
    called: list[str] = []

    def boom(query, max_results=5):
        called.append("tavily")
        raise urllib.error.URLError("timed out")

    def empty(query, max_results=5):
        called.append("brave")
        raise TimeoutError("brave timeout")

    monkeypatch.setattr(web_search, "tavily_search", boom)
    monkeypatch.setattr(web_search, "brave_search", empty)
    monkeypatch.setattr(web_search, "serper_search", lambda *a, **k: called.append("serper") or [_row("serper")])

    rows = web_search.configured_api_search("current finance minister")
    assert rows[0]["title"].startswith("serper")
    assert called == ["tavily", "brave", "serper"]


def test_api_chain_all_empty_returns_empty(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch, "tavily", "brave", "serper")
    monkeypatch.setattr(web_search, "tavily_search", lambda *a, **k: [])
    monkeypatch.setattr(web_search, "brave_search", lambda *a, **k: [])
    monkeypatch.setattr(web_search, "serper_search", lambda *a, **k: [])
    assert web_search.configured_api_search("anything") == []


def test_api_chain_no_keys_returns_empty(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch)
    monkeypatch.setattr(
        web_search,
        "tavily_search",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("tavily should not run")),
    )
    assert web_search.configured_api_search("taj mahal") == []
    assert web_search.configured_api_search("") == []


def test_api_chain_preferred_provider_runs_first(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch, "tavily", "brave", "serper")
    monkeypatch.setenv("ARKA_SEARCH_PROVIDER", "serper")
    called: list[str] = []
    monkeypatch.setattr(web_search, "tavily_search", lambda *a, **k: called.append("tavily") or [_row("tavily")])
    monkeypatch.setattr(web_search, "brave_search", lambda *a, **k: called.append("brave") or [_row("brave")])
    monkeypatch.setattr(web_search, "serper_search", lambda *a, **k: called.append("serper") or [_row("serper")])

    rows = web_search.configured_api_search("who made taj mahal")
    assert rows[0]["title"].startswith("serper")
    assert called == ["serper"]


def test_tavily_client_skips_without_key_and_posts_with_key(isolated_search_keys, monkeypatch):
    _set_keys(monkeypatch)
    assert web_search.tavily_search("q") == []

    _set_keys(monkeypatch, "tavily")
    captured: dict[str, Any] = {}

    def fake_http(url, *, method="GET", headers=None, body=None, timeout=None):
        captured.update(url=url, method=method, headers=headers or {}, body=body)
        return {
            "answer": "Shah Jahan commissioned the Taj Mahal.",
            "results": [
                {
                    "title": "Taj Mahal",
                    "url": "en.wikipedia.org/wiki/Taj_Mahal",
                    "content": "White marble mausoleum in Agra, India.",
                }
            ],
        }

    monkeypatch.setattr(web_search, "_http_json", fake_http)
    rows = web_search.tavily_search("who made taj mahal", max_results=3)
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["method"] == "POST"
    assert "Bearer tavily-test-key" in captured["headers"]["Authorization"]
    assert rows[0]["link"] == "https://en.wikipedia.org/wiki/Taj_Mahal"
    assert "Shah Jahan" in rows[0]["snippet"]


# --- Bright Data → APIs → ddgs ----------------------------------------------


def test_search_brightdata_wins_and_skips_rest(isolated_search_keys, monkeypatch):
    order: list[str] = []
    bd = [{**HIT, "title": "Bright Data hit"}]

    monkeypatch.setattr("arka.integrations.brightdata_mcp.prefer_brightdata_search", lambda: True)
    monkeypatch.setattr(
        "arka.integrations.brightdata_retrieval.should_trigger_brightdata_search",
        lambda q: True,
    )
    monkeypatch.setattr(
        "arka.integrations.brightdata_mcp.brightdata_search",
        lambda *a, **k: order.append("brightdata") or bd,
    )
    monkeypatch.setattr(
        "arka.integrations.web_search.configured_api_search",
        lambda *a, **k: order.append("apis") or [_row("tavily")],
    )
    monkeypatch.setattr(
        chat,
        "_duckduckgo_search_once",
        lambda *a, **k: order.append("ddgs") or [DDGS_HIT],
    )

    assert chat.duckduckgo_search("who is the current finance minister") == bd
    assert order == ["brightdata"]


def test_search_empty_brightdata_falls_to_tavily(isolated_search_keys, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr("arka.integrations.brightdata_mcp.prefer_brightdata_search", lambda: True)
    monkeypatch.setattr(
        "arka.integrations.brightdata_retrieval.should_trigger_brightdata_search",
        lambda q: True,
    )
    monkeypatch.setattr(
        "arka.integrations.brightdata_mcp.brightdata_search",
        lambda *a, **k: order.append("brightdata") or [],
    )
    monkeypatch.setattr(
        "arka.integrations.web_search.configured_api_search",
        lambda *a, **k: order.append("apis") or [_row("tavily")],
    )
    monkeypatch.setattr(
        chat,
        "_duckduckgo_search_once",
        lambda *a, **k: order.append("ddgs") or [DDGS_HIT],
    )

    rows = chat.duckduckgo_search("live news today")
    assert rows[0]["title"].startswith("tavily")
    assert order == ["brightdata", "apis"]


def test_search_apis_empty_falls_to_ddgs(isolated_search_keys, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr("arka.integrations.brightdata_mcp.prefer_brightdata_search", lambda: False)
    monkeypatch.setattr(
        "arka.integrations.web_search.configured_api_search",
        lambda *a, **k: order.append("apis") or [],
    )
    monkeypatch.setattr(
        chat,
        "_duckduckgo_search_once",
        lambda *a, **k: order.append("ddgs") or [DDGS_HIT],
    )

    rows = chat.duckduckgo_search("who made taj mahal")
    assert rows == [DDGS_HIT]
    assert order == ["apis", "ddgs"]


def test_search_all_backends_exhausted(isolated_search_keys, monkeypatch):
    monkeypatch.setattr("arka.integrations.brightdata_mcp.prefer_brightdata_search", lambda: True)
    monkeypatch.setattr(
        "arka.integrations.brightdata_retrieval.should_trigger_brightdata_search",
        lambda q: True,
    )
    monkeypatch.setattr("arka.integrations.brightdata_mcp.brightdata_search", lambda *a, **k: [])
    monkeypatch.setattr("arka.integrations.web_search.configured_api_search", lambda *a, **k: [])
    monkeypatch.setattr(chat, "_ddgs_retry_count", lambda: 2)
    with (
        patch.object(chat, "_duckduckgo_search_once", side_effect=TimeoutError("search timed out")) as once,
        patch.object(chat.time, "sleep", return_value=None),
    ):
        assert chat.duckduckgo_search("news") == []
    assert once.call_count == 2


def test_search_skips_brightdata_when_not_preferred(isolated_search_keys, monkeypatch):
    called = {"bd": 0}
    monkeypatch.setattr("arka.integrations.brightdata_mcp.prefer_brightdata_search", lambda: False)

    def bd(*a, **k):
        called["bd"] += 1
        return [HIT]

    monkeypatch.setattr("arka.integrations.brightdata_mcp.brightdata_search", bd)
    monkeypatch.setattr("arka.integrations.web_search.configured_api_search", lambda *a, **k: [_row("brave")])
    monkeypatch.setattr(chat, "_duckduckgo_search_once", lambda *a, **k: [DDGS_HIT])

    rows = chat.duckduckgo_search("anything")
    assert rows[0]["title"].startswith("brave")
    assert called["bd"] == 0


# --- Encyclopedia: memory → APIs → shared search ----------------------------


def test_encyclopedia_memory_short_circuits_search(isolated_search_keys, monkeypatch):
    called = {"api": 0, "ddg": 0}
    monkeypatch.setattr(
        "arka.integrations.web_search.configured_api_search",
        lambda *a, **k: called.__setitem__("api", called["api"] + 1) or [HIT],
    )
    monkeypatch.setattr(
        "arka.agent.chat.duckduckgo_search",
        lambda *a, **k: called.__setitem__("ddg", called["ddg"] + 1) or [DDGS_HIT],
    )
    answer = fast_encyclopedic_answer("who made taj mahal")
    assert answer is not None
    assert answer.startswith("[FROM MEMORY]")
    assert "Shah Jahan" in answer
    assert called == {"api": 0, "ddg": 0}


def test_encyclopedia_disabled_skips_live_search(isolated_search_keys, monkeypatch):
    monkeypatch.setenv("ARKA_FAST_SEARCH", "0")
    monkeypatch.setattr(
        "arka.integrations.web_search.configured_api_search",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("search disabled")),
    )
    assert fast_encyclopedic_answer("who is the current finance minister") is None


def test_encyclopedia_does_not_paste_search_as_answer(isolated_search_keys, monkeypatch):
    monkeypatch.setattr("arka.integrations.web_search.configured_api_search", lambda *a, **k: [HIT])
    answer = fast_encyclopedic_answer("who is the current finance minister")
    assert answer is None


def test_search_extract_stub_api_falls_to_ddgs(isolated_search_keys, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(
        "arka.integrations.web_search.configured_api_search",
        lambda *a, **k: order.append("apis") or [STUB],
    )
    monkeypatch.setattr(
        "arka.agent.chat.duckduckgo_search",
        lambda *a, **k: order.append("ddgs") or [DDGS_HIT],
    )
    answer = _search_extract("who is the current finance minister")
    assert answer is not None
    assert "Nirmala Sitharaman" in answer
    assert "This is a list" not in answer
    assert order == ["apis", "ddgs"]


def test_encyclopedia_empty_api_falls_to_ddgs(isolated_search_keys, monkeypatch):
    monkeypatch.setattr("arka.integrations.web_search.configured_api_search", lambda *a, **k: [])
    monkeypatch.setattr("arka.agent.chat.duckduckgo_search", lambda *a, **k: [DDGS_HIT])
    answer = _search_extract("who is the current finance minister")
    assert answer is not None
    assert "Nirmala Sitharaman" in answer


def test_encyclopedia_all_search_exhausted(isolated_search_keys, monkeypatch):
    monkeypatch.setattr("arka.integrations.web_search.configured_api_search", lambda *a, **k: [])
    monkeypatch.setattr("arka.agent.chat.duckduckgo_search", lambda *a, **k: [])
    assert fast_encyclopedic_answer("who is the current finance minister") is None


def test_encyclopedia_office_query_appends_country(isolated_search_keys, monkeypatch):
    queries: list[str] = []

    def api(query, max_results=5):
        queries.append(query)
        return [HIT]

    monkeypatch.setattr("arka.integrations.web_search.configured_api_search", api)
    monkeypatch.setattr(
        "arka.agent.chat.load_context",
        lambda: {"location_string": "Bengaluru, Karnataka, India (home)"},
    )
    topic = _office_search_topic("who is the current finance minister", "current finance minister")
    assert topic.endswith("India")
    extract = _search_extract("who is the current finance minister")
    assert extract is not None
    assert any("India" in q for q in queries)
    assert fast_encyclopedic_answer("who is the current finance minister") is None


def test_encyclopedia_ddgs_exception_returns_none(isolated_search_keys, monkeypatch):
    monkeypatch.setattr("arka.integrations.web_search.configured_api_search", lambda *a, **k: [])
    monkeypatch.setattr(
        "arka.agent.chat.duckduckgo_search",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert _search_extract("who is the current finance minister") is None


def test_list_page_hits_are_penalized() -> None:
    assert chat._is_list_page_hit(
        "List of current finance ministers",
        "https://en.wikipedia.org/wiki/List_of_current_finance_ministers",
        "This is a list of current finance ministers of the 193 United Nations member states.",
    )
    list_score = chat._score_search_result("who is current finance minister", STUB)
    person_score = chat._score_search_result("who is current finance minister", HIT)
    assert person_score > list_score


def test_us_finance_minister_rewrites_to_treasury_secretary() -> None:
    q = "who is current finance minister of usa"
    rewritten = rewrite_office_search_query(q, "current finance minister of usa")
    assert rewritten == "current United States Secretary of the Treasury"
    assert "India" not in rewritten
    with patch("arka.agent.chat.load_context", return_value={"location_string": "Bengaluru, India"}):
        assert "India" not in _office_search_topic(q, "current finance minister of usa")


def test_office_holder_answer_requires_a_person() -> None:
    assert chat.looks_like_office_holder_answer(
        "[FROM SEARCH]\nNirmala Sitharaman is the Finance Minister of India."
    )
    assert not chat.looks_like_office_holder_answer(
        "[FROM SEARCH]\nThis is a list of current finance ministers of the 193 United Nations member states."
    )
    assert not chat.looks_like_office_holder_answer(
        "[FROM SEARCH]\nThe State of Palestine mentioned in the list refers to a UN entity."
    )
    assert not chat.looks_like_office_holder_answer(
        "[FROM SEARCH] The Minister of Finance of India is the head of the Ministry of Finance."
    )
    assert chat.looks_like_knowledge_hedge(
        "As of my last update, the current Secretary of the Treasury is Janet Yellen."
    )
    assert not chat.looks_like_knowledge_hedge(
        "The current United States Secretary of the Treasury is Scott Bessent."
    )
    ctx = "Scott K. H. Bessent is the 79th Secretary of the Treasury of the United States."
    assert chat.office_answer_matches_sources(
        "The current United States Secretary of the Treasury is Scott Bessent.",
        ctx,
    )
    assert not chat.office_answer_matches_sources(
        "The current United States Secretary of the Treasury is Janet Yellen.",
        ctx,
    )
