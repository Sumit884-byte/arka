"""Tests for select_model / model_advisor skill."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.llm.model_advisor import (
    AdvisorReport,
    HardwareSnapshot,
    ProfileRecommendation,
    apply_recommendations,
    build_report,
    classify_tier,
    is_model_select_query,
    nl_to_argv,
    _tier_profile_models,
)
from arka.routing.symbolic import route_model_select, route_offline_extras


def _hw(**kwargs) -> HardwareSnapshot:
    base = dict(
        platform="macos",
        cpu_cores=8,
        cpu_model="Apple M2",
        ram_total_gb=16.0,
        ram_available_gb=8.0,
        gpu_kind="mps",
        gpu_name="Apple M2 GPU",
        gpu_vram_gb=None,
        disk_free_gb=120.0,
        disk_total_gb=512.0,
        on_battery=False,
        ollama_models=[],
    )
    base.update(kwargs)
    return HardwareSnapshot(**base)


class ModelAdvisorTierTests(unittest.TestCase):
    def test_classify_minimal_ram(self) -> None:
        self.assertEqual(classify_tier(_hw(ram_total_gb=6.0, gpu_kind="none")), "minimal")

    def test_classify_cloud_light(self) -> None:
        self.assertEqual(
            classify_tier(_hw(ram_total_gb=12.0, gpu_kind="integrated", gpu_name="Intel UHD")),
            "cloud_light",
        )

    def test_classify_balanced(self) -> None:
        self.assertEqual(classify_tier(_hw(ram_total_gb=16.0, gpu_kind="integrated")), "balanced")

    def test_classify_local_capable_cuda(self) -> None:
        self.assertEqual(
            classify_tier(_hw(ram_total_gb=32.0, gpu_kind="cuda", gpu_vram_gb=10.0, gpu_name="RTX 3080")),
            "local_capable",
        )

    def test_classify_local_heavy(self) -> None:
        self.assertEqual(
            classify_tier(_hw(ram_total_gb=64.0, gpu_kind="cuda", gpu_vram_gb=24.0)),
            "local_heavy",
        )

    def test_battery_downgrades_tier(self) -> None:
        self.assertEqual(
            classify_tier(_hw(ram_total_gb=64.0, gpu_kind="cuda", gpu_vram_gb=24.0, on_battery=True)),
            "balanced",
        )


class ModelAdvisorMappingTests(unittest.TestCase):
    @mock.patch("arka.llm.model_advisor._provider_available", return_value=True)
    def test_minimal_uses_cloud_models(self, _avail: mock.MagicMock) -> None:
        mapping = _tier_profile_models("minimal", _hw(ram_total_gb=6.0))
        self.assertTrue(all("/" in model for model, _ in mapping.values()))
        self.assertIn("groq/", mapping["route"][0])

    @mock.patch("arka.llm.model_advisor._provider_available", return_value=True)
    def test_local_heavy_prefers_ollama_when_installed(self, _avail: mock.MagicMock) -> None:
        hw = _hw(
            ram_total_gb=64.0,
            gpu_kind="cuda",
            gpu_vram_gb=24.0,
            ollama_models=["qwen3:8b", "llama3.2:1b"],
        )
        mapping = _tier_profile_models("local_heavy", hw)
        self.assertTrue(mapping["chat"][0].startswith("ollama/"))


class ModelAdvisorRoutingTests(unittest.TestCase):
    def test_is_model_select_query(self) -> None:
        self.assertTrue(is_model_select_query("select best model for my pc"))
        self.assertTrue(is_model_select_query("what model should I use"))
        self.assertTrue(is_model_select_query("optimize models for my hardware"))
        self.assertFalse(is_model_select_query("what is a language model"))

    def test_nl_to_argv_apply_and_json(self) -> None:
        self.assertEqual(nl_to_argv("apply best model for my laptop"), ["--apply"])
        self.assertEqual(nl_to_argv("select best model for my pc as json"), ["--json"])

    def test_route_model_select(self) -> None:
        hit = route_model_select("select best model for my mac")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "select_model")

    def test_route_offline_extras(self) -> None:

        hit = route_offline_extras("optimize models for my hardware")
        self.assertEqual(hit, "select_model")


class ModelAdvisorApplyTests(unittest.TestCase):
    @mock.patch("arka.llm.model_advisor._provider_available", return_value=True)
    def test_apply_writes_profiles(self, _avail: mock.MagicMock) -> None:
        report = AdvisorReport(
            tier="cloud_light",
            tier_label="Cloud-light",
            hardware=_hw(ram_total_gb=12.0, gpu_kind="integrated"),
            recommendations=[
                ProfileRecommendation("route", "groq/llama-3.1-8b-instant", "fast"),
                ProfileRecommendation("chat", "gemini/gemini-2.5-flash", "balanced"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm-skill-models.json"
            with mock.patch.dict(os.environ, {"LLM_SKILL_MODELS": str(path)}, clear=False):
                saved = apply_recommendations(report)
            self.assertEqual(saved, path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("groq/llama-3.1-8b-instant", text)
            self.assertIn("gemini/gemini-2.5-flash", text)


class ModelAdvisorReportTests(unittest.TestCase):
    @mock.patch("arka.llm.model_advisor.probe_hardware")
    @mock.patch("arka.llm.model_advisor._provider_available", return_value=False)
    def test_build_report_notes_missing_providers(self, _avail: mock.MagicMock, probe: mock.MagicMock) -> None:
        probe.return_value = _hw(ram_total_gb=12.0, gpu_kind="integrated")
        report = build_report()
        self.assertEqual(report.tier, "cloud_light")
        self.assertTrue(any("GEMINI" in n or "Groq" in n for n in report.notes))


if __name__ == "__main__":
    unittest.main()
