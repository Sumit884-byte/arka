"""Extract uploaded chat attachments into agent-readable text."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
_TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml",
    ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".sql", ".sh", ".bash", ".zsh", ".fish", ".toml",
    ".ini", ".cfg", ".env", ".log",
})
_DOC_SUFFIXES = frozenset({".pdf", ".docx"})
_MEDIA_SUFFIXES = frozenset({".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".opus", ".webm", ".mkv", ".mov", ".aac", ".flac"})

_DEFAULT_MAX_CHARS = 12_000
_DEFAULT_MAX_TEXT_BYTES = 512_000


def _max_inline_chars() -> int:
    try:
        return max(1000, int(os.environ.get("ARKA_CHAT_MEDIA_MAX_CHARS", str(_DEFAULT_MAX_CHARS))))
    except ValueError:
        return _DEFAULT_MAX_CHARS


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "no", "off"}


def _clip(text: str, *, limit: int | None = None) -> str:
    cap = limit or _max_inline_chars()
    cleaned = (text or "").strip()
    if len(cleaned) <= cap:
        return cleaned
    return cleaned[: cap - 20].rstrip() + "\n… [truncated]"


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()[: _DEFAULT_MAX_TEXT_BYTES]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _extract_image_text(path: Path) -> str:
    from arka.agent.ocr_skill import extract_image_payload

    payload = extract_image_payload(path, with_blocks=False, with_zones=False)
    text = str(payload.get("plain_text") or "").strip()
    if text:
        return text
    if not _truthy("ARKA_CHAT_MEDIA_VISION", "1"):
        return ""
    try:
        from arka.vision.describe import describe_source

        return describe_source(str(path), prompt="Describe this image briefly for chat context.").strip()
    except Exception as exc:
        return f"(vision unavailable: {exc})"


def _extract_pdf_text(path: Path) -> str:
    from arka.stock.turboquant_rag import extract_pdf_text

    text = extract_pdf_text(path)
    if text:
        return text.strip()
    try:
        from arka.pdf.rag import _extract_pdf_text_via_ocr

        ocr = _extract_pdf_text_via_ocr(path)
        return (ocr or "").strip()
    except Exception:
        return ""


def _extract_docx_text(path: Path) -> str:
    from arka.stock.turboquant_rag import extract_docx_text

    return (extract_docx_text(path) or "").strip()


def _extract_media_transcript(path: Path) -> str:
    if not _truthy("ARKA_CHAT_MEDIA_TRANSCRIBE", "1"):
        return "(audio/video transcription disabled — set ARKA_CHAT_MEDIA_TRANSCRIBE=1)"
    try:
        from arka.media.transcript import transcribe_file

        return transcribe_file(path).strip()
    except SystemExit as exc:
        return f"(transcription failed: {exc})"
    except Exception as exc:
        return f"(transcription failed: {exc})"


def extract_uploaded_file_content(path: str | Path, *, mime: str = "") -> str:
    """Best-effort text extraction for a saved upload path."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        return "(file missing on server)"

    ext = file_path.suffix.lower()
    media_type = (mime or "").lower()

    try:
        if media_type.startswith("image/") or ext in _IMAGE_SUFFIXES:
            return _extract_image_text(file_path)
        if ext == ".pdf" or media_type == "application/pdf":
            return _extract_pdf_text(file_path)
        if ext == ".docx" or "wordprocessingml" in media_type:
            return _extract_docx_text(file_path)
        if ext in _TEXT_SUFFIXES or media_type.startswith("text/"):
            return _read_text_file(file_path)
        if ext in _MEDIA_SUFFIXES or media_type.startswith(("audio/", "video/")):
            return _extract_media_transcript(file_path)
    except Exception as exc:
        return f"(could not read file: {exc})"

    return f"(unsupported type {ext or media_type or 'unknown'} — saved at {file_path})"


def enrich_agent_text_with_media(text: str, media: list[dict[str, Any]] | None) -> str:
    """Append extracted attachment content so web chat can reason over uploads."""
    items = [row for row in (media or []) if isinstance(row, dict)]
    if not items:
        return text

    sections: list[str] = [(text or "").strip()]
    for index, item in enumerate(items, start=1):
        name = str(item.get("name") or f"attachment-{index}")
        path = str(item.get("path") or "")
        mime = str(item.get("type") or "")
        if not path:
            continue
        extracted = _clip(extract_uploaded_file_content(path, mime=mime))
        header = f"--- Attachment {index}: {name} ---"
        if extracted:
            sections.append(f"{header}\n{extracted}")
        else:
            sections.append(f"{header}\n(no extractable text; path: {path})")

    return "\n\n".join(part for part in sections if part).strip()
