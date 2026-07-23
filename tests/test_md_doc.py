from pathlib import Path

import pytest

from arka.agent.md_doc import (
    context_block,
    extract_md_path,
    read_markdown,
    resolve_md,
    route_command,
    wants_md_doc,
)


def test_extract_md_path() -> None:
    assert extract_md_path('read docs/guide.md') == "docs/guide.md"
    assert extract_md_path("use ~/notes/README.md for setup") == "~/notes/README.md"


def test_wants_md_doc() -> None:
    assert wants_md_doc("read README.md")
    assert wants_md_doc("summarize docs/setup.md")
    assert not wants_md_doc("analyze csv data.csv")


def test_route_read_and_ask() -> None:
    assert route_command("read README.md").startswith("md_doc read ")
    assert "ask" in route_command("summarize docs/guide.md")
    assert route_command("use notes/todo.md").startswith("md_doc read ")


def test_read_markdown(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# Title\n\nBody text.\n", encoding="utf-8")
    text = read_markdown(path)
    assert "Title" in text
    assert context_block(path).startswith("Markdown (note.md):")


def test_resolve_md_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_md(tmp_path / "missing.md")
