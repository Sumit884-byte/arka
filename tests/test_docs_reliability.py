from pathlib import Path


def test_docs_reliability_checker_passes_current_docs():
    from scripts.check_docs import check_docs

    assert check_docs(Path("docs")) == []


def test_docs_reliability_checker_catches_broken_internal_link(tmp_path):
    from scripts.check_docs import check_docs

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.mdx").write_text(
        "---\ntitle: Home\nicon: \"house\"\n---\n\nSee [missing](/guides/missing).\n",
        encoding="utf-8",
    )

    problems = check_docs(docs)

    assert problems
    assert "broken internal link /guides/missing" in problems[0]
