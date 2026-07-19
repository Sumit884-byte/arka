"""Local image generation via a Stable Diffusion WebUI-compatible API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


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
            start_cmd = os.environ.get("ARKA_SD_START_CMD", "").strip()
            if not start_cmd:
                raise RuntimeError(
                    f"local image backend unavailable at {endpoint}. Set ARKA_SD_START_CMD to a local server command or start Stable Diffusion WebUI with --api."
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
    return {
        "built_in_image_generator": "unavailable or unauthorized (403)",
        "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
        "local_sd_api": local,
        "local_sd_endpoint": endpoint,
        "recommendation": "Use the local Stable Diffusion backend."
        if local
        else "Start Stable Diffusion WebUI with --api or configure ARKA_SD_API_URL.",
    }


def main(argv: list[str] | None = None) -> int:
    if argv and argv[0] == "doctor":
        print(json.dumps(doctor(), indent=2))
        return 0
    p = argparse.ArgumentParser(prog="arka image generate")
    p.add_argument("prompt", nargs="+")
    p.add_argument("--output", default="arka-generated.png")
    p.add_argument("--url")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = generate(
            " ".join(args.prompt), args.output, url=args.url, steps=args.steps
        )
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
