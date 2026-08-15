"""Arka Output Viewer — render JSON, CSV, markdown, and text in the browser."""

from arka.web.output_viewer.cli import main, open_content_in_viewer, show_file
from arka.web.output_viewer.detect import detect_format
from arka.web.output_viewer.render import build_page, render_content
from arka.web.output_viewer.server import serve

__all__ = [
    "build_page",
    "detect_format",
    "main",
    "open_content_in_viewer",
    "render_content",
    "serve",
    "show_file",
]
