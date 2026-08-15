"""Local image generation via a Stable Diffusion WebUI-compatible API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_LOCAL_INTENT_RE = re.compile(
    r"(?i)\b(?:"
    r"locally|local(?:ly)?|offline|on[\s-]device|on[\s-]prem(?:ises)?|"
    r"without\s+(?:cloud|api)|no\s+cloud|self[\s-]hosted|private|"
    r"stable[\s-]diffusion|sd[\s-]webui|automatic1111|a1111|forge|comfyui|"
    r"diffusion\s+model|local\s+(?:sd|image\s+model|diffusion)"
    r")\b"
)

_EXPLICIT_IMAGE_RE = re.compile(
    r"(?i)(?:^|\b)(?:generate|create|make|draw|paint|sketch|design)\s+(?:\w+\s+){0,6}"
    r"(?:image|picture|photo|art|drawing|sketch|painting|illustration|portrait|landscape)\b"
)


def _clean_nl_text(text: str) -> str:
    t = (text or "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        t = t[1:-1].strip()
    return t


def wants_local_image(text: str) -> bool:
    """True when the user wants local Stable Diffusion, not cloud generate_image."""
    t = _clean_nl_text(text)
    if not t:
        return False
    if _LOCAL_INTENT_RE.search(t):
        return True
    if re.search(r"(?i)\b(?:generate|create|make|draw)\b.*\b(?:image|picture|photo|art)\b.*\blocal\b", t):
        return True
    if re.search(r"(?i)\blocal\b.*\b(?:generate|create|make|draw)\b.*\b(?:image|picture|photo|art)\b", t):
        return True
    if re.search(r"(?i)\buse\s+local\s+image\s+model\b", t):
        return True
    return False


def _normalize_local_request(text: str) -> str:
    t = _clean_nl_text(text)
    t = re.sub(
        r"(?i)\b(?:"
        r"locally|local(?:ly)?|offline|on[\s-]device|on[\s-]prem(?:ises)?|"
        r"using\s+local(?:\s+(?:sd|stable[\s-]diffusion|diffusion|model))?|"
        r"with\s+(?:local\s+)?stable[\s-]diffusion|via\s+sd[\s-]webui|"
        r"without\s+(?:cloud|api)|no\s+cloud|self[\s-]hosted|private|"
        r"stable[\s-]diffusion|sd[\s-]webui|automatic1111|a1111|forge|comfyui|"
        r"local\s+(?:sd|image\s+model|diffusion\s+model)"
        r")\b",
        " ",
        t,
    )
    return " ".join(t.split())


def _extract_prompt(text: str) -> str:
    normalized = _normalize_local_request(text)
    try:
        from arka.generate.image import _extract_image_prompt

        prompt = _extract_image_prompt(normalized)
    except ImportError:
        prompt = re.sub(
            r"(?i)^(?:generate|create|draw|paint|make|sketch|design)\s+"
            r"(?:me\s+)?(?:an?\s+)?"
            r"(?:image|picture|photo|drawing|painting|sketch|illustration|portrait|landscape|\bart\b)?\s*(?:of)?\s*",
            "",
            normalized,
        ).strip()
    prompt = re.sub(r"(?i)^(?:of\s+)", "", prompt).strip()
    return " ".join(prompt.split()).strip()


def nl_to_argv(text: str) -> list[str] | None:
    t = (text or "").strip()
    if not t or not wants_local_image(t):
        return None
    if not _EXPLICIT_IMAGE_RE.search(t) and not re.search(
        r"(?i)\b(?:local\s+image|offline\s+image|stable[\s-]diffusion)\b", t
    ):
        return None
    prompt = _extract_prompt(t)
    if not prompt:
        return None
    return ["generate", prompt]


def route_command(text: str) -> str:
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "image " + " ".join(shlex.quote(a) for a in argv)


def _default_output_path(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "image"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("IMAGE_OUTPUT_DIR", "").strip()
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Pictures" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.png"


def _resolve_start_cmd() -> str:
    cmd = os.environ.get("ARKA_SD_START_CMD", "").strip()
    if cmd:
        return cmd
    home = Path.home()
    for rel in (
        "stable-diffusion-webui/webui.sh",
        "sd-webui/webui.sh",
        "AI/stable-diffusion-webui/webui.sh",
        "Projects/stable-diffusion-webui/webui.sh",
    ):
        path = home / rel
        if path.is_file():
            return f"{path} --api --listen"
    return ""


def generate(
    prompt: str, output: str, *, url: str | None = None, steps: int = 20
) -> dict[str, object]:
    base = (url or os.environ.get("ARKA_SD_API_URL") or "http://127.0.0.1:7860").rstrip(
        "/"
    )
    endpoint = base + "/sdapi/v1/txt2img"
    payload = json.dumps(
        {"prompt": prompt, "steps": max(1, min(50, steps)), "width": 768, "height": 768}
    ).encode()
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    process = None
    try:
        try:
            with urllib.request.urlopen(base + "/sdapi/v1/options", timeout=2):
                pass
        except Exception:
            start_cmd = _resolve_start_cmd()
            if not start_cmd:
                raise RuntimeError(
                    f"local image backend unavailable at {endpoint}. "
                    "Start Stable Diffusion WebUI with --api, set ARKA_SD_START_CMD, "
                    "or install webui.sh under ~/stable-diffusion-webui."
                )
            process = subprocess.Popen(
                shlex.split(start_cmd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            ready = False
            for _ in range(60):
                time.sleep(1)
                try:
                    with urllib.request.urlopen(base + "/sdapi/v1/options", timeout=2):
                        ready = True
                        break
                except Exception:
                    if process.poll() is not None:
                        break
            if not ready:
                raise RuntimeError(f"local image server did not become ready at {base}")
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode())
    except Exception as exc:
        raise RuntimeError(
            f"local image backend unavailable at {endpoint}: {exc}"
        ) from exc
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    images = body.get("images") or []
    if not images:
        raise RuntimeError("local image backend returned no images")
    raw = base64.b64decode(images[0].split(",", 1)[-1])
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "output": str(path),
        "backend": "stable-diffusion-webui",
        "prompt": prompt,
        "steps": steps,
    }


def doctor() -> dict[str, object]:
    endpoint = (os.environ.get("ARKA_SD_API_URL") or "http://127.0.0.1:7860").rstrip(
        "/"
    )
    local = False
    try:
        with urllib.request.urlopen(endpoint + "/sdapi/v1/options", timeout=2):
            local = True
    except Exception:
        pass
    start_cmd = _resolve_start_cmd()
    return {
        "built_in_image_generator": "unavailable or unauthorized (403)",
        "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
        "local_sd_api": local,
        "local_sd_endpoint": endpoint,
        "arka_sd_start_cmd": bool(os.environ.get("ARKA_SD_START_CMD")),
        "auto_discovered_start_cmd": start_cmd if start_cmd and not os.environ.get("ARKA_SD_START_CMD") else "",
        "recommendation": "Use the local Stable Diffusion backend."
        if local
        else "Start Stable Diffusion WebUI with --api or configure ARKA_SD_API_URL.",
    }


def run_nl(text: str) -> int:
    argv = nl_to_argv(text)
    if not argv or argv[0] != "generate":
        return 1
    prompt = " ".join(argv[1:]).strip()
    if not prompt:
        return 1
    out = _default_output_path(prompt)
    try:
        result = generate(prompt, str(out))
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Generated local image: {result['output']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "doctor":
        print(json.dumps(doctor(), indent=2))
        return 0
    if argv and argv[0] == "parse":
        parsed = nl_to_argv(" ".join(argv[1:]))
        if not parsed:
            return 1
        print(" ".join(shlex.quote(a) for a in parsed))
        return 0
    p = argparse.ArgumentParser(prog="arka image generate")
    p.add_argument("prompt", nargs="+")
    p.add_argument("--output")
    p.add_argument("--url")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    prompt = " ".join(args.prompt)
    out = args.output or str(_default_output_path(prompt))
    try:
        result = generate(prompt, out, url=args.url, steps=args.steps)
    except (OSError, RuntimeError, ValueError) as exc:
        p.error(str(exc))
    print(
        json.dumps(result, indent=2)
        if args.json
        else f"Generated local image: {result['output']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
