#!/usr/bin/env python3
"""Auto-start/stop local LLM servers (Ollama, vLLM) for fallback providers."""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LOCAL_PROVIDERS = frozenset({"ollama", "vllm"})


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(name: str, default: str = "1") -> bool:
    return _env(name, default).lower() in {"1", "true", "yes", "on"}


def auto_start_enabled() -> bool:
    return _truthy("LLM_AUTO_START_SERVERS", "1")


def auto_stop_enabled() -> bool:
    return _truthy("LLM_AUTO_STOP_SERVERS", "1")


def start_timeout() -> float:
    try:
        return max(3.0, float(_env("LLM_SERVER_START_TIMEOUT", "15")))
    except ValueError:
        return 15.0


def _ollama_base_url() -> str:
    host = _env("OLLAMA_HOST", "127.0.0.1:11434").replace("0.0.0.0", "127.0.0.1")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


def _vllm_health_url() -> str:
    base = _env("VLLM_API_URL")
    if not base:
        host = _env("VLLM_HOST", "127.0.0.1:8000")
        base = f"http://{host}"
    if not base.startswith("http"):
        base = f"http://{base}"
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/health"


def _http_ok(url: str, *, timeout: float = 3.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def is_reachable(provider: str) -> bool:
    provider = provider.lower()
    if provider == "ollama":
        return _http_ok(f"{_ollama_base_url()}/api/tags")
    if provider == "vllm":
        return _http_ok(_vllm_health_url())
    return False


def _display_name(provider: str) -> str:
    return {"ollama": "Ollama", "vllm": "vLLM"}.get(provider.lower(), provider.title())


def _vllm_log_path() -> Path:
    try:
        from platformdirs import user_cache_dir

        base = Path(user_cache_dir("arka", "arka"))
    except ImportError:
        base = Path.home() / ".cache" / "arka"
    base.mkdir(parents=True, exist_ok=True)
    return base / "vllm-server.log"


def _vllm_models_url() -> str:
    base = _env("VLLM_API_URL")
    if not base:
        host = _env("VLLM_HOST", "127.0.0.1:8000")
        base = f"http://{host}"
    if not base.startswith("http"):
        base = f"http://{base}"
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/models"


def _vllm_ready() -> bool:
    if not _http_ok(_vllm_health_url()):
        return False
    try:
        req = urllib.request.Request(_vllm_models_url(), method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("data") if isinstance(data, dict) else None
            return bool(models)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def _wait_until(provider: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if provider == "vllm":
            if _vllm_ready():
                return True
        elif is_reachable(provider):
            return True
        time.sleep(0.4)
    if provider == "vllm":
        return _vllm_ready()
    return is_reachable(provider)


def _stop_process(proc: subprocess.Popen[bytes], name: str) -> None:
    if proc.poll() is not None:
        return
    print(f"Stopped {name} server", file=sys.stderr)
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


@dataclass
class _ServerState:
    name: str
    process: subprocess.Popen[bytes] | None = None
    started_by_us: bool = False
    refcount: int = 0


@dataclass
class LocalServerManager:
    """Reference-counted local server lifecycle (thread-safe)."""

    _states: dict[str, _ServerState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _state(self, provider: str) -> _ServerState:
        provider = provider.lower()
        if provider not in self._states:
            self._states[provider] = _ServerState(name=_display_name(provider))
        return self._states[provider]

    def prepare(self, provider: str) -> bool:
        """Ensure provider server is up; bump refcount when successful."""
        provider = provider.lower()
        if provider not in LOCAL_PROVIDERS:
            return True

        with self._lock:
            state = self._state(provider)
            if is_reachable(provider):
                state.refcount += 1
                return True

            if not auto_start_enabled():
                return False

            if state.started_by_us and state.process and state.process.poll() is None:
                if _wait_until(provider, start_timeout()):
                    state.refcount += 1
                    return True

            proc = _start_provider(provider)
            if proc is None:
                return False

            state.process = proc
            state.started_by_us = True

        if _wait_until(provider, start_timeout()):
            with self._lock:
                state.refcount += 1
            print(f"{state.name} server ready", file=sys.stderr)
            return True

        with self._lock:
            if state.process:
                _stop_process(state.process, state.name)
            state.process = None
            state.started_by_us = False
        print(f"Failed to start {_display_name(provider)} server (timeout)", file=sys.stderr)
        return False

    def release(self, provider: str) -> None:
        provider = provider.lower()
        with self._lock:
            state = self._states.get(provider)
            if not state or state.refcount <= 0:
                return
            state.refcount -= 1
            if state.refcount > 0:
                return
            if not auto_stop_enabled() or not state.started_by_us or not state.process:
                return
            proc = state.process
            state.process = None
            state.started_by_us = False
        _stop_process(proc, state.name)

    def release_all(self, providers: set[str]) -> None:
        for provider in sorted(providers):
            self.release(provider)


MANAGER = LocalServerManager()


class LlmServerSession:
    """Track local providers touched during one LLM completion."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def prepare(self, provider: str) -> bool:
        provider = provider.lower()
        if provider not in LOCAL_PROVIDERS:
            return True
        if provider in self._used:
            return is_reachable(provider)
        if MANAGER.prepare(provider):
            self._used.add(provider)
            return True
        return False

    def close(self) -> None:
        MANAGER.release_all(self._used)
        self._used.clear()


def ensure_local_provider(provider: str) -> bool:
    return MANAGER.prepare(provider)


def release_local_provider(provider: str) -> None:
    MANAGER.release(provider)


def _start_provider(provider: str) -> subprocess.Popen[bytes] | None:
    starters: dict[str, Callable[[], subprocess.Popen[bytes] | None]] = {
        "ollama": _start_ollama,
        "vllm": _start_vllm,
    }
    starter = starters.get(provider.lower())
    if not starter:
        return None
    print(f"Starting {_display_name(provider)} server…", file=sys.stderr)
    proc = starter()
    return proc


def _start_ollama() -> subprocess.Popen[bytes] | None:
    ollama = shutil.which("ollama")
    if not ollama:
        print("Ollama binary not found — install from https://ollama.com", file=sys.stderr)
        return None
    env = os.environ.copy()
    try:
        return subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    except OSError as exc:
        print(f"Failed to start Ollama: {exc}", file=sys.stderr)
        return None


def _start_vllm() -> subprocess.Popen[bytes] | None:
    raw = _env("VLLM_START_CMD")
    if not raw:
        print(
            "vLLM not reachable — set VLLM_START_CMD (e.g. "
            "'vllm serve Qwen/Qwen2-VL-2B-Instruct --port 8000')",
            file=sys.stderr,
        )
        return None
    cmd = shlex.split(raw)
    if not cmd:
        return None
    vllm_bin = shutil.which(cmd[0])
    if not vllm_bin:
        if platform.system() == "Darwin":
            print(
                "vLLM not found on macOS — plain `pip install vllm` usually fails.\n"
                "Options:\n"
                "  • export DESCRIBE_IMAGE_BACKEND=gemini  (needs GEMINI_API_KEY)\n"
                "  • ollama pull llava && export DESCRIBE_IMAGE_BACKEND=ollama\n"
                "  • vLLM-Metal: curl -fsSL https://raw.githubusercontent.com/vllm-project/vllm-metal/main/install.sh | bash",
                file=sys.stderr,
            )
        else:
            print(
                "vLLM not found — install: pip install vllm\n"
                "Then retry describe_image (Arka auto-starts/stops the server).",
                file=sys.stderr,
            )
        return None
    cmd[0] = vllm_bin
    log_path = _vllm_log_path()
    try:
        log_fh = log_path.open("a", encoding="utf-8")
    except OSError as exc:
        print(f"Failed to open vLLM log {log_path}: {exc}", file=sys.stderr)
        return None
    print(f"Starting vLLM server… log: {log_path}", file=sys.stderr)
    print(
        "First run may download model weights (Hugging Face) — can take several minutes.",
        file=sys.stderr,
    )
    try:
        return subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
    except OSError as exc:
        print(f"Failed to start vLLM: {exc}", file=sys.stderr)
        try:
            log_fh.close()
        except OSError:
            pass
        return None


def provider_available_with_servers(provider: str) -> bool:
    """Provider check that can auto-start local servers when configured."""
    provider = provider.lower()
    if provider == "gemini":
        try:
            from arka.llm.api_keys import provider_has_keys

            return provider_has_keys("gemini") or bool(_env("GOOGLE_API_KEY"))
        except ImportError:
            return bool(_env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"))
    if provider == "groq":
        try:
            from arka.llm.api_keys import provider_has_keys

            return provider_has_keys("groq")
        except ImportError:
            return bool(_env("GROQ_API_KEY"))
    if provider == "openai":
        return bool(_env("OPENAI_API_KEY"))
    if provider == "anthropic":
        return bool(_env("ANTHROPIC_API_KEY"))
    if provider == "ollama":
        return is_reachable("ollama") or (auto_start_enabled() and bool(shutil.which("ollama")))
    if provider == "vllm":
        if is_reachable("vllm"):
            return True
        return auto_start_enabled() and bool(_env("VLLM_START_CMD"))
    return False
