"""Tests for skill registry classification, listing format, and routing."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from arka.agent.skills import (
    _format_requires,
    discover_skills,
    match_command,
    print_list,
    skill_origin,
)
from arka.paths import package_dir
from arka.routing.symbolic import route_ai_video, route_compose_video


def test_skill_origin_builtin_package_path():
    root = package_dir() / "skills" / "ai_video"
    assert skill_origin(root) == "builtin"


def test_skill_origin_third_party_config_path(tmp_path):
    root = tmp_path / "skills" / "custom_plugin"
    assert skill_origin(root) == "third-party"


def test_skill_origin_mcp():
    assert skill_origin(None, adapter="mcp") == "mcp"
    assert skill_origin("", adapter="mcp") == "mcp"


def test_format_requires_renders_env_sections():
    text = _format_requires(
        {
            "env_optional": ["POLLINATIONS_API_KEY", "GEMINI_API_KEY"],
            "bins": ["ffmpeg"],
            "note": "Needs at least one backend key.",
        }
    )
    assert "env (optional): POLLINATIONS_API_KEY, GEMINI_API_KEY" in text
    assert "bins: ffmpeg" in text
    assert "note: Needs at least one backend key." in text
    assert "{" not in text


def test_builtin_skills_not_listed_as_third_party(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", registry)
    monkeypatch.setattr(
        "arka.agent.skills.skills_search_paths",
        lambda: [package_dir() / "skills"],
    )

    skills = discover_skills(refresh=True)
    ai = next(s for s in skills if s["name"] == "ai_video")
    assert ai["origin"] == "builtin"
    assert all(s.get("origin") == "builtin" for s in skills if s.get("adapter") == "arka-manifest")


def test_third_party_skill_classified_separately(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    plugin = root / "demo_plugin"
    plugin.mkdir(parents=True)
    (plugin / "skill.json").write_text(
        json.dumps(
            {
                "name": "demo_plugin",
                "type": "python",
                "entry": "run.py",
                "triggers": ["demo plugin action"],
            }
        ),
        encoding="utf-8",
    )
    (plugin / "run.py").write_text("", encoding="utf-8")

    monkeypatch.setenv("SKILLS_PATH", str(root))
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(
        "arka.agent.skills.skills_search_paths",
        lambda: [package_dir() / "skills", root],
    )

    skills = discover_skills(refresh=True)
    demo = next(s for s in skills if s["name"] == "demo_plugin")
    assert demo["origin"] == "third-party"


def test_compose_video_doc_only_dir_not_external_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(
        "arka.agent.skills.skills_search_paths",
        lambda: [package_dir() / "skills"],
    )

    skills = discover_skills(refresh=True)
    assert not any(s["name"] == "compose_video" for s in skills)


def test_print_list_groups_builtin_and_formats_requires(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(
        "arka.agent.skills.skills_search_paths",
        lambda: [package_dir() / "skills"],
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_list(verbose=True)
    out = buf.getvalue()

    assert "Built-in skills (" in out
    assert "Third-party skills (" not in out or "Third-party skills (0)" not in out
    assert "ai_video" in out
    assert "origin=builtin" in out
    assert "requires: {'" not in out
    assert "env (optional):" in out


@pytest.mark.parametrize(
    ("cmd", "expected_skill"),
    [
        ("generate video of a cat walking", "ai_video"),
        ("create video from photos", "create_video"),
        ("generate ai video sunset mountains", "ai_video"),
    ],
)
def test_plugin_match_video_skills(cmd: str, expected_skill: str, tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(
        "arka.agent.skills.skills_search_paths",
        lambda: [package_dir() / "skills"],
    )
    discover_skills(refresh=True)

    matched = match_command(cmd)
    assert matched.startswith(expected_skill)


def test_compose_video_topic_not_matched_by_ai_video_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr("arka.agent.skills.REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(
        "arka.agent.skills.skills_search_paths",
        lambda: [package_dir() / "skills"],
    )
    discover_skills(refresh=True)

    cmd = "create a 5 minute video on artificial intelligence"
    assert match_command(cmd) == ""
    assert route_ai_video(cmd) is None
    assert route_compose_video(cmd) is not None
