"""Tests for the Arka Output Viewer."""

from __future__ import annotations

import io
import json


from arka.web.output_viewer.cli import main, show_content
from arka.web.output_viewer.detect import detect_format
from arka.web.output_viewer.render import build_page, render_content
from arka.web.output_viewer.server import OutputViewerHandler, serve


def test_detect_format_json_array():
    content = json.dumps([{"name": "Ada", "score": 99}, {"name": "Lin", "score": 88}])
    assert detect_format(content) == "json_array"


def test_detect_format_csv():
    content = "name,score\nAda,99\nLin,88\n"
    assert detect_format(content) == "csv"


def test_detect_format_markdown():
    content = "# Title\n\n- one\n- two\n\n**bold** text"
    assert detect_format(content) == "markdown"


def test_detect_format_from_filename():
    assert detect_format("a,b\n1,2", filename="data.csv") == "csv"
    assert detect_format("# Hi", filename="notes.md") == "markdown"


def test_render_json_array_as_table():
    content = json.dumps([{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}])
    payload = render_content(content)
    assert payload["format"] == "json_array"
    assert "<table" in payload["body_html"]
    assert "alpha" in payload["body_html"]


def test_render_markdown_headings():
    payload = render_content("# Hello\n\nParagraph.", fmt="markdown")
    assert "<h1>" in payload["body_html"]
    assert "Paragraph." in payload["body_html"]


def test_build_page_standalone_hides_toolbar():
    page = build_page('{"ok": true}', filename="status.json", interactive=False)
    assert "toolbar" in page
    assert 'class="toolbar" hidden' in page
    assert "ok" in page


def test_output_viewer_handler_post_render():
    handler = OutputViewerHandler.__new__(OutputViewerHandler)
    handler.headers = {}
    handler.requestline = "POST /api/render HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = "POST"
    handler.path = "/api/render"
    handler.rfile = io.BytesIO(
        json.dumps({"content": "name,value\na,1\nb,2", "filename": "demo.csv"}).encode("utf-8")
    )
    handler.headers = {"Content-Length": str(handler.rfile.getbuffer().nbytes)}
    handler.wfile = io.BytesIO()
    handler.do_POST()
    raw = handler.wfile.getvalue().decode("utf-8")
    body = raw.split("\r\n\r\n", 1)[-1]
    payload = json.loads(body)
    assert payload["format"] == "csv"
    assert "<table" in payload["body_html"]


def test_show_content_writes_html(tmp_path, monkeypatch):
    opened = {}

    def fake_open(url: str) -> bool:
        opened["url"] = url
        return True

    monkeypatch.setattr("arka.web.output_viewer.cli.webbrowser.open", fake_open)
    result = show_content('{"hello":"world"}', filename="demo.json", open_browser=True)
    output = result["output"]
    assert output.endswith(".html")
    text = open(output, encoding="utf-8").read()
    assert "hello" in text
    assert opened["url"].startswith("file://")


def test_main_show_no_open(tmp_path, capsys):
    src = tmp_path / "data.json"
    src.write_text('{"n": 1}', encoding="utf-8")
    assert main(["show", str(src), "--no-open"]) == 0
    out = capsys.readouterr().out
    assert "Output viewer:" in out


def test_serve_binds_viewer_port(monkeypatch):
    seen = {}

    class FakeServer:
        def __init__(self, addr, handler):
            seen["addr"] = addr

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setenv("ARKA_OUTPUT_VIEWER_PORT", "8795")
    monkeypatch.setattr("arka.web.output_viewer.server.ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr("arka.web.output_viewer.server.signal.signal", lambda *_a, **_k: None)
    assert serve() == 0
    assert seen["addr"] == ("127.0.0.1", 8795)
