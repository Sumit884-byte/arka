"""Tests for symbolic word-limit detection and post-answer enforcement."""

from __future__ import annotations

import unittest
from unittest import mock


class WordLimitHelpersTests(unittest.TestCase):
    def test_detect_word_limit_phrases(self) -> None:
        from arka.agent.chat import detect_word_limit

        self.assertEqual(detect_word_limit("tell me about marigold in 50 words"), 50)
        self.assertEqual(detect_word_limit("summarize in under 100 words"), 100)
        self.assertEqual(detect_word_limit("explain within 25 words"), 25)
        self.assertEqual(detect_word_limit("give a 40-word overview of tea"), 40)
        self.assertEqual(detect_word_limit("max 30 words please"), 30)
        self.assertEqual(detect_word_limit("for 80 words describe Paris"), 80)
        self.assertIsNone(detect_word_limit("tell me about marigold"))
        self.assertIsNone(detect_word_limit("top 10 beaches"))

    def test_count_and_truncate_preserve_prefix(self) -> None:
        from arka.agent.chat import count_answer_words, truncate_answer_words

        text = (
            "[FROM MEMORY] Marigolds are vibrant annuals featuring yellow orange and red "
            "blooms that gardeners love worldwide for color and pest control."
        )
        self.assertGreater(count_answer_words(text), 10)
        clipped = truncate_answer_words(text, 8)
        self.assertTrue(clipped.startswith("[FROM MEMORY]"))
        self.assertEqual(count_answer_words(clipped), 8)
        self.assertLessEqual(count_answer_words(clipped), 8)

    def test_enforce_noop_when_within_limit(self) -> None:
        from arka.agent.chat import enforce_word_limit

        short = "[FROM MEMORY] Marigolds are bright garden flowers."
        with mock.patch("arka.agent.chat.llm_complete") as llm:
            out = enforce_word_limit(short, 50, "marigold in 50 words")
        llm.assert_not_called()
        self.assertEqual(out, short)

    def test_enforce_rewrites_then_hard_caps(self) -> None:
        from arka.agent.chat import count_answer_words, enforce_word_limit

        long = (
            "[FROM MEMORY] "
            + " ".join(f"word{i}" for i in range(60))
        )
        still_long = (
            "[FROM MEMORY] "
            + " ".join(f"keep{i}" for i in range(40))
        )
        with mock.patch("arka.agent.chat.llm_complete", return_value=still_long):
            out = enforce_word_limit(long, 10, "in 10 words")
        self.assertLessEqual(count_answer_words(out), 10)
        self.assertTrue(out.startswith("[FROM MEMORY]"))


class WordLimitAnswerIntegrationTests(unittest.TestCase):
    def test_answer_question_enforces_word_limit(self) -> None:
        from arka.agent.chat import answer_question, count_answer_words

        # Deliberately over the requested 20-word cap.
        long = (
            "[FROM MEMORY] Marigolds are vibrant annuals featuring yellow, orange, and red "
            "blooms. Easy to cultivate, they are prized in gardens for their cheerful "
            "appearance and natural pest-deterrent properties. These flowers hold deep "
            "cultural significance, especially in India, where they are essential for "
            "religious ceremonies, festive garlands, and traditional decorations."
        )
        short = (
            "[FROM MEMORY] Marigolds are bright yellow-orange annuals used in gardens "
            "and Indian ceremonies."
        )
        self.assertGreater(count_answer_words(long), 20)
        self.assertLessEqual(count_answer_words(short), 20)
        with (
            mock.patch("arka.agent.chat.get_intent", return_value=("ANSWER", "marigold")),
            mock.patch("arka.agent.chat.snippet_lookup", return_value=""),
            mock.patch("arka.agent.chat.build_session_context", return_value=""),
            mock.patch("arka.agent.chat.gather_web_context", return_value=""),
            mock.patch("arka.agent.chat.llm_complete") as llm,
        ):
            llm.side_effect = [long, short]
            prov, answer = answer_question(
                "tell me about marigold in 20 words",
                use_session=False,
                cleanup=False,
            )
        self.assertEqual(prov, "memory")
        self.assertLessEqual(count_answer_words(answer), 20)
        self.assertEqual(llm.call_count, 2)
        first_user = llm.call_args_list[0].args[1]
        self.assertIn("at most 20 words", first_user)


if __name__ == "__main__":
    unittest.main()
