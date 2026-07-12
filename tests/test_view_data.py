"""Tests for colored CSV terminal viewer."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from arka.agent.view_data import (
    format_colored_table,
    format_save_message,
    nl_to_argv,
    render_csv,
    route_command,
    save_table_exports,
    wants_view_data,
)

FIXTURE = Path(__file__).parent / "fixtures" / "pubmed_sample.csv"
LONG_TITLE = "A" * 120


def test_route_view_csv_with_file() -> None:
    assert wants_view_data("view colored csv pubmed_sample.csv")
    route = route_command("view colored csv pubmed_sample.csv")
    assert "view_data" in route
    assert "pubmed_sample.csv" in route


def test_wants_view_data_excludes_data_ask() -> None:
    assert not wants_view_data("analyze csv files in data/")
    assert wants_view_data("show csv papers.csv")


def test_nl_to_argv_plain_flag() -> None:
    argv = nl_to_argv("show csv papers.csv plain no color")
    assert "--plain" in argv
    assert "papers.csv" in argv


def test_nl_to_argv_formats() -> None:
    argv = nl_to_argv("view csv papers.csv as json and save formats csv,yaml")
    assert "papers.csv" in argv
    assert "--formats" in argv


def test_render_pubmed_csv_plain() -> None:
    text = FIXTURE.read_text()
    out, _, _ = render_csv(io.StringIO(text), plain=True, max_rows=10)
    assert "pmid" in out
    assert "42436396" in out
    assert "SAMM50" in out
    assert "\033[" not in out


def test_render_pubmed_csv_colored() -> None:
    text = FIXTURE.read_text()
    out, _, _ = render_csv(io.StringIO(text), plain=False, max_rows=10)
    assert "\033[33m" in out
    assert "\033[32m" in out
    assert "\033[34m" in out
    assert "42436396" in out


def test_no_truncation_of_long_title() -> None:
    header = ["pmid", "title", "year"]
    rows = [["1", LONG_TITLE, "2026"]]
    out = format_colored_table(header, rows, plain=True)
    assert LONG_TITLE in out
    assert "…" not in out


def test_save_exports_multiple_formats() -> None:
    text = FIXTURE.read_text()
    _, header, rows = render_csv(io.StringIO(text), plain=True, max_rows=None)
    with tempfile.TemporaryDirectory() as tmp:
        saved = save_table_exports(
            header,
            rows,
            out_dir=Path(tmp),
            stem="pubmed_sample",
            formats=["csv", "json", "yaml"],
        )
        assert len(saved) == 3
        names = {p.name for p in saved}
        assert "pubmed_sample.csv" in names
        assert "pubmed_sample.json" in names
        assert "pubmed_sample.yaml" in names
        msg = format_save_message(saved, plain=True)
        assert "Saved to" in msg
        assert "pubmed_sample.csv" in msg
