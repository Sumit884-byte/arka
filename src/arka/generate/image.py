#!/usr/bin/env python3
"""Generate images via Google Nano Banana (Gemini) or Pollinations nanobanana proxy."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ALLOWED_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
# Nano Banana family — same API as Google AI Studio / agno NanoBananaTools
NANO_BANANA_MODELS = (
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-image-preview",
    "gemini-2.0-flash-preview-image-generation",
)
DEFAULT_MODEL = "gemini-2.5-flash-image"
ASPECT_SIZES = {
    "1:1": (1024, 1024),
    "2:3": (768, 1152),
    "3:2": (1152, 768),
    "3:4": (768, 1024),
    "4:3": (1024, 768),
    "4:5": (832, 1040),
    "5:4": (1040, 832),
    "9:16": (576, 1024),
    "16:9": (1024, 576),
    "21:9": (1344, 576),
}


def _api_key() -> str:
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _pollinations_key() -> str:
    for name in ("POLLINATIONS_API_KEY", "POLLINATIONS_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _backend() -> str:
    return os.environ.get("ARKA_IMAGE_BACKEND", "auto").strip().lower() or "auto"


def _fallback_enabled() -> bool:
    return os.environ.get("ARKA_IMAGE_FALLBACK", "1") not in ("0", "false", "no")


def _nano_banana_models(requested: str) -> list[str]:
    """Model try-order: explicit -m flag first, then env, then Nano Banana defaults."""
    models: list[str] = []
    if requested:
        models.append(requested)
    env_model = os.environ.get("ARKA_IMAGE_MODEL", "").strip()
    if env_model and env_model not in models:
        models.append(env_model)
    for m in NANO_BANANA_MODELS:
        if m not in models:
            models.append(m)
    return models


def _default_output(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "image"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path.home() / "Pictures" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.png"


def _quota_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "limit: 0" in text


def _friendly_gemini_error(exc: Exception) -> str:
    text = str(exc)
    if _quota_error(exc):
        return (
            "Nano Banana (Gemini image) quota is 0 on this API key.\n"
            "  • AI Studio website free use ≠ API quota — same key needs billing for API\n"
            "  • Enable billing: https://aistudio.google.com/\n"
            "  • Or set POLLINATIONS_API_KEY and use model nanobanana via Pollinations\n"
            "  • Free generic fallback: ARKA_IMAGE_BACKEND=pollinations (flux, not Nano Banana)"
        )
    if "403" in text or "PERMISSION_DENIED" in text:
        return "Gemini API key lacks Nano Banana image permission."
    if "401" in text or "API key not valid" in text:
        return "Invalid GEMINI_API_KEY — check ~/.config/fish/.env"
    return f"Nano Banana error: {text[:240]}"


def _save_inline_image(output: Path, data: bytes, mime: str) -> Path:
    ext = ".png" if "png" in mime.lower() else ".jpg"
    out = output
    if out.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        out = out.with_suffix(ext)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def generate_nano_banana(prompt: str, output: Path, aspect: str, models: list[str]) -> tuple[Path, str]:
    """Official Google Nano Banana — same SDK as AI Studio API tab, not website scraping."""
    from google import genai
    from google.genai import types

    key = _api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=key)
    cfg = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=aspect),
    )
    last_exc: Exception | None = None
    for model in models:
        try:
            print(f"  Nano Banana ({model}) …", file=sys.stderr)
            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config=cfg,
            )
            if not getattr(response, "candidates", None):
                raise RuntimeError("No image returned")

            for candidate in response.candidates:
                content = getattr(candidate, "content", None)
                if not content or not getattr(content, "parts", None):
                    continue
                for part in content.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        mime = getattr(inline, "mime_type", "image/png") or "image/png"
                        return _save_inline_image(output, inline.data, mime), f"nano-banana/{model}"

            raise RuntimeError("Response had no image data")
        except Exception as exc:
            last_exc = exc
            if _quota_error(exc):
                print(f"  ⚠ {model}: quota exhausted, trying next …", file=sys.stderr)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("No Nano Banana models available")


def _download_url(url: str, headers: dict[str, str] | None = None, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "arka-generate-image/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError("Empty response")
    if data[:1] == b"{":
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
            msg = payload.get("error") or payload.get("message") or payload
            raise RuntimeError(str(msg))
        except json.JSONDecodeError:
            pass
    return data


def generate_pollinations(
    prompt: str, output: Path, aspect: str, model: str = "flux"
) -> tuple[Path, str]:
    width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["1:1"])
    encoded = urllib.parse.quote(prompt)
    key = _pollinations_key()

    if key and model in {"nanobanana", "nanobanana-pro", "gptimage", "zimage", "seedream5"}:
        params = urllib.parse.urlencode({"model": model, "width": width, "height": height, "nologo": "true"})
        url = f"https://gen.pollinations.ai/image/{encoded}?{params}"
        headers = {"Authorization": f"Bearer {key}", "User-Agent": "arka-generate-image/1.0"}
        print(f"  Pollinations ({model}, Google Nano Banana proxy) …", file=sys.stderr)
        data = _download_url(url, headers=headers)
        label = f"pollinations/{model}"
    else:
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true"
        print(f"  Pollinations (flux, free) …", file=sys.stderr)
        data = _download_url(url)
        label = "pollinations/flux"

    out = output
    if out.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        out = out.with_suffix(".jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out, label


def generate(
    prompt: str,
    output: Path,
    aspect: str,
    model: str,
) -> tuple[Path, str]:
    backend = _backend()
    models = _nano_banana_models(model)
    poll_model = os.environ.get("ARKA_IMAGE_POLLINATIONS_MODEL", "nanobanana").strip() or "nanobanana"

    if backend == "pollinations":
        return generate_pollinations(prompt, output, aspect, poll_model)

    if backend == "nano-banana":
        return generate_nano_banana(prompt, output, aspect, models)

    if backend == "gemini":
        return generate_nano_banana(prompt, output, aspect, models)

    # auto: Nano Banana API → Pollinations nanobanana (if key) → free flux
    if _api_key():
        try:
            return generate_nano_banana(prompt, output, aspect, models)
        except Exception as exc:
            print(f"⚠ {_friendly_gemini_error(exc)}", file=sys.stderr)

    if _pollinations_key():
        try:
            return generate_pollinations(prompt, output, aspect, poll_model)
        except Exception as exc:
            print(f"⚠ Pollinations nanobanana failed: {exc}", file=sys.stderr)

    if not _fallback_enabled():
        raise SystemExit(_friendly_gemini_error(RuntimeError("quota")))

    print("→ Falling back to Pollinations flux (free, not Nano Banana) …", file=sys.stderr)
    return generate_pollinations(prompt, output, aspect, "flux")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate images with Google Nano Banana (Gemini) or Pollinations"
    )
    parser.add_argument("prompt", help="Image description")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("-a", "--aspect", default="1:1", help="Aspect ratio")
    parser.add_argument(
        "-m",
        "--model",
        default="",
        help=f"Nano Banana model (default: try {', '.join(NANO_BANANA_MODELS[:3])}…)",
    )
    args = parser.parse_args()

    aspect = args.aspect
    if aspect not in ALLOWED_RATIOS:
        print(f"Invalid aspect '{aspect}'. Choose: {', '.join(sorted(ALLOWED_RATIOS))}", file=sys.stderr)
        return 1

    out = Path(args.output) if args.output else _default_output(args.prompt)
    print(f"Generating ({aspect}) …")
    try:
        saved, provider = generate(args.prompt, out, aspect, args.model)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(_friendly_gemini_error(exc), file=sys.stderr)
        return 1

    print(f"Saved ({provider}): {saved}")
    if os.environ.get("ARKA_OPEN_IMAGE", "1") not in ("0", "false"):
        try:
            import subprocess

            subprocess.Popen(["xdg-open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
