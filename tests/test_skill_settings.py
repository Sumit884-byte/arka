from __future__ import annotations

import json


def test_explicit_hosted_profile_disables_device_skills(monkeypatch):
    monkeypatch.setenv("ARKA_HOSTED_MODE", "1")
    from arka.core.skill_settings import is_disabled, profile_disabled

    assert "play_youtube" in profile_disabled()
    assert is_disabled("play_youtube")
    assert not is_disabled("repo_health")


def test_explicit_desktop_profile_keeps_device_skills(monkeypatch):
    monkeypatch.setenv("ARKA_HOSTED_MODE", "0")
    from arka.core.skill_settings import hosted_mode, is_disabled

    assert hosted_mode() == "desktop"
    assert not is_disabled("play_youtube")


def test_enable_overrides_hosted_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("ARKA_HOSTED_MODE", "1")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    from arka.core.skill_settings import is_disabled, main

    assert main(["enable", "play_youtube"]) == 0
    assert not is_disabled("play_youtube")
    data = json.loads((tmp_path / "skills.json").read_text())
    assert data["enabled"] == ["play_youtube"]


def test_profile_status_and_apply(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    from arka.core.skill_settings import main

    assert main(["profile", "hosted", "--apply"]) == 0
    assert "profile\thosted" in capsys.readouterr().out
    assert main(["status"]) == 0
    assert "profile\thosted" in capsys.readouterr().out


def test_hosted_router_skips_browser_skill(monkeypatch):
    monkeypatch.setenv("ARKA_HOSTED_MODE", "1")
    from arka.routing.symbolic import route_offline_extras

    assert route_offline_extras("check this website in a browser") != "browser_check http://127.0.0.1:3000"
