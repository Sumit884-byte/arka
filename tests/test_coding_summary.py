from pathlib import Path

from arka.agent.core import _coding_summary


def test_coding_summary_includes_status_and_next_check(tmp_path: Path):
    summary = _coding_summary(tmp_path, "add search", 2, completed=1, failed_step=2)
    assert "✗ Coding summary: failed at step 2/2" in summary
    assert "add search" in summary
    assert "arka ci --changed" in summary


def test_coding_summary_success_mark(tmp_path: Path):
    summary = _coding_summary(tmp_path, "add search", 2, completed=2)
    assert "✓ Coding summary: completed 2/2 step(s)" in summary
