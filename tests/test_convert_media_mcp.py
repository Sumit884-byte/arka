"""Tests for arka_convert_media MCP handler."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from arka.integrations.mcp_server import _handle_arka_convert_media
from arka.media.convert_media import capabilities_catalog, media_info


def _png_bytes(width: int = 8, height: int = 8) -> bytes:
    raw = b"".join(b"\x00" + bytes([255, 0, 0]) * width for _ in range(height))
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


def test_capabilities_catalog():
    caps = capabilities_catalog()
    assert "image" in caps
    assert "webp" in caps["image"]["outputs"]
    assert "all" in caps["special"]


def test_media_info_image(tmp_path: Path):
    src = tmp_path / "photo.png"
    src.write_bytes(_png_bytes())
    info = media_info(src)
    assert info["media_type"] == "image"
    assert "webp" in info["output_formats"]


def test_mcp_detect(tmp_path: Path):
    src = tmp_path / "photo.png"
    src.write_bytes(_png_bytes())
    out = json.loads(_handle_arka_convert_media({"action": "detect", "path": str(src)}))
    assert out["media_type"] == "image"


def test_mcp_formats(tmp_path: Path):
    src = tmp_path / "photo.png"
    src.write_bytes(_png_bytes())
    out = json.loads(_handle_arka_convert_media({"action": "formats", "path": str(src)}))
    assert "jpg" in out["formats"]


def test_mcp_convert_single(tmp_path: Path):
    src = tmp_path / "photo.png"
    src.write_bytes(_png_bytes())
    out = json.loads(
        _handle_arka_convert_media(
            {"action": "convert", "path": str(src), "to": "webp", "output": str(tmp_path / "out.webp")}
        )
    )
    assert out["count"] == 1
    assert Path(out["outputs"][0]).is_file()


def test_mcp_convert_all(tmp_path: Path):
    src = tmp_path / "photo.png"
    src.write_bytes(_png_bytes())
    out = json.loads(_handle_arka_convert_media({"action": "convert", "path": str(src), "to": "all"}))
    assert out["count"] == len(out["target_formats"])
    assert all(Path(p).is_file() for p in out["outputs"])


def test_mcp_parse():
    out = json.loads(_handle_arka_convert_media({"action": "parse", "text": "convert clip.mp4 to gif"}))
    assert out["argv"] == ["clip.mp4", "--to", "gif"]


def test_mcp_capabilities():
    out = json.loads(_handle_arka_convert_media({"action": "capabilities"}))
    assert "video" in out
