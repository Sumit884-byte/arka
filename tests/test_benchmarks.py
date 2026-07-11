"""Tests for benchmark-based orchestration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def benchmark_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ARKA_CONFIG_DIR", str(cfg))
    from arka.llm import benchmarks as bm

    bm.ensure_default_suite()
    yield cfg


def test_evaluate_response_rules():
    from arka.llm.benchmarks import evaluate_response

    assert evaluate_response("The answer is 42", {"contains": "42"})
    assert not evaluate_response("forty-two", {"contains": "42"})
    assert evaluate_response("def add(a,b): pass", {"contains_any": ["def add", "return"]})
    assert evaluate_response("hello", {"min_length": 3})


def test_run_suite_dry_run_builds_rankings(benchmark_env: Path):
    from arka.llm.benchmarks import load_suite, run_suite, store_suite_run

    suite = load_suite("default")
    payload = run_suite(suite, dry_run=True)
    assert payload["dry_run"] is True
    assert payload["rankings"]
    for profile, rows in payload["rankings"].items():
        assert rows
        assert rows[0]["score"] > 0
    path = store_suite_run("default", payload)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "default" in data["suites"]


def test_benchmark_chain_entries(benchmark_env: Path):
    from arka.llm.benchmarks import (
        benchmark_chain_entries,
        load_suite,
        run_suite,
        store_suite_run,
    )

    suite = load_suite("default")
    store_suite_run("default", run_suite(suite, dry_run=True))
    chain = benchmark_chain_entries("chat")
    assert chain
    assert chain[0][0]
    assert chain[0][1]


def test_apply_rankings_writes_skill_models(benchmark_env: Path, monkeypatch: pytest.MonkeyPatch):
    from arka.llm.benchmarks import apply_rankings, load_suite, run_suite, store_suite_run
    from arka.llm.skill_models import load_skill_models_file, skill_models_path

    monkeypatch.setenv("LLM_SKILL_MODELS", str(benchmark_env / "llm-skill-models.json"))
    suite = load_suite("default")
    store_suite_run("default", run_suite(suite, dry_run=True))
    applied = apply_rankings(profiles=["chat"])
    assert applied
    data = load_skill_models_file()
    profiles = data.get("_profiles") or {}
    assert profiles.get("chat")


def test_build_default_chain_uses_benchmark_flag(benchmark_env: Path, monkeypatch: pytest.MonkeyPatch):
    from importlib import reload

    from arka.llm.benchmarks import load_suite, run_suite, store_suite_run
    import arka.llm.fallback as fb

    suite = load_suite("default")
    store_suite_run("default", run_suite(suite, dry_run=True))
    monkeypatch.setenv("ARKA_BENCHMARK_ORCHESTRATE", "1")
    for key in list(os.environ):
        if key.startswith(("LLM_FALLBACK", "SKILL_MODEL", "LLM_SKILL_MODELS")):
            monkeypatch.delenv(key, raising=False)
    reload(fb)
    chain = fb.build_default_chain(task="chat")
    winners = fb._benchmark_chain_entries("chat")
    assert winners
    assert chain[: len(winners)] == winners


def test_benchmark_cli_run_dry_run(benchmark_env: Path, capsys):
    from arka.integrations.benchmark_cli import main

    code = main(["run", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Benchmark complete" in out


def test_benchmark_cli_apply_dry_run(benchmark_env: Path, capsys):
    from arka.integrations.benchmark_cli import main

    main(["run", "--dry-run"])
    code = main(["apply", "--dry-run", "--profile", "chat"])
    assert code == 1 or code == 0
    out = capsys.readouterr().out
    assert "Would apply" in out or "chat" in out
