"""Tests for arka_rag / rag_skill fixes."""

from __future__ import annotations

import shlex
from unittest.mock import patch

import pytest


def test_build_skill_line_preserves_spaced_paths():
    from arka.integrations.mcp_server import _build_skill_line, _direct_mcp_from_skill

    line = _build_skill_line(
        "arka_rag",
        ["ingest", "/Users/me/dev/stats/end_term/Sem1 Statistics1.pdf"],
    )
    parts = shlex.split(line)
    assert parts[0] == "arka_rag"
    assert parts[1] == "ingest"
    assert parts[2] == "/Users/me/dev/stats/end_term/Sem1 Statistics1.pdf"

    routed = _direct_mcp_from_skill(
        "arka_rag",
        ["ingest", "/Users/me/dev/stats/end_term/Sem1 Statistics1.pdf"],
    )
    assert routed == (
        "arka_rag",
        {
            "action": "ingest",
            "path": "/Users/me/dev/stats/end_term/Sem1 Statistics1.pdf",
        },
    )


def test_privategpt_plan_skips_autostart_when_turboquant_ok():
    from arka.pdf import rag as rag_mod

    with patch.object(rag_mod, "is_up", return_value=False):
        wanted, auto = rag_mod._privategpt_ingest_plan(turboquant_ok=True)
    assert wanted is False
    assert auto is False


def test_privategpt_plan_autostarts_when_turboquant_failed():
    from arka.pdf import rag as rag_mod

    with patch.object(rag_mod, "is_up", return_value=False), patch.object(
        rag_mod, "auto_start_enabled", return_value=True
    ):
        wanted, auto = rag_mod._privategpt_ingest_plan(turboquant_ok=False)
    assert wanted is True
    assert auto is True


def test_llm_synthesize_falls_back_to_extractive(monkeypatch):
    from arka.pdf import rag as rag_mod

    monkeypatch.setattr(
        "arka.llm.cli.llm_complete",
        lambda *_a, **_k: "minimax-m2.5 was retired (status code: 410)",
    )
    monkeypatch.setattr(
        rag_mod,
        "_ollama_chat_answer",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")),
    )
    context = "WEEK 4: Association - covariance, Pearson correlation"
    answer = rag_mod._llm_synthesize("Which week covers correlation?", context)
    assert "WEEK 4" in answer
    assert "correlation" in answer.lower()


def test_ingest_payload_skips_pgpt_wait(tmp_path, monkeypatch):
    from arka.agent import rag_skill

    doc = tmp_path / "notes.txt"
    doc.write_text("hello world", encoding="utf-8")

    monkeypatch.setenv("PDF_RAG_PGPT", "auto")

    def _fake_tq(path):
        return True, "1 chunks"

    monkeypatch.setattr(
        "arka.pdf.rag._index_document_turboquant",
        _fake_tq,
    )
    monkeypatch.setattr("arka.pdf.rag.is_up", lambda: False)
    monkeypatch.setattr(
        "arka.pdf.rag.ensure_server",
        lambda **kwargs: pytest.fail("ensure_server should not run when TurboQuant ok"),
    )

    payload = rag_skill.ingest_payload(doc)
    assert payload["turboquant"]["ok"] is True
    assert payload["privategpt"]["error"]
