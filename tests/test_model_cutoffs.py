"""Tests for model-aware web search triggering."""

from __future__ import annotations

import os
import unittest
from datetime import date
from unittest import mock

from arka.llm import model_cutoffs as mc


class ModelCutoffRegistryTests(unittest.TestCase):
    def test_resolve_gemini_25_cutoff(self) -> None:
        cutoff = mc.resolve_knowledge_cutoff("gemini", "gemini-2.5-flash")
        self.assertEqual(cutoff, date(2025, 1, 1))

    def test_resolve_llama_31_cutoff(self) -> None:
        cutoff = mc.resolve_knowledge_cutoff("groq", "llama-3.1-8b-instant")
        self.assertEqual(cutoff, date(2023, 12, 1))

    def test_cutoff_override_env(self) -> None:
        mc._load_cutoff_overrides.cache_clear()
        with mock.patch.dict(
            os.environ,
            {"MODEL_CUTOFF_OVERRIDES": '{"groq/llama-3.1-8b-instant":"2022-06-01"}'},
        ):
            mc._load_cutoff_overrides.cache_clear()
            cutoff = mc.resolve_knowledge_cutoff("groq", "llama-3.1-8b-instant")
        self.assertEqual(cutoff, date(2022, 6, 1))
        mc._load_cutoff_overrides.cache_clear()

    def test_query_postdates_cutoff_future_year(self) -> None:
        cutoff = date(2024, 8, 1)
        self.assertTrue(mc.query_postdates_cutoff("who won IPL 2025", cutoff))
        self.assertFalse(mc.query_postdates_cutoff("who won IPL 2023", cutoff))

    def test_query_postdates_cutoff_same_year_event(self) -> None:
        cutoff = date(2024, 8, 1)
        self.assertTrue(mc.query_postdates_cutoff("IPL 2024 winner", cutoff))
        self.assertFalse(mc.query_postdates_cutoff("history of IPL before 2020", cutoff))

    def test_cutoff_search_keywords(self) -> None:
        with mock.patch("arka.llm.model_cutoffs.datetime") as dt:
            dt.now.return_value = mock.Mock(year=2026)
            kws = mc.cutoff_search_keywords(date(2024, 8, 1))
        self.assertIn("2025", kws)
        self.assertIn("2026", kws)
        self.assertIn("2027", kws)
        self.assertNotIn("2024", kws)


class ModelAwareSearchTests(unittest.TestCase):
    def test_should_search_for_model_future_year(self) -> None:
        info = mc.ModelCutoff("groq", "llama-3.1-8b-instant", date(2023, 12, 1))
        self.assertTrue(mc.should_search_for_model("events in 2025", cutoff=info))

    def test_should_not_search_for_model_past_year(self) -> None:
        info = mc.ModelCutoff("gemini", "gemini-2.5-flash", date(2025, 1, 1))
        self.assertFalse(mc.should_search_for_model("world war 2 ended in 1945", cutoff=info))

    def test_should_auto_search_live_keywords_still_trigger(self) -> None:
        from arka.agent.chat import should_auto_search

        mc.ModelCutoff("gemini", "gemini-2.5-flash", date(2025, 1, 1))
        with mock.patch("arka.agent.chat.should_search_for_model", return_value=False):
            self.assertTrue(should_auto_search("latest Rust release notes"))

    def test_should_auto_search_model_cutoff_year(self) -> None:
        from arka.agent.chat import should_auto_search

        mc.ModelCutoff("groq", "llama-3.1-8b-instant", date(2023, 12, 1))
        with mock.patch("arka.agent.chat.should_search_for_model", return_value=True):
            self.assertTrue(should_auto_search("who won IPL 2026"))

    def test_get_intent_searches_post_cutoff_query(self) -> None:
        from arka.agent.chat import get_intent

        with (
            mock.patch("arka.agent.chat.should_search_for_model", return_value=True),
            mock.patch("arka.agent.chat.llm_complete") as llm,
        ):
            action, _ = get_intent("summarize the 2026 budget")
        llm.assert_not_called()
        self.assertEqual(action, "SEARCH")

    def test_get_intent_answers_pre_cutoff_without_live_keywords(self) -> None:
        from arka.agent.chat import get_intent

        with (
            mock.patch("arka.agent.chat.should_auto_search", return_value=False),
            mock.patch(
                "arka.integrations.supermemory.is_definitional_query",
                return_value=False,
            ),
            mock.patch("arka.agent.chat.llm_complete") as llm,
        ):
            action, _ = get_intent("what happened in 1999")
        llm.assert_not_called()
        self.assertEqual(action, "ANSWER")

    def test_model_aware_search_disabled(self) -> None:
        with mock.patch.dict(os.environ, {"MODEL_AWARE_SEARCH": "0"}):
            info = mc.ModelCutoff("groq", "llama-3.1-8b-instant", date(2023, 12, 1))
            self.assertFalse(mc.should_search_for_model("IPL 2026 winner", cutoff=info))


if __name__ == "__main__":
    unittest.main()
