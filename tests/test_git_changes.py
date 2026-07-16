from pathlib import Path

from arka.agent.git_changes import (
    ChangedFile,
    format_changed_files,
    format_plan_files,
    list_changed_files,
)


def test_list_changed_files_parses_porcelain(monkeypatch, tmp_path: Path):
    output = "\n".join(
        [
            " M src/arka/agent/coding_tui.py",
            "A  docs/guides/coding-tui.mdx",
            "?? tests/test_git_changes.py",
            "D  old_module.py",
            "R  old_name.py -> src/new_name.py",
        ]
    )

    class FakeProc:
        returncode = 0
        stdout = output

    monkeypatch.setattr(
        "arka.agent.git_changes.subprocess.run",
        lambda *args, **kwargs: FakeProc(),
    )

    rows = list_changed_files(tmp_path)
    assert rows == [
        ChangedFile(path="old_module.py", status="D"),
        ChangedFile(path="src/arka/agent/coding_tui.py", status="M"),
        ChangedFile(path="src/new_name.py", status="R"),
        ChangedFile(path="docs/guides/coding-tui.mdx", status="A"),
        ChangedFile(path="tests/test_git_changes.py", status="A"),
    ]


def test_format_changed_files_renders_boxed_list():
    text = format_changed_files(
        Path("."),
        files=[
            ChangedFile(path="src/arka/agent/coding_tui.py", status="M"),
            ChangedFile(path="tests/test_coding_tui.py", status="M"),
            ChangedFile(path="docs/guides/coding-tui.mdx", status="A"),
        ],
    )
    assert "━━━ Changed files (3) ━━━" in text
    assert "  M  src/arka/agent/coding_tui.py" in text
    assert "  M  tests/test_coding_tui.py" in text
    assert "  A  docs/guides/coding-tui.mdx" in text


def test_format_changed_files_empty_message():
    assert format_changed_files(Path("."), files=[]) == "○ No changes."


def test_format_plan_files_numbered_with_reasons():
    text = format_plan_files(
        [
            ("src/arka/router.py", "adjust route precedence"),
            ("src/arka/dispatch.py", "wire the route to execution"),
        ],
        title="Files to touch",
    )
    assert "━━━ Files to touch (2) ━━━" in text
    assert "1. src/arka/router.py — adjust route precedence" in text
    assert "2. src/arka/dispatch.py — wire the route to execution" in text
