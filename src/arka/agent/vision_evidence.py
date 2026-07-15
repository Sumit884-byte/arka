"""Combine OCR evidence with a model interpretation for grounded answers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def ocr(path: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(Path(path).expanduser())).strip()
    except ImportError as exc:
        raise RuntimeError("OCR requires pytesseract and Pillow") from exc


def answer(path: str, question: str, *, model_view: str = "") -> dict[str, str]:
    extracted = ocr(path)
    if not model_view:
        model_view = "Visual model unavailable; rely on OCR and image metadata."
    prompt = (
        f"Question: {question}\nOCR evidence:\n{extracted[:12000]}\n"
        f"Visual model interpretation:\n{model_view[:12000]}\n"
        "Compare both sources. State agreements, conflicts, and uncertainty, then give a grounded answer. Do not invent text absent from evidence."
    )
    try:
        from arka.llm.cli import llm_complete
        combined = llm_complete("You are a careful multimodal evidence reviewer.", prompt, task="vision_evidence", skill="vision_evidence")
    except Exception as exc:
        combined = f"AI synthesis unavailable: {exc}"
    return {"ocr": extracted, "model": model_view, "answer": combined.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka vision-evidence")
    parser.add_argument("image")
    parser.add_argument("question")
    parser.add_argument("--model-view", default="", help="Optional vLLM/vision model interpretation")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = answer(args.image, args.question, model_view=args.model_view)
    except (OSError, RuntimeError) as exc:
        print(f"vision-evidence: {exc}")
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("OCR says:\n" + result["ocr"] + "\n\nModel says:\n" + result["model"] + "\n\nCombined answer:\n" + result["answer"])
    return 0
