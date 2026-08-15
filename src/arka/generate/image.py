#!/usr/bin/env python3
"""Generate images via Google Nano Banana (Gemini) or Pollinations nanobanana proxy."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
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
    return os.environ.get("IMAGE_BACKEND", "auto").strip().lower() or "auto"


def _fallback_enabled() -> bool:
    return os.environ.get("IMAGE_FALLBACK", "1") not in ("0", "false", "no")


def _nano_banana_models(requested: str) -> list[str]:
    """Model try-order: explicit -m flag first, then env, then Nano Banana defaults."""
    models: list[str] = []
    if requested:
        models.append(requested)
    env_model = os.environ.get("IMAGE_MODEL", "").strip()
    if env_model and env_model not in models:
        models.append(env_model)
    for m in NANO_BANANA_MODELS:
        if m not in models:
            models.append(m)
    return models


def _default_output(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "image"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("IMAGE_OUTPUT_DIR", "").strip()
    if env_dir:
        out_dir = Path(env_dir).expanduser()
    else:
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
        print("  Pollinations (flux, free) …", file=sys.stderr)
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
    poll_model = os.environ.get("IMAGE_POLLINATIONS_MODEL", "nanobanana").strip() or "nanobanana"

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


def _extract_image_prompt(text: str) -> str:
    return re.sub(
        r"(?i)^(?:generate|create|draw|paint|make|sketch|design|show)\s+"
        r"(?:me\s+)?(?:an?\s+)?"
        r"(?:image|picture|photo|drawing|painting|sketch|illustration|portrait|landscape|\bart\b)?\s*(?:of)?\s*",
        "",
        text.strip(),
    ).strip()


_SEARCH_RESEARCH_RE = re.compile(
    r"(?i)\b(?:"
    r"search(?:\s+for|\s+the\s+web\s+for)?|"
    r"look(?:ing)?\s+up|"
    r"find(?:\s+(?:info(?:rmation)?|photos?|pictures?|images?))?|"
    r"research|"
    r"tell\s+me\s+about|"
    r"what\s+(?:is|are)|"
    r"who\s+(?:is|are)|"
    r"learn\s+about|"
    r"get\s+(?:info(?:rmation)?|facts)\s+(?:on|about)|"
    r"list\s+(?:all\s+)?|"
    r"show\s+me\s+(?:info(?:rmation)?|facts|details|photos?|pictures?|real)|"
    r"build\s+(?:a\s+)?(?:website|site|page)|"
    r"make\s+(?:a\s+)?(?:website|site|page)|"
    r"write\s+(?:about|on)|"
    r"explain|describe|document"
    r")\b"
)

_CREATIVE_IMAGINARY_RE = re.compile(
    r"(?i)\b(?:"
    r"fictional|imaginary|fantasy|fantastical|sci[\s-]?fi|cyberpunk|"
    r"surreal|dreamlike|magical|mythical|dragon|unicorn|wizard|"
    r"cartoon|anime|illustration|artistic|stylized|concept\s+art|"
    r"futuristic|utopian|dystopian|otherworldly|made[\s-]?up|"
    r"ai[\s-]?(?:generated|art)|abstract"
    r")\b"
)

_REAL_WORLD_EXTRA_RE = re.compile(
    r"(?i)\b(?:"
    r"breed|breeds|species|native|indigenous|local|"
    r"dog|dogs|cat|cats|bird|birds|horse|horses|elephant|tiger|lion|"
    r"president|scientist|celebrity|"
    r"photograph|photo\s+of|picture\s+of|actual|historical|"
    r"landmark|monument|temple|church|mosque|museum|"
    r"animal|animals|wildlife|pet|pets|"
    r"mahal|breed|hound|sheepdog|pariah|rajapalayam|mudhol|chippiparai|kombai|gaddi"
    r")\b"
)

_NAMED_ENTITY_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")

_EXPLICIT_GENERATION_RE = re.compile(
    r"(?i)(?:^|\b)(?:generate|create|make|draw|paint|sketch|design)\s+(?:\w+\s+){0,4}"
    r"(?:image|picture|photo|art|drawing|sketch|painting|illustration|portrait|landscape)\b"
    r"|^show\s+(?:me\s+)?(?:an?\s+)?(?:ai[\s-])?(?:image|picture|photo|illustration|art)\b"
    r"|^(?:draw|paint|sketch)\s+"
)


def is_search_or_research_intent(text: str) -> bool:
    """True when the user is looking up facts or building content, not requesting AI art."""
    return bool(_SEARCH_RESEARCH_RE.search(text or ""))


def is_creative_or_imaginary_subject(prompt: str) -> bool:
    """True when the subject is clearly fictional or explicitly artistic."""
    return bool(_CREATIVE_IMAGINARY_RE.search(prompt or ""))


def is_real_world_subject(prompt: str, *, full_text: str = "") -> bool:
    """True when the prompt names real entities (people, places, breeds, etc.)."""
    combined = f"{full_text} {prompt}".strip()
    try:
        from arka.agent.three_js_model import symbolic_real_world_entity

        reality = symbolic_real_world_entity(combined)
        if reality is True:
            return True
        if reality is False:
            return False
    except ImportError:
        pass
    if _NAMED_ENTITY_RE.search(combined) and not is_creative_or_imaginary_subject(combined):
        return True
    return bool(_REAL_WORLD_EXTRA_RE.search(combined))


def should_generate_image(text: str) -> bool:
    """Return False for search/research on real subjects; allow clearly creative prompts."""
    t = (text or "").strip()
    try:
        from arka.agent.local_image_gen import wants_local_image

        if wants_local_image(t):
            return False
    except ImportError:
        pass
    if not t or not _EXPLICIT_GENERATION_RE.search(t):
        return False
    if is_search_or_research_intent(t):
        return False
    prompt = _extract_image_prompt(t)
    if not prompt:
        return False
    if is_creative_or_imaginary_subject(prompt) or is_creative_or_imaginary_subject(t):
        return True
    if is_real_world_subject(prompt, full_text=t):
        return False
    return True


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    try:
        from arka.agent.local_image_gen import wants_local_image

        if wants_local_image(t):
            return []
    except ImportError:
        pass

    if re.search(
        r"(?i)(?:^|\b)(?:generate|create|make|draw|design)\s+(?:an?\s+)?(?:youtube\s+)?thumbnail\b",
        t,
    ):
        return []

    if re.search(r"(?i)\bascii\s+(?:art|banner)\b", t) or re.search(r"(?i)\bfiglet\b", t):
        return []

    if not should_generate_image(t):
        return []

    prompt = _extract_image_prompt(t)
    return [prompt] if prompt else []


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
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
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        from arka.core.skill_requirements import image_generation_available, hint_for_env

        print(_friendly_gemini_error(exc), file=sys.stderr)
        if not image_generation_available():
            print(
                "\nCannot generate images — no API key configured and fallback disabled.\n"
                f"  • {hint_for_env('GEMINI_API_KEY')}\n"
                f"  • {hint_for_env('POLLINATIONS_API_KEY')}\n"
                "  • Or keep IMAGE_FALLBACK=1 (default) for free Pollinations flux.",
                file=sys.stderr,
            )
        return 1

    print(f"Saved ({provider}): {saved}")
    if os.environ.get("OPEN_IMAGE", "1") not in ("0", "false"):
        try:
            import subprocess

            if sys.platform == "darwin":
                opener = ["open", str(saved)]
            elif sys.platform.startswith("linux"):
                opener = ["xdg-open", str(saved)]
            else:
                opener = None
            if opener:
                subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate images with Google Nano Banana (Gemini) or Pollinations"
    )
    sub = p.add_subparsers(dest="cmd")

    p_gen = sub.add_parser("generate", help="Generate image from prompt")
    p_gen.add_argument("prompt", help="Image description")
    p_gen.add_argument("-o", "--output", help="Output file path")
    p_gen.add_argument("-a", "--aspect", default="1:1", help="Aspect ratio")
    p_gen.add_argument(
        "-m",
        "--model",
        default="",
        help=f"Nano Banana model (default: try {', '.join(NANO_BANANA_MODELS[:3])}…)",
    )
    p_gen.set_defaults(func=cmd_generate)

    p_parse = sub.add_parser("parse", help="Parse natural language → generate_image args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0

    if argv[0] == "parse":
        args = build_parser().parse_args(argv)
        return args.func(args)

    if argv[0] not in {"generate", "-h", "--help"}:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl

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
    args = parser.parse_args(argv)
    return cmd_generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
