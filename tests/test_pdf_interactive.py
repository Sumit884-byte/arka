from arka.agent.pdf_interactive import convert
from arka.routing.symbolic import route_pdf_interactive


def test_convert_pdf(tmp_path):
    pdf = tmp_path / "guide.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    output = convert(str(pdf))
    assert output.is_file()
    assert "pdf.js" in output.read_text()


def test_route_pdf_interactive():
    assert route_pdf_interactive("turn guide.pdf into an interactive website") == "pdf_interactive guide.pdf"


def test_ultra_mode(tmp_path):
    pdf = tmp_path / "guide.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    text = convert(str(pdf), ultra=True).read_text()
    assert "model-viewer" in text and "auto-rotate" in text
