"""Tests for arka setup side effects."""

from __future__ import annotations

import unittest
from unittest import mock


class SetupRepoIndexTests(unittest.TestCase):
    @mock.patch("arka.cli.ensure_layout")
    @mock.patch("arka.platform_info.ensure_platform_cache")
    @mock.patch("arka.setup_runtime.ensure_venv")
    @mock.patch("arka.setup_runtime.resolve_venv_python")
    @mock.patch("arka.setup_runtime.verify_chat_imports")
    @mock.patch("arka.integrations.context7_mcp.setup_context7")
    @mock.patch("arka.integrations.mcp_server.ensure_arka_self_in_config")
    @mock.patch("arka.agent.repo_context.sync_index")
    @mock.patch("arka.cli.env_file")
    @mock.patch("arka.cli.skill_mode")
    def test_setup_calls_sync_index(
        self,
        skill_mode: mock.MagicMock,
        env_file: mock.MagicMock,
        sync_index: mock.MagicMock,
        ensure_self_mcp: mock.MagicMock,
        setup_context7: mock.MagicMock,
        verify_chat: mock.MagicMock,
        resolve_venv: mock.MagicMock,
        ensure_venv: mock.MagicMock,
        ensure_cache: mock.MagicMock,
        ensure_layout: mock.MagicMock,
    ) -> None:
        from arka.cli import _cmd_setup

        ensure_cache.return_value = {"platform": "test"}
        resolve_venv.return_value = "/tmp/venv/bin/python3"
        verify_chat.return_value = []
        ensure_self_mcp.return_value = False
        sync_index.return_value = {"ok": True, "changed": 3, "skipped": False}
        env_file.return_value.is_file.return_value = True
        skill_mode.return_value = "full"

        rc = _cmd_setup(["--no-context7"])
        self.assertEqual(rc, 0)
        sync_index.assert_called_once_with(quiet=True)


if __name__ == "__main__":
    unittest.main()
