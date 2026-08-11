"""Tests for dev workflow analyzers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from arka.agent import dev_workflows as dw


def test_test_gaps_detects_missing_test_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src" / "arka").mkdir(parents=True)
        (root / "src" / "arka" / "widget.py").write_text("x = 1\n", encoding="utf-8")
        gaps = dw.test_gaps_for_files(["src/arka/widget.py"], root=root)
        assert gaps == ["src/arka/widget.py"]


def test_test_gaps_skips_when_test_exists() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src" / "arka").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "src" / "arka" / "widget.py").write_text("x = 1\n", encoding="utf-8")
        (root / "tests" / "test_widget.py").write_text("def test_widget(): pass\n", encoding="utf-8")
        gaps = dw.test_gaps_for_files(["src/arka/widget.py"], root=root)
        assert gaps == []


def test_test_gaps_uses_script_probe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "src" / "arka").mkdir(parents=True)
        (root / "src" / "arka" / "widget.py").write_text("x = 1\n", encoding="utf-8")
        (root / "scripts" / "verify_widget.py").write_text(
            '"""Verify widget module."""\nimport widget\n',
            encoding="utf-8",
        )
        gaps = dw.test_gaps_for_files(["src/arka/widget.py"], root=root)
        assert gaps == []
