"""Tests for memory → web search fallback in arka.agent.chat."""

from __future__ import annotations

import os
import unittest
from unittest import mock


class MemorySearchFallbackTests(unittest.TestCase):
    def test_memory_search_fallback_enabled_default(self) -> None:
        from arka.agent.chat import memory_search_fallback_enabled

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMORY_SEARCH_FALLBACK", None)
            self.assertTrue(memory_search_fallback_enabled())

    def test_memory_search_fallback_disabled(self) -> None:
        from arka.agent.chat import memory_search_fallback_enabled

        with mock.patch.dict(os.environ, {"MEMORY_SEARCH_FALLBACK": "0"}):
            self.assertFalse(memory_search_fallback_enabled())

    def test_looks_like_unknown_answer(self) -> None:
        from arka.agent.chat import looks_like_unknown_answer

        self.assertTrue(looks_like_unknown_answer("[FROM MEMORY] I don't know who won that match."))
        self.assertTrue(looks_like_unknown_answer("I'm not sure about the release date."))
        self.assertTrue(looks_like_unknown_answer("Could not generate an answer."))
        self.assertFalse(
            looks_like_unknown_answer("[FROM MEMORY] Paris is the capital of France.")
        )

    def test_fallback_triggers_search_on_unknown_memory_answer(self) -> None:
        from arka.agent.chat import answer_question

        with (
            mock.patch.dict(os.environ, {"MEMORY_SEARCH_FALLBACK": "1"}),
            mock.patch("arka.agent.chat.get_intent", return_value=("ANSWER", "who won IPL 2026")),
            mock.patch("arka.agent.chat.snippet_lookup", return_value=""),
            mock.patch("arka.agent.chat.build_session_context", return_value="User location: Test"),
            mock.patch("arka.agent.chat.gather_web_context", return_value="IPL 2026 winner: Team X"),
            mock.patch("arka.agent.chat.llm_complete") as llm,
        ):
            llm.side_effect = [
                "[FROM MEMORY] I don't have enough information about IPL 2026.",
                "[FROM SEARCH] Team X won IPL 2026.",
            ]
            prov, answer = answer_question("who won IPL 2026", use_session=False)
        self.assertEqual(prov, "search")
        self.assertIn("Team X", answer)
        self.assertEqual(llm.call_count, 2)

    def test_fallback_skipped_when_disabled(self) -> None:
        from arka.agent.chat import answer_question

        with (
            mock.patch.dict(os.environ, {"MEMORY_SEARCH_FALLBACK": "0"}),
            mock.patch("arka.agent.chat.get_intent", return_value=("ANSWER", "obscure fact")),
            mock.patch("arka.agent.chat.snippet_lookup", return_value=""),
            mock.patch("arka.agent.chat.build_session_context", return_value=""),
            mock.patch("arka.agent.chat.gather_web_context") as gather,
            mock.patch(
                "arka.agent.chat.llm_complete",
                return_value="[FROM MEMORY] I don't know.",
            ),
        ):
            prov, answer = answer_question("obscure fact", use_session=False)
        gather.assert_not_called()
        self.assertEqual(prov, "memory")
        self.assertIn("don't know", answer.lower())


if __name__ == "__main__":
    unittest.main()
