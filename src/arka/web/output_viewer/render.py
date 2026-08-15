"""HTML renderers for the Arka Output Viewer."""

from __future__ import annotations

import csv
import html
import io
import json
import re
from pathlib import Path
from typing import Any

from arka.web.output_viewer.detect import detect_format

_MEDIA_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".pdf"})


def render_content(content: str, *, fmt: str | None = None, filename: str | None = None, title: str | None = None) -> dict[str, Any]:
    """Render content to an HTML fragment and metadata."""
    resolved = fmt or detect_format(content, filename=filename)
    title = (title or filename or "Arka output").strip() or "Arka output"
    renderers = {
        "json": _render_json,
        "json_array": _render_table_from_json,
        "json_object": _render_key_value,
        "jsonl": _render_jsonl,
        "csv": _render_csv,
        "markdown": _render_markdown,
        "yaml": _render_pre,
        "media": _render_media,
        "text": _render_pre,
    }
    renderer = renderers.get(resolved, _render_pre)
    body_html = renderer(content, filename=filename)
    return {
        "format": resolved,
        "title": title,
        "filename": filename,
        "body_html": body_html,
    }


def build_page(
    content: str,
    *,
    fmt: str | None = None,
    filename: str | None = None,
    title: str | None = None,
    interactive: bool = False,
) -> str:
    """Build a full HTML document for standalone viewing."""
    payload = render_content(content, fmt=fmt, filename=filename, title=title)
    view_html = _wrap_view(payload)
    if interactive:
        shell = _load_shell()
        return (
            shell.replace("{{TITLE}}", html.escape(payload["title"]))
            .replace("{{INITIAL_VIEW}}", view_html)
        )
    shell = _load_shell()
    # Standalone export: hide paste toolbar and embed rendered view only.
    standalone = shell.replace("<section class=\"toolbar\">", '<section class="toolbar" hidden>')
    return (
        standalone.replace("{{TITLE}}", html.escape(payload["title"]))
        .replace("{{INITIAL_VIEW}}", view_html)
    )


def _wrap_view(payload: dict[str, Any]) -> str:
    fmt = html.escape(str(payload.get("format") or "text"))
    filename = payload.get("filename")
    meta = f"<span class='badge'>{fmt}</span>"
    if filename:
        meta += f" <span class='muted'>{html.escape(str(filename))}</span>"
    return (
        f"<header class='view-header'><h1>{html.escape(str(payload.get('title') or 'Arka output'))}</h1>"
        f"<div class='meta'>{meta}</div></header>"
        f"<main class='view-body'>{payload.get('body_html') or ''}</main>"
    )


def _load_shell() -> str:
    static_path = Path(__file__).resolve().parent.parent / "static" / "output_viewer.html"
    return static_path.read_text(encoding="utf-8")


def _render_json(content: str, *, filename: str | None = None) -> str:
    try:
        parsed = json.loads(content)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        pretty = content
    return f"<pre class='code-block'><code>{html.escape(pretty)}</code></pre>"


def _render_jsonl(content: str, *, filename: str | None = None) -> str:
    rows: list[dict[str, Any]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    if rows:
        return _render_table(rows)
    return _render_pre(content, filename=filename)


def _render_table_from_json(content: str, *, filename: str | None = None) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return _render_pre(content, filename=filename)
    if isinstance(parsed, list) and parsed and all(isinstance(row, dict) for row in parsed):
        return _render_table(parsed)
    return _render_json(content, filename=filename)


def _render_key_value(content: str, *, filename: str | None = None) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return _render_pre(content, filename=filename)
    if not isinstance(parsed, dict):
        return _render_json(content, filename=filename)
    items = []
    for key, value in parsed.items():
        if isinstance(value, (dict, list)):
            rendered = html.escape(json.dumps(value, indent=2, ensure_ascii=False))
            cell = f"<pre class='inline-json'>{rendered}</pre>"
        else:
            cell = html.escape(str(value))
        items.append(f"<tr><th>{html.escape(str(key))}</th><td>{cell}</td></tr>")
    return (
        "<table class='data-table kv-table'><tbody>"
        + "".join(items)
        + "</tbody></table>"
    )


def _render_csv(content: str, *, filename: str | None = None) -> str:
    delimiter = "\t" if filename and filename.lower().endswith(".tsv") else ","
    try:
        sample = content[:8192]
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return _render_pre(content, filename=filename)
    headers = [str(cell) for cell in rows[0]]
    body_rows = [[str(cell) for cell in row] for row in rows[1:]]
    return _render_table_dicts([dict(zip(headers, row, strict=False)) for row in body_rows], headers=headers)


def _render_table(rows: list[dict[str, Any]]) -> str:
    headers: list[str] = []
    seen: set[str] = set()
    for row in rows[:200]:
        for key in row:
            key_str = str(key)
            if key_str not in seen:
                seen.add(key_str)
                headers.append(key_str)
    return _render_table_dicts(rows[:500], headers=headers)


def _render_table_dicts(rows: list[dict[str, Any]], *, headers: list[str]) -> str:
    if not headers:
        return "<p class='muted'>No columns detected.</p>"
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_parts: list[str] = []
    for row in rows:
        cells = []
        for header in headers:
            value = row.get(header, "")
            if isinstance(value, (dict, list)):
                text = json.dumps(value, ensure_ascii=False)
            else:
                text = str(value)
            cells.append(f"<td>{html.escape(text)}</td>")
        body_parts.append("<tr>" + "".join(cells) + "</tr>")
    note = ""
    if len(rows) >= 500:
        note = "<p class='muted'>Showing first 500 rows.</p>"
    return (
        note
        + "<div class='table-wrap'><table class='data-table'><thead><tr>"
        + head
        + "</tr></thead><tbody>"
        + "".join(body_parts)
        + "</tbody></table></div>"
    )


def _render_markdown(content: str, *, filename: str | None = None) -> str:
    return f"<article class='markdown-body'>{_markdown_to_html(content)}</article>"


def _render_pre(content: str, *, filename: str | None = None) -> str:
    return f"<pre class='code-block text-block'>{html.escape(content)}</pre>"


def _render_media(content: str, *, filename: str | None = None) -> str:
    paths = _collect_media_paths(content)
    cards: list[str] = []
    for path in paths[:24]:
        ext = Path(path).suffix.lower()
        label = html.escape(path)
        resolved = Path(path).expanduser()
        src = path
        if resolved.is_file():
            src = resolved.resolve().as_uri()
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            cards.append(
                f"<figure class='media-card'><img src='{html.escape(src)}' alt='{label}' loading='lazy'>"
                f"<figcaption>{label}</figcaption></figure>"
            )
        elif ext in {".mp4", ".webm", ".mov"}:
            cards.append(
                f"<figure class='media-card'><video controls src='{html.escape(src)}'></video>"
                f"<figcaption>{label}</figcaption></figure>"
            )
        elif ext in {".mp3", ".wav"}:
            cards.append(
                f"<figure class='media-card'><audio controls src='{html.escape(src)}'></audio>"
                f"<figcaption>{label}</figcaption></figure>"
            )
        else:
            cards.append(f"<div class='media-card file-card'><a href='{html.escape(src)}'>{label}</a></div>")
    if not cards:
        return _render_key_value(content, filename=filename) if content.strip().startswith("{") else _render_pre(content, filename=filename)
    return "<div class='media-grid'>" + "".join(cards) + "</div>"


def _collect_media_paths(content: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = value.strip()
        if not text or text in seen:
            return
        if Path(text).suffix.lower() in _MEDIA_EXT or text.startswith(("http://", "https://", "file://")):
            seen.add(text)
            found.append(text)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        for match in re.finditer(r'(["\'])([^"\']+\.(?:png|jpe?g|gif|webp|mp4|webm|pdf|svg|mp3|wav))\1', content, re.I):
            add(match.group(2))
        return found

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            add(value)

    walk(parsed)
    return found


def _markdown_to_html(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    code_lines: list[str] = []
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("```"):
            close_list()
            if in_code:
                out.append(f"<pre class='code-block'><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        header = re.match(r"^(#{1,6})\s+(.*)$", line)
        if header:
            close_list()
            level = len(header.group(1))
            out.append(f"<h{level}>{_inline_md_html(header.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^[\-*+]\s+(.*)$", stripped)
        if bullet:
            if not list_open:
                out.append("<ul>")
                list_open = True
            out.append(f"<li>{_inline_md_html(bullet.group(1))}</li>")
            continue

        ordered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered:
            close_list()
            out.append(f"<p>{_inline_md_html(ordered.group(1))}</p>")
            continue

        if stripped.startswith(">"):
            close_list()
            out.append(f"<blockquote>{_inline_md_html(stripped.lstrip('>').strip())}</blockquote>")
            continue

        if not stripped:
            close_list()
            out.append("")
            continue

        close_list()
        out.append(f"<p>{_inline_md_html(stripped)}</p>")

    close_list()
    if in_code and code_lines:
        out.append(f"<pre class='code-block'><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(out)


def _inline_md_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<a href='\2' rel='noopener'>\1</a>", escaped)
    return escaped
