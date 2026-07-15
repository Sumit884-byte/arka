from arka.agent import vision_evidence
from arka.routing.symbolic import route_vision_evidence


def test_combines_ocr_and_model(monkeypatch, tmp_path):
    image = tmp_path / "screen.png"
    image.write_bytes(b"x")
    monkeypatch.setattr(vision_evidence, "ocr", lambda _: "Price: $10")
    monkeypatch.setattr("arka.llm.cli.llm_complete", lambda *a, **k: "Both sources agree")
    result = vision_evidence.answer(str(image), "What is the price?", model_view="It says $10")
    assert result["ocr"] == "Price: $10"
    assert result["answer"] == "Both sources agree"


def test_vision_route():
    assert route_vision_evidence("compare OCR and vllm for screen.png and answer")
