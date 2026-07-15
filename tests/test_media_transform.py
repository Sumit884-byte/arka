from pathlib import Path

from arka.media.media_transform import to_book
from arka.routing.symbolic import route_offline_extras


def test_text_to_book(tmp_path: Path):
    source = tmp_path / "talk.txt"
    source.write_text("First point. Second point.\n\nA new section.")
    output = to_book(str(source), tmp_path / "book.md")
    assert output.is_file()
    assert "Chapter 1" in output.read_text()


def test_playlist_to_book_route():
    result = route_offline_extras("turn https://youtube.com/playlist?list=abc into a book")
    assert result.startswith("media_transform")
    assert "--to book" in result
