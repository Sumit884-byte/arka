"""Tests for daily reading (generalized) and health alias."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def reading_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "arka"
    cfg.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ARKA_CONFIG_DIR", str(cfg))

    def _cfg() -> Path:
        return cfg

    monkeypatch.setattr("arka.agent.daily_reading._config_dir", _cfg)
    return cfg


def test_health_builtin_track(reading_config: Path) -> None:
    from arka.agent.daily_reading import all_concepts, load_curriculum, list_tracks

    assert "health" in list_tracks()
    curriculum = load_curriculum("health")
    assert curriculum is not None
    assert len(all_concepts(curriculum)) >= 40


def test_select_next_concepts_no_overlap(reading_config: Path) -> None:
    from arka.agent.daily_reading import load_curriculum, select_next_concepts

    curriculum = load_curriculum("health")
    assert curriculum is not None
    first = select_next_concepts(curriculum, set(), minutes=40)
    assert len(first) == 4
    ids = {row["id"] for row in first}
    assert len(ids) == 4

    second = select_next_concepts(curriculum, ids, minutes=40)
    assert all(row["id"] not in ids for row in second)


def test_select_balances_pillars(reading_config: Path) -> None:
    from arka.agent.daily_reading import load_curriculum, select_next_concepts

    curriculum = load_curriculum("health")
    assert curriculum is not None
    batch = select_next_concepts(curriculum, set(), minutes=60)
    pillars = {row["pillar"] for row in batch}
    assert pillars == {"nutrition", "exercise", "health"}


def test_nl_to_argv_minutes_and_today() -> None:
    from arka.agent.daily_reading import nl_to_argv

    assert nl_to_argv("daily reading today") == ["today"]
    assert nl_to_argv("40 minute reading on machine learning") == [
        "init",
        "machine learning",
    ]
    assert nl_to_argv("1 hour wellness reading") == [
        "--track",
        "health",
        "today",
        "--minutes",
        "60",
    ]
    assert nl_to_argv("health reading status") == ["--track", "health", "status"]


def test_nl_to_argv_init_unknown_topic() -> None:
    from arka.agent.daily_reading import nl_to_argv

    argv = nl_to_argv("daily reading on quantum computing basics")
    assert argv == ["init", "quantum computing basics"]


def test_today_records_concepts(reading_config: Path) -> None:
    from arka.agent.daily_reading import cmd_today, load_state

    fake_reading = (
        "# Sample\n\n## Protein\n\nContent here.\n\n"
        "CONCEPTS: nutrition.protein.basics, exercise.aerobic.zones\n"
    )

    with patch("arka.agent.daily_reading.generate_reading", return_value=fake_reading):
        rc = cmd_today(
            argparse.Namespace(track="health", minutes=40, force=False, json=False)
        )

    assert rc == 0
    state = load_state("health")
    assert "nutrition.protein.basics" in state["covered"]
    assert state["sessions"][-1]["minutes"] == 40


def test_main_default_is_today(reading_config: Path) -> None:
    from arka.agent import daily_reading as dr

    with patch.object(dr, "cmd_today", return_value=0) as mocked:
        assert dr.main([]) == 0
        mocked.assert_called_once()


def test_health_alias_injects_track(reading_config: Path) -> None:
    from arka.agent import health_reading as hr

    with patch("arka.agent.health_reading._daily_main", return_value=0) as mocked:
        assert hr.main(["status"]) == 0
        mocked.assert_called_once_with(["--track", "health", "status"])


def test_status_shows_progress(reading_config: Path, capsys) -> None:
    from arka.agent.daily_reading import main, save_state

    save_state("health", {"covered": ["nutrition.protein.basics"], "sessions": []})
    assert main(["--track", "health", "status"]) == 0
    out = capsys.readouterr().out
    assert "Concepts covered: 1 /" in out
    assert "40 minutes" in out


def test_init_saves_curriculum(reading_config: Path) -> None:
    from arka.agent.daily_reading import curriculum_path, load_curriculum, main

    sample = {
        "title": "Rust programming",
        "topic": "Rust programming",
        "audience": "developers",
        "disclaimer": "",
        "pillars": ["basics", "ownership", "async"],
        "concepts": {
            "basics": [{"id": "basics.hello", "title": "Hello world"}],
            "ownership": [{"id": "own.borrow", "title": "Borrow checker"}],
            "async": [{"id": "async.futures", "title": "Futures"}],
        },
    }

    with patch("arka.agent.daily_reading.generate_curriculum", return_value=sample):
        assert main(["init", "rust programming", "--track", "rust"]) == 0

    assert curriculum_path("rust").is_file()
    loaded = load_curriculum("rust")
    assert loaded is not None
    assert loaded["title"] == "Rust programming"
