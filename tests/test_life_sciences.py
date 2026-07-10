"""Tests for Anthropic life-sciences marketplace integration."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LS_DIR = ROOT / "src" / "arka" / "skills" / "life_sciences"
if str(LS_DIR) not in sys.path:
    sys.path.insert(0, str(LS_DIR))

import lib  # noqa: E402


class LifeSciencesMarketplaceTests(unittest.TestCase):
    def test_load_marketplace_has_plugins(self) -> None:
        data = lib.load_marketplace()
        plugins = data.get("plugins") or []
        self.assertGreaterEqual(len(plugins), 10)
        names = {p["name"] for p in plugins}
        self.assertIn("pubmed", names)
        self.assertIn("single-cell-rna-qc", names)

    def test_get_plugin(self) -> None:
        plugin = lib.get_plugin("pubmed")
        self.assertIsNotNone(plugin)
        assert plugin is not None
        self.assertEqual(plugin["kind"], "mcp")

    def test_parse_skill_md_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(
                "---\nname: demo-skill\ndescription: Demo description\n---\n\nBody\n",
                encoding="utf-8",
            )
            meta = lib.parse_skill_md_frontmatter(path)
            self.assertEqual(meta["name"], "demo-skill")
            self.assertEqual(meta["description"], "Demo description")

    def test_build_triggers_include_pubmed(self) -> None:
        plugin = lib.get_plugin("pubmed")
        self.assertIsNotNone(plugin)
        assert plugin is not None
        triggers = lib._build_triggers(plugin, "pubmed")
        self.assertIn("pubmed", triggers)
        self.assertTrue(any("search pubmed" in t for t in triggers))

    def test_render_pubmed_run_py(self) -> None:
        plugin = lib.get_plugin("pubmed")
        self.assertIsNotNone(plugin)
        assert plugin is not None
        code = lib._render_run_py(plugin=plugin, skill_name="pubmed", kind="mcp", entry=None)
        self.assertIn("esearch.fcgi", code)
        self.assertIn("pubmed", code.lower())

    def test_install_plugin_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config"
            cache = Path(tmp) / "cache"
            repo = cache / "life-sciences" / "repo"
            pubmed_dir = repo / "pubmed"
            pubmed_dir.mkdir(parents=True)
            (pubmed_dir / "README.md").write_text("pubmed mcp", encoding="utf-8")

            with (
                mock.patch.object(lib, "_install_root", return_value=config / "skills"),
                mock.patch.object(lib, "_repo_cache_dir", return_value=cache / "life-sciences"),
                mock.patch.object(lib, "ensure_repo_clone", return_value=repo),
                mock.patch("arka.agent.skills.discover_skills", return_value=[]),
            ):
                code = lib.install_plugin("pubmed")
            self.assertEqual(code, 0)
            target = config / "skills" / "pubmed"
            manifest = json.loads((target / "skill.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], "pubmed")
            self.assertTrue((target / "run.py").is_file())


class LifeSciencesRouterTests(unittest.TestCase):
    def test_offline_router_life_sciences_list(self) -> None:
        from arka.router import _route_offline

        hit = _route_offline("life sciences list")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.skill, "life_sciences list")

    def test_offline_router_install_pubmed(self) -> None:
        from arka.router import _route_offline

        hit = _route_offline("install pubmed")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.skill, "life_sciences install pubmed")

    def test_third_party_match_life_sciences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            with mock.patch("arka.agent.skills.REGISTRY_FILE", cache / "third_party_skills.json"):
                from arka.agent.skills import discover_skills, match_command

                discover_skills(refresh=True)
                self.assertEqual(match_command("life sciences list"), "life_sciences list")


class LifeSciencesProfessionTests(unittest.TestCase):
    def test_bundled_profession_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            with mock.patch("arka.agent.profession_plugins.REGISTRY_FILE", cache / "third_party_professions.json"):
                from arka.agent.profession_plugins import discover_professions

                ids = {row["id"] for row in discover_professions(refresh=True)}
                self.assertIn("life_sciences", ids)


if __name__ == "__main__":
    unittest.main()
