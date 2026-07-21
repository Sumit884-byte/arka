from __future__ import annotations

import json
from unittest import mock

from arka.agent import chat
from arka.integrations import supermemory as sm
from arka.llm import fallback as fb


def test_recall_query_terms_strips_what_is_boilerplate() -> None:
    assert sm.recall_query_terms("what is Rust?") == ["rust"]
    assert "is" not in sm.recall_query_terms("what is Rust?")


def test_ambiguous_definitional_query_detects_rust() -> None:
    from arka.core.habitat import reset_habitat, set_domain

    with mock.patch("arka.core.habitat.config_dir") as config_dir:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            reset_habitat()
            set_domain("developer")
            assert sm.is_ambiguous_definitional_query("what is Rust?")
            set_domain("general")
            assert not sm.is_ambiguous_definitional_query("what is Rust?")


def test_enhance_definitional_search_query_disambiguates_rust() -> None:
    from unittest import mock

    from arka.core.habitat import reset_habitat, set_domain

    with mock.patch("arka.core.habitat.config_dir") as config_dir:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            reset_habitat()
            set_domain("developer")
            assert "programming language" in sm.enhance_definitional_search_query("what is Rust?").lower()


def test_local_recall_ignores_unrelated_probability_memories(tmp_path, monkeypatch) -> None:
    mem_file = tmp_path / "memory.json"
    mem_file.write_text(
        json.dumps(
            [
                {
                    "id": "als",
                    "text": (
                        "Study answer Q83: A blood test indicates the presence of ALS "
                        "93% of the time when ALS is actually present."
                    ),
                    "tags": ["study"],
                    "ts": 1.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sm, "MEMORY_FILE", mem_file)
    assert sm._local_recall("what is Rust?", limit=3) == []


def test_local_recall_matches_whole_word_rust_not_corrosion_substring(tmp_path, monkeypatch) -> None:
    mem_file = tmp_path / "memory.json"
    mem_file.write_text(
        json.dumps(
            [
                {
                    "id": "corr",
                    "text": (
                        "Corrosion engineering manages rust on iron through coatings "
                        "and cathodic protection."
                    ),
                    "tags": ["engineering"],
                    "ts": 1.0,
                },
                {
                    "id": "lang",
                    "text": "Rust is a systems programming language from Mozilla.",
                    "tags": ["programming"],
                    "ts": 2.0,
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sm, "MEMORY_FILE", mem_file)
    hits = sm._local_recall("what is Rust?", limit=3)
    assert hits
    assert "systems programming language" in hits[0]


def test_get_intent_routes_what_is_rust_to_search() -> None:
    action, _ = chat.get_intent("what is Rust?")
    assert action == "SEARCH"


def test_build_default_chain_excludes_vision_ollama_for_chat() -> None:
    chain = fb.build_default_chain(task="chat", skill="web_answer")
    ollama_models = [model for provider, model in chain if provider == "ollama"]
    assert ollama_models
    assert all(not fb.OLLAMA_VISION_SKIP_RE.search(model) for model in ollama_models)


def test_unified_ask_delegates_knowledge_questions_to_chat(monkeypatch) -> None:
    from arka.agent import chat, talents

    calls: list[tuple[str, bool]] = []

    def fake_answer(question: str, *, deep: bool, use_session: bool, cleanup: bool):
        calls.append((question, use_session))
        return "search", "[FROM SEARCH]\nRust is a systems programming language."

    monkeypatch.setattr(chat, "answer_question", fake_answer)
    monkeypatch.setattr(
        "arka.output.print_block",
        lambda title, body: None,
    )

    out = talents.unified_ask("what is Rust?")
    assert "Rust" in out
    assert calls == [("what is Rust?", False)]
