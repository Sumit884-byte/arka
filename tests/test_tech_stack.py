"""Tests for tech stack folder search and suggestions."""

from __future__ import annotations

from pathlib import Path

from arka.agent.tech_stack import (
    extract_project_name,
    find_similar_folders,
    read_project_stack,
    resolve_project_folder,
    suggest_tech_stack,
)
from arka.routing.symbolic import route_tech_stack


class TestTechStackRouting:
    def test_route_nl(self) -> None:
        hit = route_tech_stack("what is the best tech stack for arka-agent")
        assert hit is not None
        assert "tech_stack suggest" in hit
        assert "arka-agent" in hit

    def test_extract_project_name(self) -> None:
        assert extract_project_name("best tech stacks for arka-agent") == "arka-agent"
        assert extract_project_name('recommended tech stack for "my-app"') == "my-app"

    def test_does_not_match_folder_navigation(self) -> None:
        from arka.agent.tech_stack import nl_to_argv

        for cmd in ("to Downloads", "'to Downloads'", "go to Downloads folder"):
            assert extract_project_name(cmd) is None, cmd
            assert nl_to_argv(cmd) == [], cmd


class TestFolderSearch:
    def test_finds_repo_by_package_name(self, tmp_path: Path) -> None:
        project = tmp_path / "arka"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            '[project]\nname = "arka-agent"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        matches = find_similar_folders("arka-agent", roots=[tmp_path])
        assert matches
        assert matches[0].path == project
        assert matches[0].package_name == "arka-agent"

    def test_exact_vs_similar(self, tmp_path: Path) -> None:
        exact = tmp_path / "arka-agent"
        exact.mkdir()
        (exact / "README.md").write_text("# demo", encoding="utf-8")
        similar = tmp_path / "arka"
        similar.mkdir()
        (similar / "pyproject.toml").write_text('name = "other"\n', encoding="utf-8")
        matches = find_similar_folders("arka-agent", roots=[tmp_path])
        assert matches[0].exact is True
        assert matches[0].path == exact


class TestSuggest:
    def test_non_interactive_fuzzy_requires_yes(self, tmp_path: Path) -> None:
        project = tmp_path / "arka"
        project.mkdir()
        (project / "pyproject.toml").write_text('name = "arka-agent"\n', encoding="utf-8")
        result = suggest_tech_stack("arka-agent", roots=[str(tmp_path)], interactive=False)
        assert result["ok"] is True

    def test_non_interactive_name_mismatch_blocks(self, tmp_path: Path) -> None:
        project = tmp_path / "arka"
        project.mkdir()
        (project / "README.md").write_text("# x", encoding="utf-8")
        match, reason = resolve_project_folder("totally-other", roots=[str(tmp_path)], interactive=False)
        assert match is None
        assert reason

    def test_read_project_stack(self, tmp_path: Path) -> None:
        project = tmp_path / "demo"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            "[project]\nname = 'demo'\nrequires-python = '>=3.11'\n",
            encoding="utf-8",
        )
        stack = read_project_stack(project)
        assert "Python" in stack["languages"]
        assert stack["recommendations"]

    def test_suggest_with_yes(self, tmp_path: Path) -> None:
        project = tmp_path / "arka"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            "[project]\nname = 'arka-agent'\nrequires-python = '>=3.11'\n",
            encoding="utf-8",
        )
        result = suggest_tech_stack(
            "arka-agent",
            roots=[str(tmp_path)],
            assume_yes=True,
            interactive=False,
        )
        assert result["ok"] is True
        assert result["match"]["path"].endswith("/arka")
