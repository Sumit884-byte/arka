"""Smart image reframing — detect bad avatar/profile crops and fix or suggest CSS."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
CLI_HEADS = frozenset(
    {
        "reposition_image",
        "reposition-image",
        "fix_image_crop",
        "fix-image-crop",
        "smart_image_frame",
        "smart-image-frame",
    }
)

VISION_FRAMING_PROMPT = (
    "This image may be used as a circular profile avatar with object-fit: cover. "
    "Is the subject poorly cropped (head, face, or chin cut off)? "
    "Reply with JSON only: "
    '{"poorly_cropped": bool, "issues": [str], "object_position_x_pct": number, '
    '"object_position_y_pct": number, "notes": str}. '
    "Use object_position_y_pct below 35 when the top of the head is clipped; "
    "above 55 when too much forehead shows."
)


@dataclass(frozen=True)
class SubjectRegion:
    x: float
    y: float
    w: float
    h: float
    source: str


@dataclass
class FramingAnalysis:
    path: str
    width: int
    height: int
    subject: SubjectRegion
    issues: list[str] = field(default_factory=list)
    severity: str = "ok"
    head_cutoff_top: bool = False
    head_cutoff_bottom: bool = False
    side_cutoff: bool = False
    object_position_x_pct: float = 50.0
    object_position_y_pct: float = 50.0
    detection: str = ""
    vision_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["subject"] = asdict(self.subject)
        return payload


def _require_pillow():
    try:
        from PIL import Image

        return Image
    except ImportError as exc:
        raise RuntimeError("reposition_image requires Pillow: pip install Pillow") from exc


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _detect_faces_mediapipe(image) -> list[tuple[int, int, int, int]]:
    try:
        import mediapipe as mp
        import numpy as np
    except ImportError:
        return []
    try:
        rgb = np.array(image.convert("RGB"))
        h, w = rgb.shape[:2]
        with mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.4) as detector:
            result = detector.process(rgb)
        if not result.detections:
            return []
        boxes: list[tuple[int, int, int, int]] = []
        for det in result.detections:
            box = det.location_data.relative_bounding_box
            x0 = max(0, int(box.xmin * w))
            y0 = max(0, int(box.ymin * h))
            bw = max(1, int(box.width * w))
            bh = max(1, int(box.height * h))
            boxes.append((x0, y0, bw, bh))
        return boxes
    except (AttributeError, OSError, RuntimeError, ValueError):
        return []


def _detect_faces_opencv(image) -> list[tuple[int, int, int, int]]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    try:
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return []
        faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(24, 24))
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]
    except (AttributeError, OSError, RuntimeError, ValueError):
        return []


def _detect_subject_mass(image) -> tuple[int, int, int, int]:
    _require_pillow()
    gray = image.convert("L")
    w, h = gray.size
    pixels = gray.load()
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            v = pixels[x, y]
            if 24 < v < 232:
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if not found:
        return (0, 0, w, h)
    pad_x = int((max_x - min_x) * 0.05) + 2
    pad_y = int((max_y - min_y) * 0.05) + 2
    return (
        max(0, min_x - pad_x),
        max(0, min_y - pad_y),
        min(w, max_x + pad_x),
        min(h, max_y + pad_y),
    )


def detect_subject(image, *, width: int | None = None, height: int | None = None) -> SubjectRegion:
    Image = _require_pillow()
    if not isinstance(image, Image.Image):
        image = Image.open(image).convert("RGB")
    w, h = image.size
    width = width or w
    height = height or h

    boxes = _detect_faces_mediapipe(image)
    source = "mediapipe"
    if not boxes:
        boxes = _detect_faces_opencv(image)
        source = "opencv"
    if boxes:
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[0] + b[2] for b in boxes)
        y1 = max(b[1] + b[3] for b in boxes)
        return SubjectRegion(x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h, source)

    x0, y0, x1, y1 = _detect_subject_mass(image)
    return SubjectRegion(x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h, "mass")


def _simulate_circle_cutoff(subject: SubjectRegion, shape: str) -> tuple[bool, bool, bool]:
    subj_top = subject.y
    subj_bottom = subject.y + subject.h
    subj_left = subject.x
    subj_right = subject.x + subject.w
    head_cutoff_top = subj_top < (0.12 if shape == "circle" else 0.08)
    head_cutoff_bottom = subj_bottom > 0.96
    side_cutoff = subj_left < 0.05 or subj_right > 0.95
    if shape == "circle":
        # Circular avatars behave like square cover crops; high subjects lose forehead faster.
        head_cutoff_top = head_cutoff_top or subj_top < 0.18
    return head_cutoff_top, head_cutoff_bottom, side_cutoff


def _compute_object_position(subject: SubjectRegion, *, shape: str = "square") -> tuple[float, float]:
    cx = (subject.x + subject.w / 2) * 100.0
    cy = (subject.y + subject.h / 2) * 100.0
    top = subject.y * 100.0
    head_cutoff_top, _, _ = _simulate_circle_cutoff(subject, shape)

    if head_cutoff_top:
        # Anchor higher in the image (lower y%) to reveal forehead in cover crops.
        cy = max(12.0, min(40.0, top + subject.h * 100.0 * 0.45))
    elif shape == "circle":
        cy = max(30.0, min(55.0, top + subject.h * 100.0 * 0.55))
    else:
        cy = max(20.0, min(70.0, cy))

    cx = max(8.0, min(92.0, cx))
    return round(cx, 1), round(cy, 1)


def analyze_framing(path: str | Path, *, shape: str = "square", vision: bool = False) -> FramingAnalysis:
    Image = _require_pillow()
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"image not found: {src}")
    image = Image.open(src).convert("RGB")
    w, h = image.size
    subject = detect_subject(image, width=w, height=h)
    head_cutoff_top, head_cutoff_bottom, side_cutoff = _simulate_circle_cutoff(subject, shape)
    pos_x, pos_y = _compute_object_position(subject, shape=shape)

    issues: list[str] = []
    if head_cutoff_top:
        issues.append("Top of head likely clipped in cover/circle crop")
    if head_cutoff_bottom:
        issues.append("Chin or lower face may be clipped")
    if side_cutoff:
        issues.append("Subject too close to left/right edge")

    severity = "ok"
    if head_cutoff_top or head_cutoff_bottom:
        severity = "bad"
    elif side_cutoff:
        severity = "minor"

    analysis = FramingAnalysis(
        path=str(src.resolve()),
        width=w,
        height=h,
        subject=subject,
        issues=issues,
        severity=severity,
        head_cutoff_top=head_cutoff_top,
        head_cutoff_bottom=head_cutoff_bottom,
        side_cutoff=side_cutoff,
        object_position_x_pct=pos_x,
        object_position_y_pct=pos_y,
        detection=subject.source,
    )

    if vision:
        hint = _vision_framing_hint(str(src))
        if hint:
            analysis.vision_notes = hint.get("notes", "")
            if hint.get("poorly_cropped") and severity == "ok":
                analysis.severity = "minor"
            if "object_position_x_pct" in hint:
                analysis.object_position_x_pct = float(hint["object_position_x_pct"])
            if "object_position_y_pct" in hint:
                analysis.object_position_y_pct = float(hint["object_position_y_pct"])
            for issue in hint.get("issues") or []:
                if issue and issue not in analysis.issues:
                    analysis.issues.append(str(issue))
    return analysis


def _vision_framing_hint(path: str) -> dict[str, Any] | None:
    try:
        from arka.vision.describe import describe_source
    except ImportError:
        return None
    try:
        raw = describe_source(path, prompt=VISION_FRAMING_PROMPT)
    except (SystemExit, RuntimeError, OSError, ValueError):
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def css_for_image(path: str | Path, *, shape: str = "circle", selector: str = ".avatar img") -> dict[str, str]:
    analysis = analyze_framing(path, shape=shape)
    pos = f"center {analysis.object_position_y_pct:g}%"
    if abs(analysis.object_position_x_pct - 50.0) > 2.0:
        pos = f"{analysis.object_position_x_pct:g}% {analysis.object_position_y_pct:g}%"
    rules = {
        "object-fit": "cover",
        "object-position": pos,
    }
    if shape == "circle":
        rules["border-radius"] = "50%"
        rules["aspect-ratio"] = "1 / 1"
    css = f"{selector} {{\n"
    for key, value in rules.items():
        css += f"  {key}: {value};\n"
    css += "}"
    return {
        "selector": selector,
        "css": css,
        "object_position": pos,
        "analysis": json.dumps(analysis.to_dict(), indent=2),
    }


def _pad_canvas(image, *, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0, fill=(255, 255, 255)):
    Image = _require_pillow()
    w, h = image.size
    canvas = Image.new("RGB", (w + left + right, h + top + bottom), fill)
    canvas.paste(image, (left, top))
    return canvas


def fix_image(
    path: str | Path,
    output: str | Path,
    *,
    shape: str = "square",
    size: int | None = None,
) -> dict[str, Any]:
    Image = _require_pillow()
    src = Path(path)
    out = Path(output)
    image = Image.open(src).convert("RGB")
    w, h = image.size
    subject = detect_subject(image)
    crop_size = min(w, h)

    face_cx = (subject.x + subject.w / 2) * w
    (subject.y + subject.h / 2) * h
    face_h = max(1.0, subject.h * h)
    head_top = subject.y * h

    desired_top = head_top - face_h * 0.35
    desired_left = face_cx - crop_size / 2

    pad_left = max(0, int(-desired_left))
    pad_top = max(0, int(-desired_top))
    pad_right = max(0, int(desired_left + crop_size - w))
    pad_bottom = max(0, int(desired_top + crop_size - h))

    if any((pad_left, pad_top, pad_right, pad_bottom)):
        image = _pad_canvas(image, left=pad_left, top=pad_top, right=pad_right, bottom=pad_bottom)
        w, h = image.size
        face_cx += pad_left
        head_top += pad_top
        desired_top = head_top - face_h * 0.35
        desired_left = face_cx - crop_size / 2

    left = int(max(0, min(w - crop_size, desired_left)))
    top = int(max(0, min(h - crop_size, desired_top)))
    cropped = image.crop((left, top, left + crop_size, top + crop_size))

    if size and size > 0:
        cropped = cropped.resize((size, size), Image.Resampling.LANCZOS)

    out.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(out)
    after = analyze_framing(out, shape=shape)
    return {
        "input": str(src.resolve()),
        "output": str(out.resolve()),
        "shape": shape,
        "size": size or crop_size,
        "before_severity": analyze_framing(src, shape=shape).severity,
        "after_severity": after.severity,
        "object_position": f"center {after.object_position_y_pct:g}%",
        "detection": subject.source,
    }


def batch_fix(
    folder: str | Path,
    *,
    output_dir: str | Path | None = None,
    shape: str = "square",
    size: int | None = None,
) -> list[dict[str, Any]]:
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    dest = Path(output_dir) if output_dir else root / "fixed"
    dest.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or not _is_image(path):
            continue
        out = dest / path.name
        results.append(fix_image(path, out, shape=shape, size=size))
    return results


def _read_context_css(context_path: str | Path | None) -> str:
    if not context_path:
        return ""
    path = Path(context_path)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def fix_ui(
    screenshot: str | Path,
    *,
    context: str | Path | None = None,
    shape: str = "circle",
    selector: str = ".avatar img",
    vision: bool = True,
) -> dict[str, Any]:
    analysis = analyze_framing(screenshot, shape=shape, vision=vision)
    css_payload = css_for_image(screenshot, shape=shape, selector=selector)
    context_text = _read_context_css(context)
    context_hint = ""
    if context_text:
        if "object-position" in context_text:
            context_hint = "Existing object-position found in context — compare with suggested value."
        if re.search(r"border-radius\s*:\s*50%", context_text):
            context_hint = (context_hint + " Context uses circular avatar styling.").strip()

    return {
        "screenshot": str(Path(screenshot).resolve()),
        "context": str(Path(context).resolve()) if context else None,
        "severity": analysis.severity,
        "issues": analysis.issues,
        "css": css_payload["css"],
        "object_position": css_payload["object_position"],
        "context_hint": context_hint,
        "analysis": analysis.to_dict(),
    }


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if not re.search(
        r"(?i)\b(?:reposition(?:\s+|-)image|fix(?:\s+|-)?image(?:\s+|-)?crop|smart(?:\s+|-)?image(?:\s+|-)?frame|"
        r"reposition avatar|center face in image|fix profile picture cropping|fix avatar crop|fix image crop)\b",
        t,
    ):
        return []

    argv: list[str] = []
    if re.search(r"(?i)\bbatch\b", t):
        argv.append("batch")
    elif re.search(r"(?i)\b(?:css|object-position|object position)\b", t):
        argv.append("css")
    elif re.search(r"(?i)\b(?:fix-ui|fix ui|screenshot)\b", t):
        argv.append("fix-ui")
    elif re.search(r"(?i)\b(?:fix|reframe|repair)\b", t):
        argv.append("fix")
    else:
        argv.append("check")

    quoted = re.findall(r"""['"]([^'"]+\.(?:png|jpe?g|webp|gif|bmp|tiff?))['"]""", t, flags=re.I)
    paths = quoted or re.findall(r"\S+\.(?:png|jpe?g|webp|gif|bmp|tiff?)\b", t, flags=re.I)
    if paths:
        argv.append(paths[0])

    if re.search(r"(?i)\bcircle|circular|avatar|profile\b", t):
        argv.extend(["--shape", "circle"])

    folder = re.search(r"(?i)\b(?:folder|directory)\s+['\"]?([^\s'\"]+)", t)
    if folder and "batch" in argv:
        argv.append(folder.group(1))

    return argv


def reposition_image_result(
    action: str,
    path: str | Path | None = None,
    *,
    output: str | Path | None = None,
    shape: str = "square",
    size: int | None = None,
    context: str | Path | None = None,
    selector: str = ".avatar img",
    vision: bool = False,
    folder: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    action = action.strip().lower()
    if action == "check":
        if not path:
            raise ValueError("path is required for check")
        return analyze_framing(path, shape=shape, vision=vision).to_dict()
    if action == "fix":
        if not path or not output:
            raise ValueError("path and output are required for fix")
        return fix_image(path, output, shape=shape, size=size)
    if action == "css":
        if not path:
            raise ValueError("path is required for css")
        return css_for_image(path, shape=shape, selector=selector)
    if action == "fix-ui":
        if not path:
            raise ValueError("path is required for fix-ui")
        return fix_ui(path, context=context, shape=shape, selector=selector, vision=vision)
    if action == "batch":
        if not folder and not path:
            raise ValueError("folder is required for batch")
        target = folder or path
        return {"results": batch_fix(target, output_dir=output_dir, shape=shape, size=size)}
    raise ValueError("action must be check, fix, css, fix-ui, or batch")


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(prog="arka reposition_image", description="Detect and fix bad image framing")
    sub = parser.add_subparsers(dest="command")

    check_p = sub.add_parser("check", help="Analyze framing issues")
    check_p.add_argument("image")
    check_p.add_argument("--shape", choices=["square", "circle"], default="square")
    check_p.add_argument("--vision", action="store_true")
    check_p.add_argument("--json", action="store_true")

    fix_p = sub.add_parser("fix", help="Reframe image with smart crop/padding")
    fix_p.add_argument("image")
    fix_p.add_argument("-o", "--output", required=True)
    fix_p.add_argument("--shape", choices=["square", "circle"], default="square")
    fix_p.add_argument("--size", type=int, default=0)
    fix_p.add_argument("--json", action="store_true")

    css_p = sub.add_parser("css", help="Emit CSS object-position for an image")
    css_p.add_argument("image")
    css_p.add_argument("--shape", choices=["square", "circle"], default="circle")
    css_p.add_argument("--selector", default=".avatar img")
    css_p.add_argument("--json", action="store_true")

    ui_p = sub.add_parser("fix-ui", help="Analyze screenshot/UI and suggest CSS")
    ui_p.add_argument("screenshot")
    ui_p.add_argument("--context", "-c", help="Component or stylesheet path")
    ui_p.add_argument("--shape", choices=["square", "circle"], default="circle")
    ui_p.add_argument("--selector", default=".avatar img")
    ui_p.add_argument("--vision", action="store_true")
    ui_p.add_argument("--json", action="store_true")

    batch_p = sub.add_parser("batch", help="Fix all images in a folder")
    batch_p.add_argument("folder")
    batch_p.add_argument("-o", "--output-dir")
    batch_p.add_argument("--shape", choices=["square", "circle"], default="square")
    batch_p.add_argument("--size", type=int, default=0)
    batch_p.add_argument("--json", action="store_true")

    args = parser.parse_args(raw)
    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "check":
            payload = analyze_framing(args.image, shape=args.shape, vision=args.vision).to_dict()
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                from arka.core.output_layout import info, list_items, result_box, section, success

                section("Image framing check")
                info(f"Image: {payload['path']}")
                info(f"Detection: {payload['detection']} ({payload['subject']['source']})")
                info(f"Severity: {payload['severity']}")
                if payload["issues"]:
                    list_items("Issues", payload["issues"])
                result_box(
                    "Suggested CSS",
                    f"object-fit: cover; object-position: center {payload['object_position_y_pct']:g}%;",
                )
                if payload["severity"] == "ok":
                    success("Framing looks acceptable")
            return 0

        if args.command == "fix":
            payload = fix_image(
                args.image,
                args.output,
                shape=args.shape,
                size=args.size or None,
            )
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                from arka.core.output_layout import push_to_viewer, success

                success(f"Saved reframed image → {payload['output']}")
                push_to_viewer(payload["output"], title="Reframed image")
            return 0

        if args.command == "css":
            payload = css_for_image(args.image, shape=args.shape, selector=args.selector)
            if args.json:
                print(json.dumps({k: v for k, v in payload.items() if k != "analysis"}, indent=2))
            else:
                print(payload["css"])
            return 0

        if args.command == "fix-ui":
            payload = fix_ui(
                args.screenshot,
                context=args.context,
                shape=args.shape,
                selector=args.selector,
                vision=args.vision or bool(os.environ.get("ARKA_REPOSITION_VISION")),
            )
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                from arka.core.output_layout import info, list_items, result_box, section

                section("UI crop fix")
                if payload["issues"]:
                    list_items("Issues", payload["issues"])
                info(payload.get("context_hint") or "")
                result_box("CSS", payload["css"])
            return 0

        if args.command == "batch":
            results = batch_fix(
                args.folder,
                output_dir=args.output_dir,
                shape=args.shape,
                size=args.size or None,
            )
            payload = {"count": len(results), "results": results}
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                from arka.core.output_layout import success

                success(f"Reframed {len(results)} image(s)")
            return 0
    except (FileNotFoundError, NotADirectoryError, ValueError, RuntimeError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}))
        else:
            from arka.core.output_layout import error

            error(str(exc))
        return 1
    return 0
