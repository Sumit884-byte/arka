from __future__ import annotations

import json


def test_preview_is_non_mutating(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    from arka.core.default_config import main, path

    assert main(["configure", "--json"]) == 0
    assert not path().exists()


def test_apply_preserves_explicit_values(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("ROUTE_MODE", "ai")
    from arka.core.default_config import main, path

    assert main(["configure", "--apply"]) == 0
    data = json.loads(path().read_text())
    assert data["defaults"]["ROUTE_MODE"] == "ai"
    assert data["defaults"]["PROMPT_OPTIMIZE"] == "1"


def test_config_reset_only_removes_arka_config(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    from arka.core.default_config import main, path

    main(["configure", "--apply"])
    assert path().exists()
    assert main(["reset"]) == 0
    assert not path().exists()
