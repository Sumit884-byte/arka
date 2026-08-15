"""Tests for edit guardrails on MCP file edits."""

from __future__ import annotations

import json

import pytest

from arka.core import edit_guard as eg


def test_blocks_env_file():
    result = eg.check_edit_path(".env")
    assert not result.allowed
    assert "edit blocked" in result.reason


def test_allows_env_example():
    result = eg.check_edit_path(".env.example")
    assert result.allowed


def test_blocks_secrets_directory():
    result = eg.check_edit_path("secrets/api.key")
    assert not result.allowed


def test_custom_blocked_glob(monkeypatch):
    monkeypatch.setenv("BLOCKED_EDIT_PATHS", "recordings/**")
    result = eg.check_edit_path("recordings/reels/demo.mp4")
    assert not result.allowed
    assert "recordings/**" in result.pattern


def test_allowed_override(monkeypatch):
    monkeypatch.setenv("BLOCKED_EDIT_PATHS", "src/**")
    monkeypatch.setenv("ALLOWED_EDIT_PATHS", "src/arka/core/edit_guard.py")
    result = eg.check_edit_path("src/arka/core/edit_guard.py")
    assert result.allowed


def test_files_in_unified_diff():
    diff = """--- a/.env
+++ b/.env
@@ -1 +1 @@
-OLD=1
+OLD=2
"""
    assert eg.files_in_unified_diff(diff) == [".env"]


def test_apply_patch_blocks_env(tmp_path, monkeypatch):
    from arka.agent.apply_patch import PatchError, apply_patch_payload

    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    monkeypatch.setattr("arka.core.code_project.get_active_root", lambda: tmp_path)
    with pytest.raises(PatchError, match="edit blocked"):
        apply_patch_payload(
            root=tmp_path,
            file=".env",
            search="SECRET=1",
            replace="SECRET=2",
        )


def test_mcp_apply_patch_returns_blocked_json(tmp_path, monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_apply_patch

    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    monkeypatch.setattr("arka.core.code_project.get_active_root", lambda: tmp_path)
    payload = json.loads(
        _handle_arka_apply_patch(
            {
                "path": str(tmp_path),
                "file": ".env",
                "search": "SECRET=1",
                "replace": "SECRET=2",
            }
        )
    )
    assert payload["ok"] is False
    assert payload["blocked"] is True


def test_mcp_edit_guard_check(tmp_path):
    from arka.integrations.mcp_server import _handle_arka_edit_guard

    payload = json.loads(
        _handle_arka_edit_guard(
            {"action": "check", "path": "node_modules/foo/index.js", "root": str(tmp_path)}
        )
    )
    assert payload["blocked"] is True
    assert payload["ok"] is False


def test_allows_readme_md():
    result = eg.check_edit_path("README.md")
    assert result.allowed


def test_apply_patch_allows_readme(tmp_path, monkeypatch):
    from arka.agent.apply_patch import apply_patch_payload

    (tmp_path / "README.md").write_text("# Hello\n", encoding="utf-8")
    monkeypatch.setattr("arka.core.code_project.get_active_root", lambda: tmp_path)
    payload = apply_patch_payload(
        root=tmp_path,
        file="README.md",
        search="# Hello",
        replace="# Hello World",
    )
    assert payload["ok"] is True
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Hello World\n"
