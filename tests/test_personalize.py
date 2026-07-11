"""Tests for arka personalize onboarding and skill recommendations."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from arka.core.personalize import (
    SKILL_CATALOG,
    is_personalize_query,
    load_profile,
    nl_to_argv,
    profile_path,
    reset_profile,
    run_wizard,
    save_profile,
    score_skills,
)
from arka.routing.symbolic import route_offline_extras, route_personalize


class PersonalizeProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.personalize.config_dir")
    def test_save_and_load_profile(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        profile = {
            "interests": ["finance", "pdf"],
            "experience": "beginner",
            "platforms": ["mac"],
            "has_api_keys": True,
            "uses_fish": False,
            "completed_at": "2026-07-11T00:00:00Z",
            "onboarding_done": True,
        }
        save_profile(profile)
        loaded = load_profile()
        self.assertEqual(loaded["interests"], ["finance", "pdf"])
        self.assertEqual(loaded["experience"], "beginner")
        self.assertTrue(loaded["onboarding_done"])

    @mock.patch("arka.core.personalize.config_dir")
    def test_reset_clears_profile(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        save_profile({"interests": ["dev"], "experience": "intermediate", "platforms": ["linux"]})
        self.assertTrue(profile_path().is_file())
        reset_profile()
        self.assertFalse(profile_path().is_file())


class PersonalizeScoringTests(unittest.TestCase):
    def test_finance_profile_ranks_stocks(self) -> None:
        profile = {"interests": ["finance"], "experience": "beginner", "platforms": ["mac"]}
        recs = score_skills(profile, limit=5)
        names = [r.name for r in recs]
        self.assertIn("stocks", names)
        self.assertIn("currency_convert", names)

    def test_pdf_profile_ranks_pdf_tools(self) -> None:
        profile = {"interests": ["pdf"], "experience": "beginner", "platforms": ["linux"]}
        recs = score_skills(profile, limit=5)
        names = [r.name for r in recs]
        self.assertIn("pdf_tools", names[:3])

    def test_beginner_bonus_prefers_beginner_skills(self) -> None:
        profile = {"interests": ["productivity"], "experience": "beginner", "platforms": ["mac"]}
        recs = score_skills(profile, limit=10)
        beginner_hits = [r for r in recs if SKILL_CATALOG[r.name].get("beginner")]
        self.assertTrue(len(beginner_hits) >= 2)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_gated_skill_shows_env_label(self) -> None:
        profile = {"interests": ["finance"], "experience": "beginner", "platforms": ["mac"]}
        recs = score_skills(profile, limit=10)
        stocks = next(r for r in recs if r.name == "stocks")
        self.assertFalse(stocks.gate_ok)
        self.assertIn("GROQ_API_KEY", stocks.gate_label)


class PersonalizeWizardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.personalize.config_dir")
    def test_wizard_flags_non_interactive(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        profile = run_wizard(
            interests=["finance", "pdf"],
            experience="beginner",
            platforms=["mac"],
            non_interactive=True,
        )
        self.assertEqual(profile["interests"], ["finance", "pdf"])
        self.assertTrue(profile["onboarding_done"])
        data = json.loads((self.config / "personalize.json").read_text(encoding="utf-8"))
        self.assertEqual(data["interests"], ["finance", "pdf"])


class PersonalizeOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)

    @mock.patch("arka.core.personalize.config_dir")
    def test_recommend_output_format(self, config_dir: mock.MagicMock) -> None:
        config_dir.return_value = self.config
        save_profile(
            {
                "interests": ["finance", "pdf"],
                "experience": "beginner",
                "platforms": ["mac"],
                "onboarding_done": True,
            }
        )
        from arka.core.personalize import print_recommendations

        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            code = print_recommendations()
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("Your profile: finance, pdf (beginner)", out)
        self.assertIn("Recommended skills:", out)
        self.assertIn("pdf_tools", out)
        self.assertIn("Try:", out)


class PersonalizeRoutingTests(unittest.TestCase):
    def test_is_personalize_query(self) -> None:
        self.assertTrue(is_personalize_query("personalize me"))
        self.assertTrue(is_personalize_query("recommend skills for me"))
        self.assertTrue(is_personalize_query("what skills should I use"))
        self.assertTrue(is_personalize_query("get started with arka"))
        self.assertFalse(is_personalize_query("what is Python"))

    def test_nl_to_argv_recommend(self) -> None:
        self.assertEqual(nl_to_argv("recommend skills"), ["recommend"])

    def test_nl_to_argv_quickstart(self) -> None:
        self.assertEqual(nl_to_argv("get started with arka quickstart"), ["quickstart"])

    def test_route_personalize(self) -> None:
        self.assertEqual(route_personalize("personalize me"), "personalize recommend")
        self.assertEqual(route_personalize("get started with arka"), "personalize recommend")

    def test_offline_extras_routes_personalize(self) -> None:
        hit = route_offline_extras("recommend skills for finance and pdf")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "personalize")


if __name__ == "__main__":
    unittest.main()
