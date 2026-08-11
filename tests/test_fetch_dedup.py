"""Tests for fetch deduplication helpers."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from arka.core import fetch_dedup as fd
from arka.env import load_env, reset_env_loaded


@pytest.fixture(autouse=True)
def _reset_fetch_dedup() -> None:
    fd.reset_caches()
    reset_env_loaded()
    yield
    fd.reset_caches()
    reset_env_loaded()


def test_fetch_dedup_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARKA_FETCH_DEDUP", raising=False)
    assert fd.fetch_dedup_enabled() is True


def test_fetch_dedup_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARKA_FETCH_DEDUP", "0")
    assert fd.fetch_dedup_enabled() is False


def test_get_or_fetch_caches_result() -> None:
    cache = fd.FetchDedupCache()
    calls = {"n": 0}

    def fetch() -> str:
        calls["n"] += 1
        return "ok"

    assert cache.get_or_fetch("key", fetch, ttl=60.0) == "ok"
    assert cache.get_or_fetch("key", fetch, ttl=60.0) == "ok"
    assert calls["n"] == 1


def test_singleflight_coalesces_concurrent_fetches() -> None:
    cache = fd.FetchDedupCache()
    calls = {"n": 0}
    leader_running = threading.Event()
    release = threading.Event()

    def fetch() -> str:
        calls["n"] += 1
        leader_running.set()
        release.wait(timeout=2)
        return "ok"

    results: list[str] = []

    def worker() -> None:
        results.append(cache.singleflight("live", fetch))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    assert leader_running.wait(timeout=2)
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert calls["n"] == 1
    assert results == ["ok", "ok", "ok"]


def test_load_env_runs_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("DEDUP_TEST_KEY=first\n")
    reads = {"n": 0}
    original_read_text = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == env_path.resolve():
            reads["n"] += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    monkeypatch.setattr("arka.env.checkout_root", lambda: tmp_path)
    monkeypatch.setattr("arka.env.env_file", lambda: tmp_path / "missing.env")
    monkeypatch.delenv("DEDUP_TEST_KEY", raising=False)

    load_env()
    load_env()
    assert reads["n"] == 1


def test_fetch_openrouter_balance_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.llm import credits_usage as cu

    calls = {"n": 0}

    class Resp:
        def read(self) -> bytes:
            return b'{"data":{"usage":1.0}}'

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return False

    def fake_urlopen(req, timeout=2.5):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return Resp()

    monkeypatch.setattr(cu, "iter_provider_keys", lambda _slug: ["k"])
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert cu.fetch_openrouter_balance() == {"usage": 1.0}
    assert cu.fetch_openrouter_balance() == {"usage": 1.0}
    assert calls["n"] == 1


def test_arka_api_chat_completion_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.integrations import arka_api

    calls = {"n": 0}

    def fake_impl(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return "hello", "arka", 0

    monkeypatch.setattr(arka_api, "_run_chat_completion_impl", fake_impl)
    payload = {"messages": [{"role": "user", "content": "hi"}], "model": "arka"}

    assert arka_api.run_chat_completion(payload) == ("hello", "arka", 0)
    assert arka_api.run_chat_completion(payload) == ("hello", "arka", 0)
    assert calls["n"] == 1


def test_live_fetch_singleflight(monkeypatch: pytest.MonkeyPatch) -> None:
    from arka.llm import fallback as fb

    fd.reset_caches()
    calls = {"n": 0}
    leader_running = threading.Event()
    release = threading.Event()

    def fake_urlopen(req, timeout=15):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        leader_running.set()
        release.wait(timeout=2)

        class Resp:
            def read(self):  # type: ignore[no-untyped-def]
                return b'{"models":[{"name":"models/gemini-2.0-flash","supportedGenerationMethods":["generateContent"]}]}'

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, *args):  # type: ignore[no-untyped-def]
                return False

        return Resp()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_LIST", "1")
    monkeypatch.setattr(fb, "_GEMINI_LIVE_CACHE", None)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with fb._GEMINI_LIVE_LOCK:
        fb._GEMINI_LIVE_CACHE = None

    results: list[list[str]] = []

    def worker() -> None:
        results.append(fb.fetch_gemini_models_live(force=True))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    assert leader_running.wait(timeout=2)
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert calls["n"] == 1
    assert len(results) == 3
    assert results[0] == results[1] == results[2]
