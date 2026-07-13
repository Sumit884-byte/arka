"""Tests for debug-mode gating of verbose traces."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

from arka.core.mode import DEFAULT_MODE, get_mode, is_debug_mode, set_mode
from arka.llm import fallback as fb
from arka.llm import servers


class DebugModeDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "arka")
        os.makedirs(self.config, exist_ok=True)
        self.mode_patch = mock.patch("arka.core.mode.config_dir")
        self.mock_config_dir = self.mode_patch.start()
        self.addCleanup(self.mode_patch.stop)
        from pathlib import Path

        self.mock_config_dir.return_value = Path(self.config)
        os.environ.pop("ARKA_MODE", None)
        os.environ.pop("LLM_VERBOSE", None)

    def test_default_mode_is_not_debug(self) -> None:
        self.assertEqual(get_mode(), DEFAULT_MODE)
        self.assertNotEqual(get_mode(), "debug")
        self.assertFalse(is_debug_mode())

    def test_llm_trace_disabled_by_default(self) -> None:
        self.assertFalse(fb.llm_trace_enabled())

    def test_llm_verbose_env_does_not_enable_traces_without_debug_mode(self) -> None:
        os.environ["LLM_VERBOSE"] = "1"
        self.assertFalse(fb.llm_trace_enabled())


class DebugTraceOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "arka")
        os.makedirs(self.config, exist_ok=True)
        self.mode_patch = mock.patch("arka.core.mode.config_dir")
        self.mock_config_dir = self.mode_patch.start()
        self.addCleanup(self.mode_patch.stop)
        from pathlib import Path

        self.mock_config_dir.return_value = Path(self.config)
        os.environ.pop("ARKA_MODE", None)
        os.environ.pop("LLM_VERBOSE", None)
        fb.EXHAUSTION.reset()

    def _run_fallback(self) -> fb.CompletionResult:
        class FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def run(self, _user):
                return SimpleNamespace(content="ok")

        def fake_build_model(provider, model_id, temperature, *, max_tokens=None, session=None):
            return object()

        engine = fb.LlmFallbackEngine(
            chain=[("gemini", "gemini-2.0-flash")],
            store=fb.ExhaustionStore(),
        )
        with patch.object(fb, "build_model", side_effect=fake_build_model):
            with patch("agno.agent.Agent", FakeAgent):
                return engine.complete("You are helpful.", "hello")

    def test_fallback_silent_in_agent_mode(self) -> None:
        set_mode("agent")
        with patch("builtins.print") as printed:
            result = self._run_fallback()
        self.assertEqual(result.text, "ok")
        self.assertFalse(fb.llm_trace_enabled())
        for call in printed.call_args_list:
            msg = str(call.args[0]) if call.args else ""
            self.assertNotIn("arka_llm:", msg)

    def test_fallback_verbose_in_debug_mode(self) -> None:
        set_mode("debug")
        self.assertTrue(fb.llm_trace_enabled())
        with patch("builtins.print") as printed:
            result = self._run_fallback()
        self.assertEqual(result.text, "ok")
        messages = [str(call.args[0]) for call in printed.call_args_list if call.args]
        self.assertTrue(any("arka_llm:" in msg for msg in messages))

    def test_servers_trace_silent_by_default(self) -> None:
        set_mode("agent")
        with patch("builtins.print") as printed:
            servers._trace_stderr("Starting vLLM server…")
        printed.assert_not_called()

    def test_servers_trace_shown_in_debug_mode(self) -> None:
        set_mode("debug")
        with patch("builtins.print") as printed:
            servers._trace_stderr("Starting vLLM server…")
        printed.assert_called_once()


class FishRoutingTraceTests(unittest.TestCase):
    def test_fish_config_gates_interpreted_and_running_skill(self) -> None:
        from pathlib import Path

        cfg = Path(__file__).resolve().parents[1] / "src" / "arka" / "fish" / "config.fish"
        text = cfg.read_text(encoding="utf-8")
        self.assertIn("function _arka_routing_trace_enabled", text)
        self.assertIn('if _arka_routing_trace_enabled\n            echo (set_color blue)"→ Interpreted:', text)
        self.assertIn('if _arka_routing_trace_enabled\n            echo (set_color cyan)"▶ Running skill:', text)


if __name__ == "__main__":
    unittest.main()
