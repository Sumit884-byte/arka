"""Tests for person-focused vision prompts and fallback behavior."""

from __future__ import annotations

import unittest
from unittest import mock

from arka.vision.describe import (
    DEFAULT_PROMPT,
    PERSON_PROMPT,
    SCREEN_PROMPT,
    _backend_candidates,
    _is_weak_person_response,
    _resolve_vision_prompt,
    _wants_person_identification,
)
from arka.vision.screen import DEFAULT_PROMPT as SCREEN_DEFAULT_PROMPT


class PersonPromptTests(unittest.TestCase):
    def test_screen_default_prompt_is_person_aware(self) -> None:
        self.assertEqual(SCREEN_DEFAULT_PROMPT, SCREEN_PROMPT)
        self.assertIn("identify who they are", SCREEN_DEFAULT_PROMPT.lower())

    def test_wants_person_identification_for_screen_queries(self) -> None:
        for query in (
            "what is on my screen",
            "what's on the screen",
            "who is this",
            "who is shown in the photo",
            "identify the person",
        ):
            with self.subTest(query=query):
                self.assertTrue(_wants_person_identification(query))

    def test_default_prompts_are_person_focused(self) -> None:
        self.assertTrue(_wants_person_identification(DEFAULT_PROMPT))
        self.assertTrue(_wants_person_identification(SCREEN_PROMPT))

    def test_chart_prompt_not_person_focused(self) -> None:
        self.assertFalse(_wants_person_identification("Summarize this chart."))

    def test_resolve_screen_capture_prompt(self) -> None:
        resolved = _resolve_vision_prompt(
            SCREEN_PROMPT,
            source="/tmp/screen_capture_20250712_120000.png",
        )
        self.assertEqual(resolved, SCREEN_PROMPT)

    def test_resolve_person_question_wraps_prompt(self) -> None:
        resolved = _resolve_vision_prompt("who is in this Instagram post?")
        self.assertIn(PERSON_PROMPT, resolved)
        self.assertIn("who is in this Instagram post?", resolved)


class WeakResponseTests(unittest.TestCase):
    def test_detects_generic_person_description(self) -> None:
        self.assertTrue(_is_weak_person_response("The screen shows a woman in a social media post."))

    def test_accepts_named_person(self) -> None:
        text = "The post shows Taylor Swift at a concert, likely from her Eras tour."
        self.assertFalse(_is_weak_person_response(text))

    def test_accepts_likely_identification(self) -> None:
        self.assertFalse(
            _is_weak_person_response("Likely Elon Musk based on the profile photo and @elonmusk handle.")
        )

    def test_no_people_not_weak(self) -> None:
        self.assertFalse(_is_weak_person_response("A Safari window showing a GitHub repository."))

    def test_no_people_visible_not_weak(self) -> None:
        self.assertFalse(_is_weak_person_response("No people visible — only a spreadsheet."))


class PersonBackendOrderTests(unittest.TestCase):
    def test_person_focused_prefers_gemini_on_linux(self) -> None:
        with (
            mock.patch("arka.vision.describe._api_key", return_value="test-key"),
            mock.patch("arka.llm.servers.host_os", return_value="linux"),
            mock.patch("arka.vision.describe.shutil.which", return_value="/usr/bin/vllm"),
            mock.patch("arka.vision.describe._env", side_effect=lambda name, default="": default),
        ):
            default_order = _backend_candidates()
            person_order = _backend_candidates(person_focused=True)
        self.assertEqual(default_order[0], "vllm")
        self.assertEqual(person_order[0], "gemini")

    def test_person_focused_noop_when_gemini_already_first(self) -> None:
        with (
            mock.patch("arka.vision.describe._api_key", return_value="test-key"),
            mock.patch("arka.llm.servers.host_os", return_value="macos"),
        ):
            order = _backend_candidates(person_focused=True)
        self.assertEqual(order[0], "gemini")


if __name__ == "__main__":
    unittest.main()
