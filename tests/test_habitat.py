"""Tests for arka habitat — lightweight user domain/context inference."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.core import habitat
from arka.integrations import supermemory as sm
from arka.routing.symbolic import route_habitat, route_offline_extras


class HabitatStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.habitat.config_dir")
    def test_save_and_load(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        state = habitat.HabitatState(domain="developer", confidence=0.8, signals=["test"])
        habitat.save_habitat(state)
        loaded = habitat.load_habitat()
        self.assertEqual(loaded.domain, "developer")
        self.assertAlmostEqual(loaded.confidence, 0.8)

    @mock.patch("arka.core.habitat.config_dir")
    def test_reset_clears(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        habitat.set_domain("ops")
        self.assertTrue(habitat.habitat_path().is_file())
        habitat.reset_habitat()
        self.assertFalse(habitat.habitat_path().is_file())

    @mock.patch("arka.core.habitat.config_dir")
    @mock.patch("arka.core.personalize.load_profile")
    def test_seed_from_personalize_dev(self, load_profile: mock.MagicMock, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        load_profile.return_value = {"interests": ["dev"]}
        state = habitat.load_habitat()
        self.assertEqual(state.domain, "developer")
        self.assertIn("profile:dev", state.signals)


class HabitatInferenceTests(unittest.TestCase):
    def test_score_developer_signals(self) -> None:
        scores = habitat.score_text("I'm debugging a Python API with git and unit tests")
        self.assertGreater(scores["developer"], scores.get("student", 0))
        self.assertGreater(scores["developer"], scores.get("ops", 0))

    def test_score_ops_signals(self) -> None:
        scores = habitat.score_text("kubectl incident on kubernetes cluster during on-call")
        self.assertGreater(scores["ops"], scores.get("developer", 0))

    def test_score_student_signals(self) -> None:
        scores = habitat.score_text("homework due tomorrow for my university exam")
        self.assertGreater(scores["student"], scores.get("developer", 0))

    def test_explicit_role_developer(self) -> None:
        scores = habitat.score_text("I'm a software engineer")
        self.assertGreaterEqual(scores["developer"], 4.0)

    @mock.patch("arka.core.habitat.config_dir")
    def test_update_from_message_shifts_habitat(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.reset_habitat()
            state = habitat.update_from_message("working on a Rust codebase with cargo and git")
            self.assertEqual(state.domain, "developer")
            self.assertGreater(state.confidence, 0.0)

    @mock.patch("arka.core.habitat.config_dir")
    def test_manual_domain_not_overwritten(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.set_domain("student")
            before = habitat.load_habitat()
            after = habitat.update_from_message("kubernetes terraform on-call incident")
            self.assertEqual(after.domain, before.domain)
            self.assertTrue(after.manual)


class HabitatDisambiguationTests(unittest.TestCase):
    @mock.patch("arka.core.habitat.config_dir")
    def test_developer_disambiguates_rust(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.set_domain("developer")
            q = habitat.enhance_definitional_search_query("what is Rust?")
            self.assertIn("programming language", q.lower())

    @mock.patch("arka.core.habitat.config_dir")
    def test_general_does_not_disambiguate_rust(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.set_domain("general")
            q = habitat.enhance_definitional_search_query("what is Rust?")
            self.assertEqual(q, "what is Rust?")

    @mock.patch("arka.core.habitat.config_dir")
    def test_skip_memory_recall_when_ambiguous(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.set_domain("developer")
            self.assertTrue(habitat.should_skip_memory_recall("what is Rust?"))
            habitat.set_domain("general")
            self.assertFalse(habitat.should_skip_memory_recall("what is Rust?"))

    @mock.patch("arka.core.habitat.config_dir")
    def test_supermemory_delegates_to_habitat(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.set_domain("developer")
            q = sm.enhance_definitional_search_query("what is Rust?")
            self.assertIn("programming language", q.lower())


class HabitatContextTests(unittest.TestCase):
    @mock.patch("arka.core.habitat.config_dir")
    def test_context_for_developer(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.set_domain("developer")
            ctx = habitat.context_for("what is Rust?")
            self.assertIn("developer", ctx.lower())
            self.assertIn("programming", ctx.lower())

    @mock.patch("arka.core.habitat.config_dir")
    def test_context_empty_for_low_confidence_general(self, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.reset_habitat()
            ctx = habitat.context_for("")
            self.assertEqual(ctx, "")


class HabitatRoutingTests(unittest.TestCase):
    def test_is_habitat_query(self) -> None:
        self.assertTrue(habitat.is_habitat_query("what is my habitat"))
        self.assertTrue(habitat.is_habitat_query("habitat status"))
        self.assertFalse(habitat.is_habitat_query("what is Rust"))

    def test_nl_to_argv(self) -> None:
        self.assertEqual(habitat.nl_to_argv("habitat status"), ["status"])
        self.assertEqual(habitat.nl_to_argv("set habitat to developer"), ["set", "developer"])
        self.assertEqual(habitat.nl_to_argv("my habitat is ops"), ["set", "ops"])

    def test_route_habitat(self) -> None:
        self.assertEqual(route_habitat("what is my habitat"), "habitat status")
        self.assertEqual(route_habitat("set habitat to developer"), "habitat set developer")
        self.assertIsNone(route_habitat("weather today"))

    def test_route_offline_extras_habitat(self) -> None:
        route = route_offline_extras("habitat status")
        self.assertEqual(route, "habitat status")


class HabitatSessionInferTests(unittest.TestCase):
    @mock.patch("arka.core.habitat.config_dir")
    @mock.patch("arka.agent.chat.load_session")
    def test_infer_from_session(self, load_session: mock.MagicMock, config_dir: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir.return_value = Path(tmp)
            habitat.reset_habitat()
            load_session.return_value = [
                {"role": "user", "content": "how do I fix this Python git merge conflict"},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "what is a pull request in github"},
            ]
            state = habitat.update_from_session()
            self.assertEqual(state.domain, "developer")
            self.assertGreater(state.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
