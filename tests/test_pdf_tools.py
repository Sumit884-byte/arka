"""Tests for pdf_tools — NL parsing and core PDF operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from arka.pdf.tools import (
    add_page_numbers,
    add_watermark,
    compare_pdfs,
    compress_pdf,
    create_pdf,
    edit_pdf,
    extract_pages,
    images_to_pdf,
    main,
    merge_pdfs,
    nl_to_argv,
    protect_pdf,
    rearrange_pages,
    remove_pages,
    rotate_pdf,
    split_pdf,
    unlock_pdf,
    web_optimize_pdf,
)


def _make_pdf(path: Path, *, pages: int = 2, text: str = "Hello") -> Path:
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    writer = PdfWriter()
    for i in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def _make_text_pdf(path: Path, text: str = "Page one content") -> Path:
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    c.drawString(72, 720, text)
    c.showPage()
    c.drawString(72, 720, "Page two different")
    c.save()
    return path


def test_nl_to_argv_merge():
    argv = nl_to_argv("merge a.pdf and b.pdf into one")
    assert argv == ["merge", "a.pdf", "b.pdf"]


def test_nl_to_argv_compress():
    argv = nl_to_argv("compress report.pdf")
    assert argv == ["compress", "report.pdf"]


def test_nl_to_argv_pdf_to_images():
    argv = nl_to_argv("pdf to images scan.pdf")
    assert argv == ["pdf-to-images", "scan.pdf"]


def test_nl_to_argv_protect():
    argv = nl_to_argv("protect pdf report.pdf with password secret123")
    assert argv == ["protect", "report.pdf", "--password", "secret123"]


def test_nl_to_argv_unlock():
    argv = nl_to_argv("unlock pdf locked.pdf password mypass")
    assert argv == ["unlock", "locked.pdf", "--password", "mypass"]


def test_nl_to_argv_ocr():
    argv = nl_to_argv("ocr scanned.pdf make searchable")
    assert argv == ["ocr", "scanned.pdf"]


def test_nl_to_argv_create():
    argv = nl_to_argv("create blank pdf text Hello world")
    assert argv == ["create", "--text", "Hello world"]


def test_nl_to_argv_ignores_unrelated():
    assert nl_to_argv("what is the weather today") == []


def test_merge_pdfs(tmp_path: Path):
    pytest.importorskip("pypdf")
    a = _make_pdf(tmp_path / "a.pdf")
    b = _make_pdf(tmp_path / "b.pdf", pages=1)
    out = tmp_path / "merged.pdf"
    merge_pdfs([a, b], out)
    assert out.is_file()
    from pypdf import PdfReader

    assert len(PdfReader(str(out)).pages) == 3


def test_split_pdf(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf", pages=3)
    out_dir = tmp_path / "parts"
    saved = split_pdf(src, out_dir, pages_per_file=1)
    assert len(saved) == 3
    for p in saved:
        assert p.is_file()


def test_compress_pdf(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf")
    out = tmp_path / "out.pdf"
    compress_pdf(src, out)
    assert out.is_file()
    assert out.stat().st_size > 0


def test_protect_and_unlock(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf")
    locked = tmp_path / "locked.pdf"
    protect_pdf(src, locked, password="secret")
    assert locked.is_file()
    unlocked = tmp_path / "unlocked.pdf"
    unlock_pdf(locked, unlocked, password="secret")
    from pypdf import PdfReader

    reader = PdfReader(str(unlocked))
    assert not reader.is_encrypted


def test_rotate_pdf(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf", pages=1)
    out = tmp_path / "rotated.pdf"
    rotate_pdf(src, out, degrees=90)
    assert out.is_file()


def test_remove_and_extract_pages(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf", pages=4)
    trimmed = tmp_path / "trimmed.pdf"
    remove_pages(src, trimmed, pages="2,4")
    from pypdf import PdfReader

    assert len(PdfReader(str(trimmed)).pages) == 2
    extracted = tmp_path / "extracted.pdf"
    extract_pages(src, extracted, pages="1,3")
    assert len(PdfReader(str(extracted)).pages) == 2


def test_rearrange_pages(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf", pages=3)
    out = tmp_path / "reordered.pdf"
    rearrange_pages(src, out, order="3,1,2")
    from pypdf import PdfReader

    assert len(PdfReader(str(out)).pages) == 3


def test_edit_pdf(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf", pages=1)
    out = tmp_path / "edited.pdf"
    edit_pdf(src, out, text="Approved")
    assert out.is_file()


def test_create_pdf(tmp_path: Path):
    pytest.importorskip("reportlab")
    out = tmp_path / "created.pdf"
    create_pdf(out, text="Test document", pages=2)
    assert out.is_file()
    from pypdf import PdfReader

    assert len(PdfReader(str(out)).pages) == 2


def test_watermark_and_page_numbers(tmp_path: Path):
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")
    src = _make_pdf(tmp_path / "src.pdf", pages=2)
    wm = tmp_path / "wm.pdf"
    add_watermark(src, wm, text="DRAFT")
    assert wm.is_file()
    num = tmp_path / "num.pdf"
    add_page_numbers(src, num)
    assert num.is_file()


def test_images_to_pdf(tmp_path: Path):
    pytest.importorskip("PIL")
    pytest.importorskip("pypdf")
    from PIL import Image

    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    Image.new("RGB", (100, 100), color="red").save(img1)
    Image.new("RGB", (100, 100), color="blue").save(img2)
    out = tmp_path / "album.pdf"
    images_to_pdf([img1, img2], out)
    assert out.is_file()
    from pypdf import PdfReader

    assert len(PdfReader(str(out)).pages) == 2


def test_compare_pdfs(tmp_path: Path):
    pytest.importorskip("reportlab")
    a = _make_text_pdf(tmp_path / "a.pdf", text="Same content")
    b = _make_text_pdf(tmp_path / "b.pdf", text="Different content")
    result = compare_pdfs(a, b)
    assert result["identical_text"] is False
    assert result["text_diff_pages"]


def test_web_optimize_pdf(tmp_path: Path):
    pytest.importorskip("pypdf")
    src = _make_pdf(tmp_path / "src.pdf")
    out = tmp_path / "web.pdf"
    web_optimize_pdf(src, out)
    assert out.is_file()


def test_pdf_to_images(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    _ = fitz
    from arka.pdf.tools import pdf_to_images

    src = _make_pdf(tmp_path / "src.pdf", pages=2)
    out_dir = tmp_path / "images"
    saved = pdf_to_images(src, out_dir, fmt="png", dpi=72)
    assert len(saved) == 2
    for p in saved:
        assert p.suffix == ".png"


def test_extract_pdf_images(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("PIL")
    from PIL import Image
    from arka.pdf.tools import extract_pdf_images

    img_path = tmp_path / "embed.png"
    Image.new("RGB", (50, 50), color="green").save(img_path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(10, 10, 60, 60), filename=str(img_path))
    pdf_path = tmp_path / "with_img.pdf"
    doc.save(str(pdf_path))
    doc.close()
    out_dir = tmp_path / "extracted"
    saved = extract_pdf_images(pdf_path, out_dir)
    assert len(saved) >= 1


def test_overlay_pdfs(tmp_path: Path):
    pytest.importorskip("pypdf")
    from arka.pdf.tools import overlay_pdfs

    base = _make_pdf(tmp_path / "base.pdf", pages=1)
    over = _make_pdf(tmp_path / "over.pdf", pages=1)
    out = tmp_path / "overlay.pdf"
    overlay_pdfs(base, over, out)
    assert out.is_file()


def test_redact_pdf(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    _ = fitz
    from arka.pdf.tools import redact_pdf

    src = _make_text_pdf(tmp_path / "secret.pdf", text="CONFIDENTIAL DATA here")
    out = tmp_path / "redacted.pdf"
    redact_pdf(src, out, text="CONFIDENTIAL")
    assert out.is_file()


def test_sign_pdf(tmp_path: Path):
    pytest.importorskip("pypdf")
    pytest.importorskip("PIL")
    pytest.importorskip("reportlab")
    from PIL import Image
    from arka.pdf.tools import sign_pdf

    src = _make_pdf(tmp_path / "doc.pdf", pages=1)
    sig = tmp_path / "sig.png"
    Image.new("RGBA", (100, 40), color=(0, 0, 0, 0)).save(sig)
    out = tmp_path / "signed.pdf"
    sign_pdf(src, out, signature_image=sig)
    assert out.is_file()


def test_main_sign_with_image_still_works(tmp_path: Path, capsys):
    pytest.importorskip("pypdf")
    pytest.importorskip("PIL")
    pytest.importorskip("reportlab")
    from PIL import Image

    src = _make_pdf(tmp_path / "doc.pdf", pages=1)
    sig = tmp_path / "sig.png"
    Image.new("RGBA", (100, 40), color=(0, 0, 0, 0)).save(sig)
    out = tmp_path / "signed.pdf"
    code = main(["sign", str(src), "--image", str(sig), "-o", str(out)])
    assert code == 0
    assert out.is_file()
    assert "Saved:" in capsys.readouterr().out


def test_main_check_lists_operations(capsys):
    code = main(["check"])
    out = capsys.readouterr().out
    assert code in {0, 1}
    assert "Operations:" in out
    assert "edit" in out
    assert "merge" in out
    assert "Backends:" in out
