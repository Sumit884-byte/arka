"""Tests for workspace file read helper and routing."""

from __future__ import annotations

import json
from pathlib import Path

from arka.agent.read_file import read_file_payload, route_command, wants_read_file


def test_wants_read_file_source_path() -> None:
    assert wants_read_file("read file src/arka/agent/goal.py")
    assert not wants_read_file("read the entire repo")
    assert not wants_read_file("read markdown file docs/guide.mdx")


def test_route_read_file() -> None:
    route = route_command("show file src/arka/agent/goal.py")
    assert route.startswith("read_file read ")
    assert "goal.py" in route


def test_read_file_payload(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    payload = read_file_payload("demo.py", root=tmp_path)
    assert payload["ok"] is True
    assert payload["content"] == "line1\nline2\nline3"
    assert payload["total_lines"] == 3


def test_read_file_offset_limit(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("a\nb\nc\nd\n", encoding="utf-8")
    payload = read_file_payload("demo.py", root=tmp_path, offset=2, limit=2)
    assert payload["ok"] is True
    assert payload["content"] == "b\nc\n"
    assert payload["truncated"] is True


def test_read_file_blocks_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=1\n", encoding="utf-8")
    payload = read_file_payload(".env", root=tmp_path)
    assert payload["ok"] is False
    assert payload.get("blocked") is True


def test_read_file_too_large(tmp_path: Path) -> None:
    target = tmp_path / "big.txt"
    target.write_text("x" * 2000, encoding="utf-8")
    payload = read_file_payload("big.txt", root=tmp_path, max_bytes=100)
    assert payload["ok"] is False
    assert "too large" in payload["error"]


def test_handle_arka_read_file_mcp(tmp_path: Path) -> None:
    from arka.integrations.mcp_server import _handle_arka_read_file

    target = tmp_path / "sample.py"
    target.write_text("print('hi')\n", encoding="utf-8")
    payload = json.loads(_handle_arka_read_file({"path": str(target), "root": str(tmp_path)}))
    assert payload["ok"] is True
    assert "print('hi')" in payload["content"]
