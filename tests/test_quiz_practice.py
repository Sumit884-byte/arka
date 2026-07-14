"""Tests for Arka quiz_practice skill — NL routing, memory, and dedup."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from arka.agent.quiz_practice import (
    _unique_question,
    is_duplicate,
    list_topics,
    load_memory,
    nl_to_argv,
    normalize_question,
    quiz_practice,
    reset_memory,
    save_memory,
    score_answer,
    topic_slug,
)
from arka.routing.symbolic import route_quiz_practice
from arka.router import route


class TestQuizNlToArgv(unittest.TestCase):
    def test_quiz_python(self) -> None:
        self.assertEqual(nl_to_argv("arka quiz python"), ["python"])

    def test_practice_quiz_rust(self) -> None:
        self.assertEqual(nl_to_argv("practice quiz rust loops"), ["rust loops"])

    def test_quiz_me_on_history(self) -> None:
        self.assertEqual(nl_to_argv("quiz me on world history"), ["world history"])

    def test_quiz_practice_biology(self) -> None:
        self.assertEqual(nl_to_argv("quiz practice biology mitosis"), ["biology mitosis"])

    def test_list_command(self) -> None:
        self.assertEqual(nl_to_argv("quiz_practice list"), ["list"])

    def test_not_generic_question(self) -> None:
        self.assertEqual(nl_to_argv("what is Python"), [])

    def test_route_symbolic(self) -> None:
        hit = route_quiz_practice("quiz me on python decorators")
        self.assertEqual(hit, "quiz_practice 'python decorators'")

    def test_route_quiz_python_beats_llm_misroute(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "ai_only"}, clear=False):
            result = route("quiz python")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill, "quiz_practice python")
        self.assertEqual(result.kind, "skill")


class TestQuizMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _patch_root(self):
        return patch("arka.agent.quiz_practice.memory_root", return_value=self.root)

    def test_topic_slug(self) -> None:
        self.assertEqual(topic_slug("Rust Loops!"), "rust-loops")

    def test_save_load_reset(self) -> None:
        with self._patch_root():
            data = {"topic": "Python", "asked": ["What is a list?"], "scores": [], "last_at": None}
            save_memory(data)
            loaded = load_memory("Python")
            self.assertEqual(loaded["asked"], ["What is a list?"])
            self.assertTrue(reset_memory("Python"))
            self.assertFalse(reset_memory("Python"))

    def test_list_topics(self) -> None:
        with self._patch_root():
            save_memory({"topic": "Rust", "asked": ["q1", "q2"], "scores": [], "last_at": None})
            save_memory({"topic": "Go", "asked": ["q1"], "scores": [], "last_at": None})
            topics = list_topics()
            self.assertEqual(len(topics), 2)
            names = {t[0] for t in topics}
            self.assertIn("Rust", names)
            self.assertIn("Go", names)


class TestQuizDedup(unittest.TestCase):
    def test_normalize_and_duplicate(self) -> None:
        a = normalize_question("What is a Python list?")
        b = normalize_question("what  is   a python list")
        self.assertEqual(a, b)
        self.assertTrue(is_duplicate("What is a Python list?", ["what is a python list"]))

    def test_generate_avoids_repeat(self) -> None:
        asked = ["What is a Python list?"]
        with patch(
            "arka.agent.quiz_practice._llm_complete",
            side_effect=[
                "QUESTION: What is a Python list?\nHINT: none",
                "QUESTION: Explain list comprehensions\nHINT: syntax",
            ],
        ):
            question, hint = _unique_question("python", asked)
        self.assertEqual(question, "Explain list comprehensions")
        self.assertEqual(hint, "syntax")


class TestQuizRun(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_one_shot_with_score(self) -> None:
        with patch("arka.agent.quiz_practice.memory_root", return_value=self.root):
            with patch(
                "arka.agent.quiz_practice._unique_question",
                return_value=("What is mitosis?", ""),
            ):
                with patch("sys.stdin.isatty", return_value=True):
                    with patch(
                        "arka.agent.quiz_practice._read_answer",
                        return_value="cell division",
                    ):
                        with patch(
                            "arka.agent.quiz_practice.score_answer",
                            return_value={
                                "score": "90",
                                "correct": "yes",
                                "feedback": "Good.",
                                "answer": "cell division",
                                "explanation": "Mitosis splits a cell.",
                            },
                        ):
                            code = quiz_practice("biology", count=1)
            self.assertEqual(code, 0)
            mem = load_memory("biology")
        self.assertEqual(len(mem["asked"]), 1)
        self.assertEqual(mem["scores"][0]["score"], "90")

    def test_score_answer_parsing(self) -> None:
        raw = (
            "SCORE: 75\nCORRECT: partial\n"
            "FEEDBACK: Close.\nANSWER: Tokyo\nEXPLANATION: Capital of Japan."
        )
        with patch("arka.agent.quiz_practice._llm_complete", return_value=raw):
            result = score_answer("geography", "Capital of Japan?", "Kyoto")
        self.assertEqual(result["score"], "75")
        self.assertEqual(result["correct"], "partial")


if __name__ == "__main__":
    unittest.main()
