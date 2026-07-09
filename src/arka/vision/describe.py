#!/usr/bin/env python3
"""Describe images via a local vLLM vision model (OpenAI-compatible API)."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import platform
import re
import shlex
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".heic", ".svg",
})

DEFAULT_PROMPT = "Describe this image in detail. Mention objects, people, colors, setting, and any visible text."

CHART_PROMPT = "Summarize this chart."

_CHART_NAME = re.compile(
    r"(?i)(?:^|[/_.-])(?:pie|bar|chart|graph|traffic|device|browser|sales|revenue|scatter|histogram|pareto|monthly|quarterly|defect|response)"
)

GROUNDED_VISION_PROMPT = (
    "In ≤120 words: chart type, segment colors, and where each OCR label sits (use x%,y%). "
    "Do not re-read text or repeat numeric values — they are already extracted."
)

GEMINI_SYSTEM = (
    "Describe images accurately and concisely. For charts and graphs, summarize the title, "
    "axes, data series, labels, and main trends or takeaways."
)

GEMINI_GROUNDED_SYSTEM = (
    "OCR coordinates and structured data are authoritative. Describe only visual layout, colors, "
    "and spatial placement. Never change or invent text or numeric values."
)

_OLLAMA_VISION_HINTS = (
    "llava",
    "vision",
    "moondream",
    "bakllava",
    "minicpm-v",
    "llama3.2-vision",
    "gemma3",
)


class BackendError(Exception):
    """Recoverable vision backend failure (auto mode tries the next backend)."""

    def __init__(self, backend: str, message: str, *, recoverable: bool = True) -> None:
        self.backend = backend
        self.message = message
        self.recoverable = recoverable
        super().__init__(message)

_KNOWN_CMDS = frozenset({"describe", "parse", "formats", "help"})

_DRAWING_WORDS = re.compile(
    r"(?i)\b(drawing|blueprint|floor\s+plan|site\s+plan|elevation|section|schematic|"
    r"architectural|MEP|as[- ]built|plan\s+set|shop\s+drawing|construction\s+drawing)\b",
)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _vllm_base_url() -> str:
    base = _env("VLLM_API_URL")
    if not base:
        host = _env("VLLM_HOST", "127.0.0.1:8000")
        base = f"http://{host}"
    if not base.startswith("http"):
        base = f"http://{base}"
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


DEFAULT_VISION_MODEL = "Qwen/Qwen2-VL-2B-Instruct"


def _model_id() -> str:
    return _env("DESCRIBE_IMAGE_MODEL") or _env("VLLM_MODEL") or "default"


def _vllm_unavailable_message() -> str:
    return _describe_unavailable_message()


def _describe_unavailable_message() -> str:
    lines = [
        "Image description is not available for describe_image.",
    ]
    if platform.system() == "Darwin":
        lines.extend(
            [
                "",
                "On macOS, plain `pip install vllm` usually fails — use one of these instead:",
                "",
                "1) Gemini (easiest if you have a key):",
                "   export GEMINI_API_KEY=your-key",
                "   export DESCRIBE_IMAGE_BACKEND=gemini",
                "",
                "2) Ollama vision (local):",
                "   brew install ollama && ollama pull llava",
                "   export DESCRIBE_IMAGE_BACKEND=ollama",
                "",
                "3) vLLM-Metal (Apple Silicon GPU):",
                "   curl -fsSL https://raw.githubusercontent.com/vllm-project/vllm-metal/main/install.sh | bash",
                "   source ~/.venv-vllm-metal/bin/activate",
                "   export VLLM_START_CMD='vllm serve mlx-community/Qwen2-VL-2B-Instruct-4bit --port 8000'",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Install vLLM: pip install vllm",
                "Or set DESCRIBE_IMAGE_BACKEND=gemini|ollama",
                "Or set VLLM_START_CMD, e.g.:",
                f"  export VLLM_START_CMD='vllm serve {DEFAULT_VISION_MODEL} --port 8000'",
            ]
        )
    lines.append(
        "\nArka auto-starts/stops local servers when LLM_AUTO_START_SERVERS=1 (default on)."
    )
    return "\n".join(lines)


def _load_arka_env() -> None:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass


def _api_key() -> str:
    try:
        from arka.env import env_get

        return env_get("GOOGLE_API_KEY") or env_get("GEMINI_API_KEY")
    except ImportError:
        pass
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _gemini_models() -> list[str]:
    models: list[str] = []
    for name in ("DESCRIBE_IMAGE_MODEL", "DRAWING_MODEL"):
        val = _env(name)
        if val and val not in models:
            models.append(val)
    for m in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"):
        if m not in models:
            models.append(m)
    return models


def _ollama_host() -> str:
    host = _env("OLLAMA_HOST", "127.0.0.1:11434")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


def _ollama_vision_model() -> str | None:
    explicit = _env("DESCRIBE_IMAGE_OLLAMA_MODEL") or _env("OLLAMA_VISION_MODEL")
    if explicit:
        return explicit
    try:
        req = urllib.request.Request(f"{_ollama_host()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    names = [
        m.get("name", "")
        for m in (data.get("models") if isinstance(data, dict) else []) or []
        if isinstance(m, dict)
    ]
    for hint in _OLLAMA_VISION_HINTS:
        for name in names:
            if hint in name.lower():
                return name
    return None


def _backend() -> str:
    mode = _env("DESCRIBE_IMAGE_BACKEND", "auto").lower()
    if mode in {"vllm", "ollama", "gemini"}:
        return mode
    return "auto"


def _backend_ready(name: str) -> bool:
    if name == "gemini":
        return bool(_api_key())
    if name == "ollama":
        return bool(_ollama_vision_model()) or bool(shutil.which("ollama"))
    if name == "vllm":
        return bool(shutil.which("vllm") or _env("VLLM_START_CMD"))
    return False


def _auto_backend_order() -> list[str]:
    if platform.system() == "Darwin":
        return ["ollama", "vllm", "gemini"]
    return ["vllm", "ollama", "gemini"]


def _backend_candidates() -> list[str]:
    mode = _backend()
    if mode != "auto":
        return [mode]
    return list(_auto_backend_order())


def _pick_backend() -> str:
    candidates = _backend_candidates()
    return candidates[0] if candidates else "none"


def _is_auth_error(code: int, detail: str) -> bool:
    low = detail.lower()
    return code in {400, 401, 403} and (
        "api key" in low or "api_key" in low or "unauthenticated" in low or "permission denied" in low
    )


def _vllm_port() -> str:
    host = _env("VLLM_HOST", "127.0.0.1:8000")
    if ":" in host.rsplit("/", 1)[-1]:
        return host.rsplit(":", 1)[-1]
    return "8000"


def _apply_vllm_defaults() -> None:
    """Default host/start cmd so describe_image can auto-start/stop vLLM."""
    if not _env("VLLM_HOST") and not _env("VLLM_API_URL"):
        os.environ.setdefault("VLLM_HOST", "127.0.0.1:8000")
    if _env("DESCRIBE_IMAGE_VLLM_START_CMD") and not _env("VLLM_START_CMD"):
        os.environ.setdefault("VLLM_START_CMD", _env("DESCRIBE_IMAGE_VLLM_START_CMD"))
    if not _env("VLLM_START_CMD"):
        model = _model_id()
        if model == "default":
            model = DEFAULT_VISION_MODEL
        port = _vllm_port()
        os.environ.setdefault(
            "VLLM_START_CMD",
            f"vllm serve {model} --host 127.0.0.1 --port {port} --max-model-len 4096",
        )
    os.environ.setdefault("LLM_SERVER_START_TIMEOUT", "600")
    if not _env("VLLM_MODEL") and not _env("DESCRIBE_IMAGE_MODEL"):
        cmd = _env("VLLM_START_CMD")
        m = re.search(r"vllm serve\s+(\S+)", cmd)
        if m:
            os.environ.setdefault("VLLM_MODEL", m.group(1))


def _max_edge() -> int:
    try:
        return max(256, int(_env("DESCRIBE_IMAGE_MAX_EDGE", "2048")))
    except ValueError:
        return 2048


def _require_pillow():
    try:
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        raise SystemExit(
            "Pillow is required for image description.\n"
            "Install: pip install Pillow\n"
            "Or: pip install 'arka-agent[drawings]'"
        ) from None


def _guess_mime(path_or_url: str) -> str:
    ext = Path(urllib.parse.urlparse(path_or_url).path).suffix.lower()
    if not ext and "." in path_or_url.rsplit("/", 1)[-1]:
        ext = Path(path_or_url).suffix.lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".heic": "image/heic",
        ".svg": "image/svg+xml",
    }
    return mapping.get(ext, "image/jpeg")


def _resize_image(data: bytes, mime: str) -> tuple[bytes, str]:
    _require_pillow()
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    max_edge = _max_edge()
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    out_mime = "image/png" if mime == "image/svg+xml" else mime
    buf = io.BytesIO()
    fmt = "PNG" if out_mime == "image/png" else ("JPEG" if out_mime == "image/jpeg" else "PNG")
    if fmt == "JPEG" and img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(buf, format=fmt, optimize=True)
    if fmt == "JPEG":
        out_mime = "image/jpeg"
    elif fmt == "PNG":
        out_mime = "image/png"
    return buf.getvalue(), out_mime


def _to_data_url(data: bytes, mime: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _is_url(text: str) -> bool:
    return bool(re.match(r"https?://", text, re.I))


def _load_local(path: Path) -> tuple[bytes, str]:
    if not path.is_file():
        raise SystemExit(f"Image not found: {path}")
    ext = path.suffix.lower()
    if ext and ext not in IMAGE_EXTENSIONS:
        raise SystemExit(
            f"Unsupported image type {ext}. Supported: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )
    raw = path.read_bytes()
    mime = _guess_mime(str(path))
    return _resize_image(raw, mime)


def _load_url(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "arka/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    except urllib.error.URLError as exc:
        raise SystemExit(f"Failed to download image: {exc}") from exc
    mime = ctype if ctype.startswith("image/") else _guess_mime(url)
    return _resize_image(data, mime)


def load_image(source: str) -> tuple[str, str]:
    """Return (data_url, label) for OpenAI-compatible vision APIs."""
    data, mime, label = load_image_bytes(source)
    return _to_data_url(data, mime), label


def load_image_bytes(source: str) -> tuple[bytes, str, str]:
    """Return (image_bytes, mime, label)."""
    src = source.strip().strip("'\"")
    if _is_url(src):
        data, mime = _load_url(src)
        label = urllib.parse.urlparse(src).path.rsplit("/", 1)[-1] or src
        return data, mime, label
    path = resolve_image_path(src)
    data, mime = _load_local(path)
    return data, mime, path.name


def _vllm_describe(data_url: str, prompt: str, *, max_tokens: int | None = None) -> str:
    base = _vllm_base_url()
    url = f"{base}/chat/completions"
    model = _model_id()
    if max_tokens is None:
        max_tokens = _vision_max_tokens(grounded=False)
    try:
        temperature = float(_env("DESCRIBE_IMAGE_TEMPERATURE", "0.2"))
    except ValueError:
        temperature = 0.2

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    key = _env("VLLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise SystemExit(f"vLLM vision request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"vLLM request failed: {exc}") from exc

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit(f"Unexpected vLLM response: {data!r}") from exc


def _gemini_describe(
    data: bytes,
    mime: str,
    prompt: str,
    *,
    max_tokens: int | None = None,
    grounded: bool = False,
) -> str:
    api_key = _api_key()
    if not api_key:
        raise BackendError(
            "gemini",
            "GEMINI_API_KEY or GOOGLE_API_KEY required for Gemini vision.",
            recoverable=True,
        )
    if max_tokens is None:
        max_tokens = _vision_max_tokens(grounded=grounded)
    system = GEMINI_GROUNDED_SYSTEM if grounded else GEMINI_SYSTEM
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt.strip() or DEFAULT_PROMPT},
                    {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}},
                ],
            }
        ],
        "system_instruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }
    last_err = ""
    auth_failed = False
    for model in _gemini_models():
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(api_key, safe='')}"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            last_err = f"Gemini vision error ({exc.code}): {detail}"
            if _is_auth_error(exc.code, detail):
                auth_failed = True
                break
            if exc.code in {404, 429} or "not found" in detail.lower():
                continue
            raise BackendError("gemini", last_err, recoverable=False) from exc
        except urllib.error.URLError as exc:
            raise BackendError("gemini", f"Network error calling Gemini: {exc}", recoverable=True) from exc

        candidates = payload.get("candidates") or []
        if not candidates:
            last_err = f"No response from Gemini: {json.dumps(payload)[:300]}"
            continue
        content = candidates[0].get("content") or {}
        text_parts = [
            p.get("text", "")
            for p in content.get("parts") or []
            if isinstance(p, dict) and p.get("text")
        ]
        answer = "\n".join(text_parts).strip()
        if answer:
            return answer
        last_err = "Empty response from Gemini."
    hint = ""
    if auth_failed:
        hint = " Fix GEMINI_API_KEY in ~/.config/arka/.env or set DESCRIBE_IMAGE_BACKEND=ollama."
    raise BackendError("gemini", (last_err or "Gemini vision failed for all models.") + hint, recoverable=auth_failed or bool(last_err))


def _ollama_describe(data: bytes, mime: str, prompt: str, *, max_tokens: int | None = None) -> str:
    from arka.llm.servers import LlmServerSession

    model = _ollama_vision_model()
    if not model:
        raise BackendError(
            "ollama",
            "No Ollama vision model found. Install one: ollama pull llava",
            recoverable=True,
        )
    if max_tokens is None:
        max_tokens = _vision_max_tokens(grounded=False)
    session = LlmServerSession()
    try:
        if not session.prepare("ollama"):
            raise BackendError(
                "ollama",
                "Ollama is not running. Start it: ollama serve — or install from https://ollama.com",
                recoverable=True,
            )
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt.strip() or DEFAULT_PROMPT,
                    "images": [base64.b64encode(data).decode("ascii")],
                }
            ],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }
        url = f"{_ollama_host()}/api/chat"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:800]
            raise BackendError(
                "ollama",
                f"Ollama vision request failed ({exc.code}): {detail}",
                recoverable=exc.code >= 500,
            ) from exc
        except urllib.error.URLError as exc:
            raise BackendError("ollama", f"Ollama request failed: {exc}", recoverable=True) from exc
        message = result.get("message") or {}
        answer = (message.get("content") or "").strip()
        if not answer:
            raise BackendError("ollama", f"Unexpected Ollama response: {result!r}", recoverable=False)
        return answer
    finally:
        session.close()


def _vllm_describe_bytes(data: bytes, mime: str, prompt: str, *, max_tokens: int | None = None) -> str:
    from arka.llm.servers import LlmServerSession

    _apply_vllm_defaults()
    session = LlmServerSession()
    try:
        if not session.prepare("vllm"):
            raise BackendError(
                "vllm",
                "vLLM server not reachable and could not be started.",
                recoverable=True,
            )
        return _vllm_describe(_to_data_url(data, mime), prompt, max_tokens=max_tokens)
    finally:
        session.close()


def _run_backend(
    backend: str,
    data: bytes,
    mime: str,
    prompt: str,
    *,
    max_tokens: int | None = None,
    grounded: bool = False,
) -> str:
    if backend == "gemini":
        return _gemini_describe(data, mime, prompt, max_tokens=max_tokens, grounded=grounded)
    if backend == "ollama":
        return _ollama_describe(data, mime, prompt, max_tokens=max_tokens)
    if backend == "vllm":
        return _vllm_describe_bytes(data, mime, prompt, max_tokens=max_tokens)
    raise BackendError(backend, f"Unknown backend: {backend}", recoverable=False)


def _vision_max_tokens(*, grounded: bool) -> int:
    raw = _env("DESCRIBE_IMAGE_MAX_TOKENS")
    if raw:
        try:
            return max(64, int(raw))
        except ValueError:
            pass
    if grounded:
        try:
            return max(64, int(_env("DESCRIBE_IMAGE_GROUNDED_MAX_TOKENS", "256")))
        except ValueError:
            return 256
    return 1024


def _two_layer_enabled() -> bool:
    return _env("DESCRIBE_IMAGE_TWO_LAYER", "1") not in {"0", "false", "no", "off"}


def _load_chart_payload(source: str) -> dict | None:
    if _is_url(source):
        return None
    try:
        path = resolve_image_path(source)
    except SystemExit:
        return None
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    from arka.vision.chart_visual import enrich_payload

    return enrich_payload(payload)


def _load_chart_sidecar(source: str) -> str | None:
    payload = _load_chart_payload(source)
    if not payload:
        return None
    return _format_chart_facts(payload)


def _chart_visual_mode() -> str:
    return _env("DESCRIBE_IMAGE_CHART_VISUAL", "auto").lower()


def _prefer_structured_visual(payload: dict | None) -> bool:
    from arka.vision.chart_visual import can_render_structured

    if not can_render_structured(payload):
        return False
    mode = _chart_visual_mode()
    if mode == "vision":
        return False
    if mode == "structured":
        return True
    return bool(payload and payload.get("source") == "arka-chart")


def _format_chart_facts(payload: dict) -> str:
    lines = [f"Type: {payload.get('type', 'chart')}"]
    title = payload.get("title")
    if title:
        lines.append(f"Title: {title}")
    chart_type = payload.get("type")
    if chart_type == "scatter":
        xlabel = payload.get("xlabel")
        ylabel = payload.get("ylabel")
        if xlabel or ylabel:
            lines.append(f"Axes: X={xlabel or 'X'}, Y={ylabel or 'Y'}")
        points = payload.get("points") or []
        if points:
            lines.append("Points:")
            for pt in points:
                lines.append(f"  • ({pt.get('x', '?')}, {pt.get('y', '?')})")
        return "\n".join(lines)
    if chart_type == "histogram":
        xlabel = payload.get("xlabel")
        if xlabel:
            lines.append(f"X-axis: {xlabel}")
        bins = payload.get("bins") or []
        if bins:
            lines.append("Bins:")
            for row in bins:
                if "label" in row:
                    lines.append(f"  • {row['label']}: {row.get('count', 0):g}")
                else:
                    lines.append(
                        f"  • {row.get('start', '?')}–{row.get('end', '?')}: {row.get('count', 0):g}"
                    )
        return "\n".join(lines)
    if chart_type == "pareto":
        labels = payload.get("labels") or []
        values = payload.get("values") or []
        cumulative = payload.get("cumulative_pct") or {}
        if labels and values:
            lines.append("Categories (descending):")
            for lbl, val in zip(labels, values):
                cum = cumulative.get(lbl)
                cum_part = f", cumulative {cum}%" if cum is not None else ""
                lines.append(f"  • {lbl}: {val:g}{cum_part}")
        return "\n".join(lines)
    labels = payload.get("labels") or []
    values = payload.get("values") or []
    percentages = payload.get("percentages") or {}
    if labels and values:
        lines.append("Series:")
        for lbl, val in zip(labels, values):
            pct = percentages.get(lbl)
            pct_part = f" ({pct}%)" if pct is not None else ""
            lines.append(f"  • {lbl}: {val:g}{pct_part}")
    elif percentages:
        lines.append("Series:")
        for lbl, pct in percentages.items():
            lines.append(f"  • {lbl}: {pct}%")
    return "\n".join(lines)


def _structure_ocr_chart(ocr_text: str) -> str | None:
    if not ocr_text.strip():
        return None
    pairs = re.findall(
        r"([A-Za-z][A-Za-z0-9 &/-]{0,24}?)\s+(\d{1,3})\s*%|(\d{1,3})\s*%\s+([A-Za-z][A-Za-z0-9 &/-]{0,24})",
        ocr_text,
    )
    rows: list[tuple[str, str]] = []
    for a, b, c, d in pairs:
        if a and b:
            rows.append((a.strip(), b))
        elif c and d:
            rows.append((d.strip(), c))
    if len(rows) < 2:
        labels = re.findall(r"(?m)^([A-Za-z][A-Za-z0-9 ]{1,20})$", ocr_text)
        pcts = re.findall(r"(\d{1,3})\s*%", ocr_text)
        if len(labels) >= 2 and len(pcts) >= len(labels):
            rows = list(zip(labels[: len(pcts)], pcts[: len(labels)]))
    if len(rows) < 2:
        return None
    lines = ["Type: chart (structured from OCR)"]
    for label, pct in rows:
        lines.append(f"  • {label}: {pct}%")
    return "\n".join(lines)


def _build_vision_prompt(
    user_prompt: str,
    ocr_text: str,
    chart_facts: str | None,
    *,
    ocr_blocks: tuple | None = None,
) -> tuple[str, bool]:
    from arka.vision.ocr import format_blocks_for_vision, spatial_zones

    blocks = ocr_blocks or ()
    grounded = bool(chart_facts or blocks)
    coord_map = format_blocks_for_vision(blocks) if blocks else ""
    zones = spatial_zones(blocks) if blocks else ""

    blocks_list: list[str] = []
    if chart_facts:
        blocks_list.append("Structured chart data (authoritative — do not change numbers):\n" + chart_facts)
    if coord_map:
        blocks_list.append(coord_map)
    if zones:
        blocks_list.append(zones)
    elif ocr_text.strip() and not coord_map:
        blocks_list.append("OCR text (authoritative for labels and percentages):\n" + ocr_text.strip())

    if not blocks_list:
        return user_prompt, False

    ground = "\n\n".join(blocks_list)
    if grounded and user_prompt.strip() in {DEFAULT_PROMPT, ""}:
        user_prompt = GROUNDED_VISION_PROMPT
    return (
        f"{user_prompt}\n\n"
        "Layer 2 (vision): OCR coordinates + structured data above are authoritative.\n"
        "Describe colors, chart type, and spatial layout only — map labels to x%,y% positions.\n"
        "Do NOT re-read text or invent values.\n\n"
        f"{ground}",
        grounded,
    )


def _show_ocr_detail(*, structured: bool) -> bool:
    default = "0" if structured else "1"
    return _env("DESCRIBE_IMAGE_SHOW_OCR", default) not in {"0", "false", "no", "off"}


def _format_two_layer_output(
    *,
    chart_facts: str | None,
    ocr_text: str,
    ocr_engine: str,
    ocr_blocks: tuple | None,
    vision_text: str,
    vision_backend: str,
    image_label: str = "",
    structured: bool = False,
) -> str:
    from arka.vision.ocr import format_blocks_compact, ocr_install_hint

    if structured and vision_backend == "structured":
        out = vision_text.strip()
        if _show_ocr_detail(structured=True) and ocr_blocks:
            out += "\n\n" + format_blocks_compact(ocr_blocks, ocr_engine)
        elif _show_ocr_detail(structured=True) and ocr_text.strip():
            out += f"\n\n  OCR ({ocr_engine}): {ocr_text.strip()}"
        return out

    parts: list[str] = []
    if image_label:
        parts.append(f"── {image_label} ──")
    if chart_facts and not structured:
        parts.append(f"Data\n{chart_facts}")
    if _show_ocr_detail(structured=False):
        if ocr_blocks:
            from arka.vision.ocr import format_blocks_for_display

            parts.append(f"Text map ({ocr_engine})\n{format_blocks_for_display(ocr_blocks)}")
        elif ocr_text.strip():
            parts.append(f"Text ({ocr_engine})\n{ocr_text.strip()}")
        elif ocr_engine == "none":
            parts.append(f"Text\n{ocr_install_hint()}")
    parts.append(f"Description\n{vision_text.strip()}")
    return "\n\n".join(parts)


def _ocr_layer(data: bytes, mime: str, chart_facts: str | None):
    from arka.vision.ocr import OcrResult, extract_blocks

    result: OcrResult = extract_blocks(data, mime)
    structured = _structure_ocr_chart(result.plain_text) if result.plain_text else None
    facts = chart_facts or structured
    return result, facts


def describe_source(source: str, prompt: str | None = None) -> str:
    _load_arka_env()
    mode = _backend()
    candidates = _backend_candidates()
    if not candidates:
        raise SystemExit(_describe_unavailable_message())

    user_prompt = (prompt or DEFAULT_PROMPT).strip() or DEFAULT_PROMPT
    data, mime, image_label = load_image_bytes(source)
    errors: list[str] = []

    chart_payload = _load_chart_payload(source)
    chart_facts = _format_chart_facts(chart_payload) if chart_payload else None
    ocr_result = None
    facts = chart_facts
    if _two_layer_enabled():
        ocr_result, facts = _ocr_layer(data, mime, chart_facts)
    elif chart_facts:
        facts = chart_facts

    ocr_text = ocr_result.plain_text if ocr_result else ""
    ocr_engine = ocr_result.engine if ocr_result else "disabled"
    ocr_blocks = ocr_result.blocks if ocr_result else ()

    if _two_layer_enabled() and _prefer_structured_visual(chart_payload):
        from arka.vision.chart_visual import render_structured_visual

        visual = render_structured_visual(chart_payload, ocr_blocks)
        return _format_two_layer_output(
            chart_facts=facts,
            ocr_text=ocr_text,
            ocr_engine=ocr_engine,
            ocr_blocks=ocr_blocks,
            vision_text=visual,
            vision_backend="structured",
            image_label=image_label,
            structured=True,
        )

    vision_prompt, grounded = _build_vision_prompt(
        user_prompt,
        ocr_text,
        facts,
        ocr_blocks=ocr_blocks,
    )
    max_tokens = _vision_max_tokens(grounded=grounded)

    for index, backend in enumerate(candidates):
        try:
            vision_text = _run_backend(
                backend,
                data,
                mime,
                vision_prompt,
                max_tokens=max_tokens,
                grounded=grounded,
            )
            if mode == "auto" and index > 0:
                print(f"describe_image: using {backend}", file=sys.stderr)
            if _two_layer_enabled():
                return _format_two_layer_output(
                    chart_facts=facts,
                    ocr_text=ocr_text,
                    ocr_engine=ocr_engine,
                    ocr_blocks=ocr_blocks,
                    vision_text=vision_text,
                    vision_backend=backend,
                    image_label=image_label,
                )
            return vision_text
        except BackendError as exc:
            errors.append(f"{exc.backend}: {exc.message}")
            if mode != "auto" or not exc.recoverable or index >= len(candidates) - 1:
                break
            print(f"describe_image: {exc.backend} failed — trying next backend", file=sys.stderr)

    if facts and _two_layer_enabled():
        return _format_two_layer_output(
            chart_facts=facts,
            ocr_text=ocr_text,
            ocr_engine=ocr_engine,
            ocr_blocks=ocr_blocks,
            vision_text="(Vision backends unavailable — showing extracted data only.)",
            vision_backend="none",
            image_label=image_label,
        )

    if mode != "auto" and errors:
        raise SystemExit(errors[-1].split(": ", 1)[-1] if ": " in errors[-1] else errors[-1])

    msg = _describe_unavailable_message()
    if errors:
        msg += "\n\nAttempts:\n" + "\n".join(f"  • {line}" for line in errors)
    raise SystemExit(msg)


_DESCRIBE_VERB = re.compile(
    r"(?i)^(?:please\s+)?(?:describe|caption|explain|identify|what(?:'|\s+)s\s+in|what\s+is\s+in|"
    r"look\s+at|show\s+me)\s+(.+)$",
)
_EXT_TRY = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic")


def _search_dirs() -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []

    def add(path: Path) -> None:
        p = path.expanduser()
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)

    for chunk in _env("DESCRIBE_IMAGE_SEARCH_DIRS").split(":"):
        if chunk.strip():
            add(Path(chunk.strip()))
    chart = _env("CHART_OUTPUT_DIR") or _env("IMAGE_OUTPUT_DIR")
    if chart:
        add(Path(chart))
    else:
        add(Path.home() / "Pictures" / "arka-generated")
    add(Path.cwd())
    add(Path.home() / "Pictures")
    add(Path.home() / "Downloads")
    add(Path.home() / "Desktop")
    return out


def resolve_image_path(name: str) -> Path:
    """Resolve a path, bare filename, or extensionless chart name to one image file."""
    raw = name.strip().strip("'\"")
    if _is_url(raw):
        raise SystemExit("resolve_image_path called with URL")

    direct = Path(raw).expanduser()
    matches: list[Path] = []

    def add_match(path: Path) -> None:
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            resolved = path.resolve()
            if resolved not in matches:
                matches.append(resolved)

    add_match(direct)
    if not direct.suffix:
        for ext in _EXT_TRY:
            add_match(direct.with_suffix(ext))
    if direct.parent not in {Path("."), Path("")} and str(direct.parent) != ".":
        if not direct.suffix:
            for ext in _EXT_TRY:
                add_match(direct.parent / f"{direct.name}{ext}")

    stem = direct.name
    for directory in _search_dirs():
        if not directory.is_dir():
            continue
        for ext in ("",) + _EXT_TRY:
            candidate = directory / f"{stem}{ext}" if ext or not Path(stem).suffix else directory / stem
            add_match(candidate)
        if not Path(stem).suffix:
            for hit in sorted(directory.glob(f"{stem}*")):
                add_match(hit)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        lines = "\n".join(f"  {p}" for p in matches[:12])
        extra = f"\n  … and {len(matches) - 12} more" if len(matches) > 12 else ""
        raise SystemExit(
            f"Multiple images match '{name}'. Use the full file path:\n{lines}{extra}"
        )

    searched = "\n".join(f"  {d}" for d in _search_dirs() if d.is_dir())
    raise SystemExit(
        f"Image not found: {name}\n"
        f"Searched for {stem} (+ common extensions) in:\n{searched}\n"
        f"Tip: arka describe ~/Pictures/arka-generated/{stem}.png"
    )


def _has_describe_intent(text: str) -> bool:
    if re.search(
        r"(?i)\b(what\s+(?:do\s+)?you\s+think|your\s+(?:thoughts?|opinion|take)|think\s+about|opinion\s+on)\b",
        text,
    ):
        return False
    return bool(
        _DESCRIBE_VERB.match(text.strip())
        or re.search(
            r"(?i)\b(describe|caption|explain|identify|what(?:'|\s+)s\s+in|what\s+is\s+in|"
            r"tell\s+me\s+about|look\s+at|show\s+me)\b",
            text,
        )
    )


_PAGE_URL = re.compile(
    r"(?i)(?:linkedin\.com|twitter\.com|x\.com|facebook\.com|instagram\.com|reddit\.com|"
    r"youtube\.com/watch|youtu\.be/|tiktok\.com|threads\.net|medium\.com/@)"
)


def _is_page_url(url: str) -> bool:
    return bool(_PAGE_URL.search(url))


def _default_prompt_for_source(source: str) -> str:
    stem = Path(source.strip().strip("'\"")).stem
    if _CHART_NAME.search(stem):
        return CHART_PROMPT
    return DEFAULT_PROMPT


def _normalize_nl(text: str) -> str:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t


def parse_describe_request(text: str) -> tuple[str | None, str]:
    t = _normalize_nl(text)
    if not t or _DRAWING_WORDS.search(t):
        return None, DEFAULT_PROMPT

    url_m = re.search(r"(https?://[^\s\"']+)", t, re.I)
    if url_m:
        url = url_m.group(1).rstrip(".,)")
        if _is_page_url(url):
            return None, DEFAULT_PROMPT
        if _has_describe_intent(t):
            question = _strip_describe_words(t, url) or DEFAULT_PROMPT
            return url, question

    m = _DESCRIBE_VERB.match(t)
    if m:
        rest = m.group(1).strip().strip("'\"")
        if rest:
            url_in_rest = re.match(r"(https?://\S+)", rest, re.I)
            if url_in_rest:
                url = url_in_rest.group(1).rstrip(".,)")
                question = rest[len(url_in_rest.group(0)) :].strip() or DEFAULT_PROMPT
                return url, question
            path_m = re.match(
                r"(\S+\.(?:png|jpe?g|webp|gif|bmp|tiff?|heic|svg))(?:\s+(.*))?$",
                rest,
                re.I,
            )
            if path_m:
                q = (path_m.group(2) or "").strip() or _default_prompt_for_source(path_m.group(1))
                return path_m.group(1), q
            parts = rest.split(None, 1)
            name = parts[0]
            question = parts[1].strip() if len(parts) > 1 else _default_prompt_for_source(name)
            return name, question or _default_prompt_for_source(name)

    path_m = re.search(
        r'(?P<q>["\']?)(?P<p>(?:~|/|\./|\.\./)[^\s"\']+|[^\s"\']+\.(?:png|jpe?g|webp|gif|bmp|tiff?|heic|svg))\1',
        t,
        re.I,
    )
    if path_m and _has_describe_intent(t):
        src = path_m.group("p").strip("'\"")
        return src, _strip_describe_words(t, src) or DEFAULT_PROMPT

    return None, DEFAULT_PROMPT


def _looks_like_image_source(text: str) -> bool:
    t = text.strip().strip("'\"")
    if not t or t.startswith("-"):
        return False
    if _is_url(t):
        return True
    ext = Path(t).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return True
    if "/" in t or t.startswith("~") or t.startswith("."):
        return True
    return bool(re.match(r"^[\w.-]+$", t))


def _strip_describe_words(text: str, source: str) -> str:
    t = text.strip()
    t = re.sub(re.escape(source), " ", t, count=1, flags=re.I)
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:describe|caption|explain|identify|what(?:'|\s+)s\s+in|what\s+is\s+in|"
        r"analyze|inspect|look\s+at|tell\s+me\s+about|show\s+me)\s*",
        "",
        t,
    )
    t = re.sub(r"(?i)\b(?:this|the|my|an?)\s+(?:image|photo|picture|pic|screenshot|snapshot)\b", " ", t)
    t = re.sub(r"(?i)\b(?:image|photo|picture|pic|screenshot|snapshot)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,-")
    return t


def nl_to_argv(text: str) -> list[str]:
    source, question = parse_describe_request(_normalize_nl(text))
    if not source:
        return []
    return ["describe", source, question]


def cmd_describe(args: argparse.Namespace) -> int:
    prompt = " ".join(args.prompt).strip() if args.prompt else DEFAULT_PROMPT
    print(describe_source(args.source, prompt))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(_normalize_nl(" ".join(args.text)))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_formats(_args: argparse.Namespace) -> int:
    print("Sources: local path or http(s) URL (extensionless chart names OK)")
    print("Images:", ", ".join(sorted(IMAGE_EXTENSIONS)))
    print("Analysis: two-layer — OCR text map (x%,y%) + vision (layout/colors)")
    print("OCR coords: tesseract TSV — DESCRIBE_IMAGE_OCR_COORDS=1")
    print("Chart PNGs: .json sidecar + structured visual (colors from palette, not LLM)")
    print("Env: DESCRIBE_IMAGE_CHART_VISUAL=auto|structured|vision")
    print("Requires: Pillow")
    print("Env: DESCRIBE_IMAGE_TWO_LAYER=1, DESCRIBE_IMAGE_OCR=1, GEMINI_API_KEY, VLLM_START_CMD")
    print("Search dirs: CHART_OUTPUT_DIR, ~/Pictures/arka-generated, cwd, Downloads")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Describe an image using local vLLM vision")
    sub = p.add_subparsers(dest="cmd")

    p_desc = sub.add_parser("describe", help="Describe an image file or URL")
    p_desc.add_argument("source", help="Image path or http(s) URL")
    p_desc.add_argument("prompt", nargs="*", help="Optional question (default: describe in detail)")
    p_desc.set_defaults(func=cmd_describe)

    p_parse = sub.add_parser("parse", help="Parse natural language → describe_image args (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    sub.add_parser("formats", help="Supported inputs").set_defaults(func=cmd_formats)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _KNOWN_CMDS:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        elif _looks_like_image_source(argv[0]):
            argv = ["describe", *argv]
        else:
            print("Could not parse image describe request. Try:", file=sys.stderr)
            print('  describe_image photo.jpg', file=sys.stderr)
            print('  describe_image https://example.com/cat.png "what breed is this?"', file=sys.stderr)
            print('  arka describe ~/Pictures/screenshot.png', file=sys.stderr)
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
