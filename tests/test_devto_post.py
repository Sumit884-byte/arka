"""Tests for dev.to article writing and publishing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_parse_devto_request_publish_research() -> None:
    from arka.integrations.devto_post import build_devto_argv_from_nl, parse_devto_request

    cmd = "write a research article on smartwatches for dev.to"
    parsed = parse_devto_request(cmd)
    assert parsed is not None
    assert parsed.get("topic") == "smartwatches"
    assert build_devto_argv_from_nl(cmd) == ["write", "--topic", "smartwatches"]


def test_parse_devto_publish_session() -> None:
    from arka.integrations.devto_post import build_devto_argv_from_nl

    argv = build_devto_argv_from_nl("publish session 20260729-151700-smartwatches to dev.to")
    assert argv == ["write", "--session", "20260729-151700-smartwatches", "--post"]


def test_extract_sources_and_clean_notes() -> None:
    from arka.integrations.devto_post import clean_notes_for_prompt, extract_sources

    md = "\n".join(
        [
            "<!-- round 6 @ 2026-07-29 18:48 -->",
            "## Battery",
            "Finding text.",
            "**Links to prior research**:",
            "- earlier",
            "Sources:",
            "- https://example.com/a",
            "* https://example.com/b",
        ]
    )
    assert extract_sources(md) == ["https://example.com/a", "https://example.com/b"]
    cleaned = clean_notes_for_prompt(md)
    assert "round 6" not in cleaned
    assert "Links to prior research" not in cleaned
    assert "example.com" not in cleaned
    assert "Finding text" in cleaned


def test_suggest_title_for_smartwatches() -> None:
    from arka.integrations.devto_post import suggest_title

    state = {"thesis": "MIP displays in smartwatches beat OLED for battery life."}
    assert "MIP" in suggest_title("smartwatches", state)


def test_fallback_article_from_bundle() -> None:
    from arka.integrations.devto_post import _fallback_article

    body = _fallback_article(
        {
            "state": {
                "thesis": "MIP saves battery.",
                "confident_findings": ["MIP draws power on change only."],
                "open_questions": ["Samsung figures?"],
            }
        },
        title="Test",
        sources=["https://example.com/source"],
    )
    assert "MIP" in body
    assert "Key takeaways" in body
    assert "example.com" in body


def test_publish_article_requires_key() -> None:
    from arka.integrations.devto_post import publish_article

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="DEVTO_API_KEY"):
            publish_article(title="T", body_markdown="body", tags=["test"])


def test_publish_article_success() -> None:
    from arka.integrations.devto_post import publish_article

    payload = {"id": 1, "url": "https://dev.to/user/test-abc"}

    class FakeResp:
        def read(self) -> bytes:
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch.dict("os.environ", {"DEVTO_API_KEY": "secret"}):
        with patch("urllib.request.urlopen", return_value=FakeResp()):
            result = publish_article(
                title="Test",
                body_markdown="# Hi",
                tags=["smartwatch"],
                published=False,
            )
    assert result["url"] == "https://dev.to/user/test-abc"


def test_write_from_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.integrations.devto_post import main

    root = tmp_path / "sessions" / "test-smartwatches"
    root.mkdir(parents=True)
    (root / "session.json").write_text(
        json.dumps({"id": "test-smartwatches", "topic": "smartwatches"}),
        encoding="utf-8",
    )
    (root / "digest.md").write_text("Smartwatch battery research digest.", encoding="utf-8")
    (root / "state.json").write_text(
        json.dumps(
            {
                "thesis": "MIP displays save battery in smartwatches.",
                "confident_findings": ["MIP only draws on pixel change."],
                "open_questions": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "arka.integrations.devto_post._session_root",
        lambda sid: root if sid == "test-smartwatches" else None,
    )

    out = root / "devto-article.md"
    rc = main(["write", "--session", "test-smartwatches", "--output", str(out)])
    assert rc == 0
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "title:" in text
    assert "MIP" in text or "smartwatch" in text.lower()
