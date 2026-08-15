"""CLI entry points for the Arka Output Viewer."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

from arka.web.output_viewer.render import build_page
from arka.web.output_viewer.server import serve


def show_file(path: str, *, open_browser: bool = True, fmt: str | None = None, title: str | None = None) -> dict[str, Any]:
    """Render a file to a temp HTML page and optionally open the browser."""
    src = Path(path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")
    content = src.read_text(encoding="utf-8", errors="replace")
    return show_content(
        content,
        filename=src.name,
        open_browser=open_browser,
        fmt=fmt,
        title=title or src.name,
    )


def show_content(
    content: str,
    *,
    filename: str | None = None,
    open_browser: bool = True,
    fmt: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    document = build_page(content, fmt=fmt, filename=filename, title=title, interactive=False)
    tmp = Path(tempfile.gettempdir()) / f"arka-output-{Path(filename or 'data').stem}.html"
    tmp.write_text(document, encoding="utf-8")
    url = tmp.resolve().as_uri()
    if open_browser:
        webbrowser.open(url)
    return {"output": str(tmp), "url": url, "filename": filename}


def open_content_in_viewer(
    content: str,
    *,
    filename: str | None = None,
    fmt: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Open arbitrary content in the output viewer (used by output_layout --open-ui)."""
    return show_content(content, filename=filename, open_browser=True, fmt=fmt, title=title)


def main(argv: list[str] | None = None) -> int:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(prog="arka output", description="Render data beautifully in the browser")
    sub = parser.add_subparsers(dest="command")

    p_show = sub.add_parser("show", help="Render a file (or stdin) and open the browser")
    p_show.add_argument("path", nargs="?", default="-", help="File path or '-' for stdin")
    p_show.add_argument("--format", dest="fmt", help="Force format (json, csv, markdown, text, …)")
    p_show.add_argument("--title", help="Viewer title")
    p_show.add_argument("--no-open", action="store_true", help="Write HTML but do not open a browser")
    p_show.add_argument("--json", action="store_true", help="Print result metadata as JSON")

    p_serve = sub.add_parser("serve", help="Start interactive paste/upload viewer")
    p_serve.add_argument("--host", default=None, help="Listen host (default 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=None, help="Listen port (default 8790)")
    p_serve.add_argument("--open", action="store_true", help="Open browser after starting")

    p_render = sub.add_parser("render", help="Render to HTML file without opening browser")
    p_render.add_argument("path", help="Input file path")
    p_render.add_argument("-o", "--output", required=True, help="Output HTML path")
    p_render.add_argument("--format", dest="fmt", help="Force format")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    if args.command == "show":
        if args.path == "-":
            content = sys.stdin.read()
            filename = None
        else:
            src = Path(args.path).expanduser()
            if not src.is_file():
                print(f"output show: file not found: {src}", file=sys.stderr)
                return 1
            content = src.read_text(encoding="utf-8", errors="replace")
            filename = src.name
        result = show_content(
            content,
            filename=filename,
            open_browser=not args.no_open,
            fmt=args.fmt,
            title=args.title,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Output viewer: {result['output']}")
            if result.get("url"):
                print(result["url"])
        return 0

    if args.command == "serve":
        if args.open:
            host = args.host or "127.0.0.1"
            port = args.port if args.port is not None else 8790
            webbrowser.open(f"http://{host}:{port}/")
        return serve(host=args.host, port=args.port)

    if args.command == "render":
        src = Path(args.path).expanduser()
        if not src.is_file():
            print(f"output render: file not found: {src}", file=sys.stderr)
            return 1
        content = src.read_text(encoding="utf-8", errors="replace")
        document = build_page(content, fmt=args.fmt, filename=src.name, interactive=False)
        out = Path(args.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(document, encoding="utf-8")
        print(out)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
