"""Tests for skill manifest audit and trigger normalization."""

from __future__ import annotations

import json

from arka.agent.skills import _audit_skill_manifest, _skill_from_manifest


def test_auto_trigger_not_duplicated_when_already_present(tmp_path):
    root = tmp_path / "fetch_lyrics"
    root.mkdir()
    manifest = root / "skill.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "fetch_lyrics",
                "type": "python",
                "entry": "run.py",
                "triggers": ["fetch lyrics", "get lyrics"],
            }
        ),
        encoding="utf-8",
    )
    (root / "run.py").write_text("", encoding="utf-8")

    sk = _skill_from_manifest(manifest)
    assert sk is not None
    assert sk["triggers"].count("fetch lyrics") == 1


def test_auto_trigger_inserts_humanized_name_when_missing(tmp_path):
    root = tmp_path / "music_generate"
    root.mkdir()
    manifest = root / "skill.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "music_generate",
                "type": "python",
                "entry": "run.py",
                "triggers": ["generate music", "create music"],
            }
        ),
        encoding="utf-8",
    )
    (root / "run.py").write_text("", encoding="utf-8")

    sk = _skill_from_manifest(manifest)
    assert sk is not None
    assert "music generate" in sk["triggers"]
    assert len(sk["triggers"]) == len(set(sk["triggers"]))


def test_audit_flags_required_env_with_documented_fallback():
    issues = _audit_skill_manifest(
        {
            "name": "music_generate",
            "description": "Generate music with Pollinations or ffmpeg tone-synthesis fallback when no API key is configured",
            "triggers": ["generate music"],
            "requires": {"env": ["POLLINATIONS_API_KEY"], "bins": ["ffmpeg"]},
        }
    )
    assert any("POLLINATIONS_API_KEY" in issue for issue in issues)


def test_audit_flags_duplicate_triggers():
    issues = _audit_skill_manifest(
        {
            "name": "demo",
            "description": "Demo skill",
            "triggers": ["dub video", "dub video", "dubbing"],
            "requires": {},
        }
    )
    assert any("duplicate triggers" in issue for issue in issues)


def test_music_generate_gate_passes_without_pollinations_key(monkeypatch):
    monkeypatch.delenv("POLLINATIONS_API_KEY", raising=False)
    monkeypatch.delenv("POLLINATIONS_KEY", raising=False)

    from arka.agent.skills import _skill_gates

    sk = {
        "name": "music_generate",
        "requires": {"bins": ["ffmpeg"], "env_optional": ["POLLINATIONS_API_KEY"]},
        "os": [],
        "permissions": ["read", "write", "network", "shell"],
    }
    ok, reason = _skill_gates(sk)
    assert ok, reason
