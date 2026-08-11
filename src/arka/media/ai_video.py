#!/usr/bin/env python3
"""Full AI text-to-video — Pollinations, Gemini Veo 3.1 chain, optional Replicate.

Unlike compose_video (stock photos + TTS) or create_video (ffmpeg slideshows), every
backend here generates real video pixels from a text prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_GEMINI_MODEL = "veo-3.1-generate-preview"
DEFAULT_POLLINATIONS_MODEL = "wan-fast"
DEFAULT_REPLICATE_MODEL = "minimax/video-01"
GEMINI_VEO_MODELS = (
    "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview",
    "veo-3.1-generate-preview",
)
ALLOWED_ASPECTS = {"16:9", "9:16", "1:1"}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _api_key() -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val and val not in ("your_gemini_api_key_here", "changeme", "your_key_here"):
            return val
    return ""


def _pollinations_key() -> str:
    for name in ("POLLINATIONS_API_KEY", "POLLINATIONS_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _replicate_token() -> str:
    return os.environ.get("REPLICATE_API_TOKEN", "").strip()


def _backend() -> str:
    return os.environ.get("VIDEO_BACKEND", "auto").strip().lower() or "auto"


def _default_output(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "ai-video"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("VIDEO_OUTPUT_DIR", "").strip()
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Videos" / "arka-ai-video"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.mp4"


def _setup_hint() -> str:
    return (
        "Full AI video needs a text-to-video API — stock-photo slideshows are a different skill (compose_video).\n\n"
        "Option 1 — Pollinations (free signup, recommended):\n"
        "  1. Get a key: https://enter.pollinations.ai/\n"
        "  2. Add to ~/.config/arka/.env:\n"
        "       POLLINATIONS_API_KEY=pk_...\n"
        "  3. Run: arka ai_video cinematic drone shot over mountains\n\n"
        "Option 2 — Gemini Veo 3.1 (paid tier + billing):\n"
        "  • Enable billing: https://aistudio.google.com/\n"
        "  • Uses GEMINI_API_KEY (invalid GOOGLE_API_KEY placeholders are ignored)\n"
        "  • Tries fast → lite → standard Veo 3.1 models automatically\n\n"
        "Option 3 — Replicate (optional):\n"
        "  • REPLICATE_API_TOKEN=... and optional VIDEO_REPLICATE_MODEL\n\n"
        "Not AI: arka compose_video (stock B-roll + TTS) or arka create_video (ffmpeg slideshows)"
    )


def _friendly_error(provider: str, exc: Exception) -> str:
    text = str(exc)
    if provider == "gemini":
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            return f"Gemini Veo rate/quota (429): {text[:400]}"
        if "404" in text or "NOT_FOUND" in text:
            return f"Gemini model not found (404): {text[:400]}"
        if "billing" in text.lower() or "FAILED_PRECONDITION" in text:
            return f"Gemini Veo precondition failed: {text[:400]}"
    if provider == "pollinations":
        if "401" in text or "403" in text:
            return "Pollinations rejected the API key — check POLLINATIONS_API_KEY in .env"
    if provider == "replicate":
        if "401" in text or "403" in text:
            return "Replicate rejected the API token — check REPLICATE_API_TOKEN"
    return f"{provider}: {text[:400]}"


def _download_url(url: str, headers: dict[str, str] | None = None, timeout: int = 600) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "arka-ai-video/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError("Empty response from video provider")
    if data[:1] == b"{":
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
            msg = payload.get("error") or payload.get("message") or payload
            raise RuntimeError(str(msg))
        except json.JSONDecodeError:
            pass
    return data


def _prepare_gemini_env() -> str:
    """Prefer GEMINI_API_KEY; drop conflicting GOOGLE_API_KEY when both are set."""
    gemini = os.environ.get("GEMINI_API_KEY", "").strip()
    google = os.environ.get("GOOGLE_API_KEY", "").strip()
    placeholders = {"your_gemini_api_key_here", "changeme", "your_key_here", ""}
    if gemini and gemini not in placeholders:
        if google and google != gemini:
            os.environ.pop("GOOGLE_API_KEY", None)
        return gemini
    if google and google not in placeholders:
        return google
    return ""


def _gemini_models(preferred: str) -> list[str]:
    env = os.environ.get("VIDEO_MODEL", "").strip()
    models: list[str] = []
    for name in (preferred, env, *GEMINI_VEO_MODELS):
        if name and name not in models:
            models.append(name)
    return models


def generate_gemini(
    prompt: str,
    output: Path,
    aspect: str,
    model: str,
    duration: int,
) -> Path:
    from google import genai
    from google.genai import types

    key = _prepare_gemini_env() or _api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=key)
    cfg = types.GenerateVideosConfig(
        aspect_ratio=aspect,
        number_of_videos=1,
    duration_seconds=min(max(int(duration), 4), 8),
    )
    _log(f"  Gemini Veo ({model}) — generating real AI video, may take 1–3 minutes …")
    operation = client.models.generate_videos(
        model=model,
        source=types.GenerateVideosSource(prompt=prompt),
        config=cfg,
    )
    while not getattr(operation, "done", False):
        time.sleep(10)
        operation = client.operations.get(operation)
        _log("  … still generating")

    if getattr(operation, "error", None):
        raise RuntimeError(str(operation.error))

    result = getattr(operation, "result", None)
    videos = getattr(result, "generated_videos", None) if result else None
    if not videos:
        raise RuntimeError("Gemini returned no video")

    video = videos[0].video
    if video is None:
        raise RuntimeError("Gemini returned empty video")

    client.files.download(file=video)
    if not video.video_bytes:
        raise RuntimeError("Gemini video download failed")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(video.video_bytes)
    return output


def generate_gemini_chain(
    prompt: str,
    output: Path,
    aspect: str,
    model: str,
    duration: int,
) -> tuple[Path, str]:
    errors: list[str] = []
    for idx, veo_model in enumerate(_gemini_models(model), start=1):
        _log(f"[backend {idx}] Trying Gemini Veo model: {veo_model}")
        try:
            saved = generate_gemini(prompt, output, aspect, veo_model, duration)
            return saved, f"gemini:{veo_model}"
        except Exception as exc:
            errors.append(_friendly_error("gemini", exc))
            _log(f"  ✗ {veo_model} failed: {errors[-1]}")
    raise RuntimeError("\n".join(errors) or "All Gemini Veo models failed")


def generate_pollinations(
    prompt: str,
    output: Path,
    aspect: str,
    model: str,
    duration: int,
    audio: bool,
) -> Path:
    key = _pollinations_key()
    if not key:
        raise RuntimeError("POLLINATIONS_API_KEY not set")

    encoded = urllib.parse.quote(prompt)
    params = urllib.parse.urlencode(
        {
            "model": model,
            "duration": duration,
            "aspectRatio": aspect,
            "audio": "true" if audio else "false",
        }
    )
    url = f"https://gen.pollinations.ai/video/{encoded}?{params}"
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "arka-ai-video/1.0"}
    _log(f"  Pollinations ({model}, {duration}s) — generating real AI video …")
    data = _download_url(url, headers=headers, timeout=600)

    out = output if output.suffix.lower() == ".mp4" else output.with_suffix(".mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def _replicate_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "arka-ai-video/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def generate_replicate(
    prompt: str,
    output: Path,
    aspect: str,
    duration: int,
) -> Path:
    token = _replicate_token()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not set")

    model = os.environ.get("VIDEO_REPLICATE_MODEL", DEFAULT_REPLICATE_MODEL).strip() or DEFAULT_REPLICATE_MODEL
    owner, name = model.split("/", 1) if "/" in model else ("minimax", model)
    url = f"https://api.replicate.com/v1/models/{owner}/{name}/predictions"
    _log(f"  Replicate ({model}) — submitting prediction …")

    prediction = _replicate_request(
        "POST",
        url,
        token,
        {"input": {"prompt": prompt, "aspect_ratio": aspect.replace(":", "_"), "duration": duration}},
    )
    poll_url = prediction.get("urls", {}).get("get") or prediction.get("url")
    if not poll_url:
        raise RuntimeError(f"Replicate returned no poll URL: {prediction}")

    deadline = time.time() + int(os.environ.get("VIDEO_REPLICATE_TIMEOUT", "600"))
    while time.time() < deadline:
        status_payload = _replicate_request("GET", poll_url, token)
        status = status_payload.get("status")
        if status == "succeeded":
            out_url = status_payload.get("output")
            if isinstance(out_url, list):
                out_url = out_url[0] if out_url else None
            if not out_url or not isinstance(out_url, str):
                raise RuntimeError(f"Replicate succeeded but no output URL: {status_payload}")
            data = _download_url(out_url, timeout=600)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            return output
        if status in ("failed", "canceled"):
            raise RuntimeError(status_payload.get("error") or f"Replicate {status}")
        _log("  … Replicate still processing")
        time.sleep(5)

    raise RuntimeError("Replicate prediction timed out")


def generate(
    prompt: str,
    output: Path,
    *,
    aspect: str,
    model: str,
    duration: int,
    audio: bool,
) -> tuple[Path, str]:
    backend = _backend()
    errors: list[str] = []
    attempt = 0

    def _try(name: str, fn) -> tuple[Path, str] | None:
        nonlocal attempt
        attempt += 1
        _log(f"[backend {attempt}] Trying {name} …")
        try:
            result = fn()
            if isinstance(result, tuple):
                return result
            return result, name
        except SystemExit:
            raise
        except Exception as exc:
            msg = _friendly_error(name.split(":")[0], exc)
            errors.append(msg)
            _log(f"  ✗ {name} failed: {msg}")
            return None

    if backend == "gemini":
        if not _api_key():
            raise SystemExit(_setup_hint())
        result = _try("gemini", lambda: generate_gemini_chain(prompt, output, aspect, model, duration))
        if result:
            return result
        raise SystemExit("\n".join(errors) or "Gemini video generation failed")

    if backend == "pollinations":
        if not _pollinations_key():
            raise SystemExit(_setup_hint())
        poll_model = os.environ.get("VIDEO_POLLINATIONS_MODEL", DEFAULT_POLLINATIONS_MODEL)
        result = _try(
            "pollinations",
            lambda: generate_pollinations(prompt, output, aspect, poll_model, duration, audio),
        )
        if result:
            return result
        raise SystemExit("\n".join(errors) or "Pollinations video generation failed")

    if backend == "replicate":
        if not _replicate_token():
            raise SystemExit(_setup_hint())
        result = _try("replicate", lambda: generate_replicate(prompt, output, aspect, duration))
        if result:
            return result
        raise SystemExit("\n".join(errors) or "Replicate video generation failed")

    # auto: Pollinations → Gemini Veo chain → Replicate
    if not _pollinations_key() and not _api_key() and not _replicate_token():
        raise SystemExit(_setup_hint())

    if _pollinations_key():
        poll_model = os.environ.get("VIDEO_POLLINATIONS_MODEL", DEFAULT_POLLINATIONS_MODEL)
        result = _try(
            "pollinations",
            lambda: generate_pollinations(prompt, output, aspect, poll_model, duration, audio),
        )
        if result:
            return result

    if _api_key():
        result = _try(
            "gemini",
            lambda: generate_gemini_chain(prompt, output, aspect, model, duration),
        )
        if result:
            return result

    if _replicate_token():
        result = _try("replicate", lambda: generate_replicate(prompt, output, aspect, duration))
        if result:
            return result

    detail = "\n".join(f"  • {e}" for e in errors if e)
    raise SystemExit(f"All AI video backends failed.\n{detail}\n\n{_setup_hint()}")


def ai_video_result(
    prompt: str,
    *,
    output: str | Path | None = None,
    aspect: str | None = None,
    model: str | None = None,
    duration: int | None = None,
    audio: bool | None = None,
) -> dict[str, object]:
    asp = aspect or os.environ.get("VIDEO_ASPECT", "16:9")
    dur = min(max(int(duration or os.environ.get("VIDEO_DURATION") or 5), 4), 15)
    aud = audio if audio is not None else os.environ.get("VIDEO_AUDIO", "1") not in ("0", "false")
    out = Path(output).expanduser() if output else _default_output(prompt)
    saved, provider = generate(
        prompt,
        out,
        aspect=asp,
        model=model or os.environ.get("VIDEO_MODEL", DEFAULT_GEMINI_MODEL),
        duration=dur,
        audio=aud,
    )
    return {
        "prompt": prompt,
        "output": str(saved),
        "provider": provider,
        "aspect": asp,
        "duration": dur,
        "audio": aud,
    }


_VIDEO_VERBS = r"(?:generate|create|make|render|produce|animate|film)"
_VIDEO_NOUNS = r"(?:ai\s+video|full\s+ai\s+video|ai\s+clip|ai\s+animation|ai\s+movie|video|clip|animation|movie|animated\s+video)"


def _is_compose_video_request(text: str) -> bool:
    t = text.strip()
    duration_gap = r"(?:(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|sec)\s+)+)?"
    if re.search(
        rf"(?i){duration_gap}(?:youtube|info|tech|explainer)\s+video\b",
        t,
    ):
        return True
    if re.search(
        rf"(?i)(?:make|create|compose|build|render|produce|generate)\s+(?:a\s+|an\s+)?{duration_gap}video\s+(?:on|about|for|explaining)\s+\S",
        t,
    ):
        return True
    return False


def _is_local_video_request(text: str) -> bool:
    t = text.strip()
    if re.search(r"(?i)\b(?:from|with)\s+(?:images?|photos?|pictures?|audio|folder)\b", t):
        return True
    if re.search(r"(?i)\b(?:slideshow|transparent\s+video|image-audio)\b", t):
        return True
    return False


def _is_ai_video_request(text: str) -> bool:
    t = text.strip()
    if not t or _is_compose_video_request(t) or _is_local_video_request(t):
        return False
    if re.search(rf"(?i)\b(?:full\s+)?ai\s+(?:video|clip|animation|movie)\b", t):
        return True
    if re.search(rf"(?i)\b(?:text[\s-]?to[\s-]?video|ai\s+video\s+generation)\b", t):
        return True
    if re.search(rf"(?i)^{_VIDEO_VERBS}\s+(?:an?\s+)?(?:full\s+)?ai\s+(?:video|clip|animation|movie)\b", t):
        return True
    if re.search(rf"(?i)^{_VIDEO_VERBS}\s+(?:an?\s+)?{_VIDEO_NOUNS}\b", t):
        return True
    if re.search(rf"(?i)^{_VIDEO_VERBS}\s+(?:an?\s+)?.+\b(?:video|clip|animation|movie)\b", t):
        return True
    if re.search(r"(?i)^(animate|film)\s+", t):
        return True
    return False


def _extract_video_prompt(text: str) -> str:
    t = text.strip()
    t = re.sub(
        rf"(?i)^{_VIDEO_VERBS}\s+(?:an?\s+)?(?:full\s+)?(?:ai\s+)?(?:video|clip|animation|movie|animated\s+video)\s*(?:of|about|showing|depicting)?\s*",
        "",
        t,
    )
    if t == text.strip():
        t = re.sub(rf"(?i)^{_VIDEO_VERBS}\s+(?:an?\s+)?", "", text.strip())
        t = re.sub(rf"(?i)\s+\b(?:video|clip|animation|movie)\s*$", "", t)
    t = re.sub(r"(?i)\b(?:for|-d|--duration)\s+\d+\s*(?:seconds?|secs?|s)?\b", "", t)
    t = re.sub(r"(?i)^(?:of|about|for|showing|depicting)\s+", "", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_ai_video_request(t):
        return []

    argv: list[str] = []
    if re.search(r"(?i)\b(?:no\s+audio|without\s+audio|silent)\b", t):
        argv.append("--no-audio")

    asp = re.search(r"(?i)\b(?:aspect|format)\s+(16:9|9:16|1:1)\b", t)
    if asp:
        argv.extend(["-a", asp.group(1)])

    dur = re.search(r"(?i)\b(?:for|-d|--duration)\s+(\d+)\s*(?:seconds?|secs?|s)?\b", t)
    if dur:
        argv.extend(["-d", dur.group(1)])

    out = re.search(r"(?i)\b(?:to|into|save\s+to|output)\s+([^\s]+\.mp4)\b", t)
    if out:
        argv.extend(["-o", out.group(1)])

    prompt = _extract_video_prompt(t)
    if prompt:
        argv.append(prompt)
    elif not argv:
        return []
    return argv


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    aspect = args.aspect
    if aspect not in ALLOWED_ASPECTS:
        print(f"Invalid aspect '{aspect}'. Choose: {', '.join(sorted(ALLOWED_ASPECTS))}", file=sys.stderr)
        return 1

    duration = min(max(int(args.duration), 4), 15)
    audio = not args.no_audio and os.environ.get("VIDEO_AUDIO", "1") not in ("0", "false")
    out = Path(args.output) if args.output else _default_output(args.prompt)

    print(f"Generating full AI video ({aspect}, {duration}s) …")
    try:
        saved, provider = generate(
            args.prompt,
            out,
            aspect=aspect,
            model=args.model,
            duration=duration,
            audio=audio,
        )
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Saved ({provider}): {saved}")
    if os.environ.get("OPEN_VIDEO", "1") not in ("0", "false"):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    backend = _backend()
    _log(f"VIDEO_BACKEND: {backend}")
    poll = _pollinations_key()
    gem = _api_key()
    rep = _replicate_token()
    _log(f"  POLLINATIONS_API_KEY: {'set' if poll else 'not set — https://enter.pollinations.ai/'}")
    _log(f"  GEMINI_API_KEY: {'set' if gem else 'not set'}")
    _log(f"  REPLICATE_API_TOKEN: {'set' if rep else 'not set'}")
    _log(f"  Gemini Veo fallback chain: {' → '.join(_gemini_models(DEFAULT_GEMINI_MODEL))}")
    if backend == "auto" and not poll and not gem and not rep:
        _log("\nNo backends configured. See setup hints above.")
        return 1
    return 0


def cmd_setup_pollinations(args: argparse.Namespace) -> int:
    """Open Pollinations dashboard in Brave (Selenium, isolated profile) and save API key to .env."""
    from arka.paths import checkout_root

    script = checkout_root() / "scripts" / "pollinations_api_key_selenium.py" if checkout_root() else None
    if not script or not script.is_file():
        _log("Run from Arka checkout or: python scripts/pollinations_api_key_selenium.py")
        return 1
    cmd = [sys.executable, str(script)]
    if getattr(args, "create", False):
        cmd.append("--create")
    return subprocess.call(cmd)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Full AI text-to-video (Pollinations, Gemini Veo 3.1, Replicate)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ai_video cinematic drone shot over mountains at sunset\n"
            "  ai_video 'a cat walking in rain' -o ~/Videos/cat.mp4\n"
            "  ai_video check\n"
            "  ai_video setup-pollinations [--create]\n\n"
            "Not this skill: compose_video (stock photos + TTS), create_video (ffmpeg slideshows)"
        ),
    )
    sub = p.add_subparsers(dest="cmd")

    p_gen = sub.add_parser("generate", help="Generate full AI video from a text prompt")
    p_gen.add_argument("prompt", help="Video description")
    p_gen.add_argument("-o", "--output", help="Output .mp4 path")
    p_gen.add_argument("-a", "--aspect", default=os.environ.get("VIDEO_ASPECT", "16:9"))
    p_gen.add_argument("-d", "--duration", type=int, default=int(os.environ.get("VIDEO_DURATION") or "5"))
    p_gen.add_argument("-m", "--model", default=os.environ.get("VIDEO_MODEL", DEFAULT_GEMINI_MODEL))
    p_gen.add_argument("--no-audio", action="store_true", help="Disable Pollinations audio track")
    p_gen.set_defaults(func=cmd_generate)

    p_parse = sub.add_parser("parse", help="Parse natural language → ai_video args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify configured AI video backends")
    p_check.set_defaults(func=cmd_check)

    p_setup = sub.add_parser(
        "setup-pollinations",
        help="Open enter.pollinations.ai in Brave (isolated profile) and save API key to .env (Selenium)",
    )
    p_setup.add_argument(
        "--create",
        action="store_true",
        help="Create a new secret API key if none is visible",
    )
    p_setup.set_defaults(func=cmd_setup_pollinations)

    return p


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        build_parser().print_help()
        return 0
    if args in (["-h"], ["--help"]):
        build_parser().parse_args(["generate", "--help"])
        return 0
    if args[0] == "parse":
        ns = build_parser().parse_args(args)
        return int(ns.func(ns))
    if args[0] == "check":
        ns = build_parser().parse_args(args)
        return int(ns.func(ns))
    if args[0] == "setup-pollinations":
        ns = build_parser().parse_args(args)
        return int(ns.func(ns))
    if args[0] not in {"generate", "-h", "--help"}:
        args = ["generate", *args]
    try:
        ns = build_parser().parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not getattr(ns, "cmd", None):
        build_parser().print_help()
        return 0
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
