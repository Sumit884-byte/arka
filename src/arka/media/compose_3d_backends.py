"""Free and optional paid 3D generation backends for compose_3d."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

BACKEND_SLUGS = (
    "auto",
    "procedural",
    "shap-e",
    "hf-shap-e",
    "tripo",
    "meshy",
    "openscad",
    "llm",
)

_TRIPO_BASE = "https://api.tripo3d.ai/v2/openapi/task"
_MESHY_BASE = "https://api.meshy.ai/openapi/v2/text-to-3d"
_DEFAULT_HF_SPACE = "hysts/Shap-E"
_POLL_INTERVAL = 3.0
_MAX_POLL_SECONDS = 600.0


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _hf_token() -> str:
    return _env("HF_TOKEN") or _env("HUGGINGFACE_API_KEY") or _env("HF_API_KEY")


def _tripo_key() -> str:
    return _env("TRIPO_API_KEY") or _env("TRIPO3D_API_KEY")


def _meshy_key() -> str:
    return _env("MESHY_API_KEY")


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> Any:
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error calling {url}: {exc.reason}") from exc


def _download_url(url: str, dest: Path, *, headers: dict[str, str] | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            dest.write_bytes(resp.read())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download {url}: {exc.reason}") from exc
    return dest


def _space_subdomain(space_id: str) -> str:
    owner, name = space_id.split("/", 1)
    return f"{owner.lower()}-{name.lower().replace('_', '-')}"


def _has_local_shap_e() -> bool:
    try:
        import torch  # noqa: F401
        from diffusers import ShapEPipeline  # noqa: F401
    except ImportError:
        return False
    return True


def _has_gradio_client() -> bool:
    try:
        import gradio_client  # noqa: F401
    except ImportError:
        return False
    return True


def _openscad_available() -> bool:
    return shutil.which("openscad") is not None


@dataclass(frozen=True)
class BackendInfo:
    slug: str
    label: str
    available: bool
    detail: str
    env_vars: tuple[str, ...] = ()


@dataclass
class GeneratedMesh:
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    method: str
    source_file: Path | None = None


def backend_catalog() -> list[BackendInfo]:
    tripo_ok = bool(_tripo_key())
    meshy_ok = bool(_meshy_key())
    hf_ok = _has_gradio_client() or bool(_hf_token())
    shap_ok = _has_local_shap_e()
    openscad_ok = _openscad_available()
    llm_ok = False
    try:
        from arka.media.compose_3d import _any_llm_available

        llm_ok = _any_llm_available()
    except ImportError:
        pass

    return [
        BackendInfo("procedural", "Procedural templates", True, "always available"),
        BackendInfo(
            "shap-e",
            "Local Shap-E (OpenAI)",
            shap_ok,
            "pip install -e '.[3d-ai]' + CUDA/CPU PyTorch" if not shap_ok else "torch + diffusers installed",
            ("SHAP_E_DEVICE",),
        ),
        BackendInfo(
            "hf-shap-e",
            "HuggingFace Shap-E Space",
            hf_ok,
            "HF_TOKEN set or gradio_client installed" if hf_ok else "set HF_TOKEN or pip install gradio_client",
            ("HF_TOKEN", "HF_SHAP_E_SPACE"),
        ),
        BackendInfo(
            "tripo",
            "Tripo AI API",
            tripo_ok,
            "300 free credits on signup" if tripo_ok else "set TRIPO_API_KEY (free tier at platform.tripo3d.ai)",
            ("TRIPO_API_KEY",),
        ),
        BackendInfo(
            "meshy",
            "Meshy API",
            meshy_ok,
            "API key set (Pro+ plan required for API)" if meshy_ok else "set MESHY_API_KEY (Pro tier for API)",
            ("MESHY_API_KEY",),
        ),
        BackendInfo(
            "openscad",
            "OpenSCAD + LLM",
            openscad_ok and llm_ok,
            "openscad on PATH + LLM configured"
            if openscad_ok and llm_ok
            else "install openscad and configure an LLM",
            (),
        ),
        BackendInfo(
            "llm",
            "LLM OBJ fallback",
            llm_ok,
            "LLM configured in .env" if llm_ok else "add GEMINI_API_KEY or GROQ_API_KEY",
            ("GEMINI_API_KEY", "GROQ_API_KEY"),
        ),
    ]


def auto_backend_order(*, prefer_procedural: bool = False) -> list[str]:
    if prefer_procedural:
        return ["procedural"]
    order: list[str] = []
    if _has_local_shap_e():
        order.append("shap-e")
    if _tripo_key():
        order.append("tripo")
    if _has_gradio_client() or _hf_token():
        order.append("hf-shap-e")
    if _meshy_key():
        order.append("meshy")
    if _openscad_available():
        order.append("openscad")
    order.append("llm")
    return order


def _load_mesh_file(path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    suffix = path.suffix.lower()
    if suffix == ".obj":
        from arka.media.compose_3d import parse_obj

        return parse_obj(path.read_text(encoding="utf-8"))
    if suffix in {".glb", ".stl", ".ply"}:
        try:
            import trimesh

            mesh = trimesh.load(path, force="mesh")
            if isinstance(mesh, trimesh.Scene):
                mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
            from arka.media.compose_3d import _trimesh_to_raw

            return _trimesh_to_raw(mesh)
        except ImportError as exc:
            raise RuntimeError(
                f"Downloaded {suffix} requires trimesh — pip install -e '.[3d]'"
            ) from exc
    raise RuntimeError(f"Unsupported mesh format: {path.suffix}")


def _generate_shap_e_local(prompt: str, out_dir: Path) -> GeneratedMesh:
    import torch
    from diffusers import ShapEPipeline
    from diffusers.utils import export_to_ply

    device_name = _env("SHAP_E_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(device_name)
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    pipe = ShapEPipeline.from_pretrained("openai/shap-e", torch_dtype=dtype)
    pipe = pipe.to(device)
    guidance = float(_env("SHAP_E_GUIDANCE", "15.0") or "15.0")
    steps = int(_env("SHAP_E_STEPS", "64") or "64")
    result = pipe(
        prompt,
        guidance_scale=guidance,
        num_inference_steps=steps,
        frame_size=256,
        output_type="mesh",
    )
    mesh = result.images[0]
    ply_path = out_dir / "shap_e.ply"
    export_to_ply(mesh, str(ply_path))
    vertices, faces = _load_mesh_file(ply_path)
    return GeneratedMesh(vertices, faces, "local Shap-E", ply_path)


def _gradio_space_generate(prompt: str, out_dir: Path) -> Path:
    space = _env("HF_SHAP_E_SPACE", _DEFAULT_HF_SPACE) or _DEFAULT_HF_SPACE
    if _has_gradio_client():
        from gradio_client import Client

        token = _hf_token() or None
        client = Client(space, hf_token=token)
        seed = 0
        guidance = float(_env("SHAP_E_GUIDANCE", "15.0") or "15.0")
        steps = int(_env("SHAP_E_STEPS", "50") or "50")
        result = client.predict(prompt, seed, guidance, steps, api_name="/text_to_3d")
        if isinstance(result, (str, Path)):
            src = Path(result)
            if src.is_file():
                dest = out_dir / src.name
                shutil.copy2(src, dest)
                return dest
        if isinstance(result, tuple) and result:
            first = result[0]
            if isinstance(first, (str, Path)) and Path(first).is_file():
                dest = out_dir / Path(first).name
                shutil.copy2(first, dest)
                return dest
        raise RuntimeError(f"Unexpected Gradio result type: {type(result)!r}")

    subdomain = _space_subdomain(space)
    base = f"https://{subdomain}.hf.space"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = _hf_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    seed = 0
    guidance = float(_env("SHAP_E_GUIDANCE", "15.0") or "15.0")
    steps = int(_env("SHAP_E_STEPS", "50") or "50")
    for api_name in ("/text_to_3d", "/predict", "text_to_3d"):
        try:
            submit = _http_json(
                "POST",
                f"{base}/gradio_api/call{api_name if api_name.startswith('/') else '/' + api_name}",
                headers=headers,
                body={"data": [prompt, seed, guidance, steps]},
                timeout=30.0,
            )
            event_id = submit.get("event_id")
            if not event_id:
                continue
            deadline = time.time() + _MAX_POLL_SECONDS
            while time.time() < deadline:
                poll_url = (
                    f"{base}/gradio_api/call{api_name if api_name.startswith('/') else '/' + api_name}/{event_id}"
                )
                req = urllib.request.Request(poll_url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    chunk = resp.read().decode("utf-8", errors="replace")
                if "error" in chunk.lower() and "event_id" not in chunk:
                    break
                for line in chunk.splitlines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, list) and parsed:
                        candidate = parsed[0]
                        if isinstance(candidate, str) and candidate.startswith("http"):
                            dest = out_dir / "hf_shap_e.obj"
                            _download_url(candidate, dest, headers=headers)
                            return dest
                        if isinstance(candidate, str) and Path(candidate).suffix:
                            dest = out_dir / Path(candidate).name
                            _download_url(candidate, dest, headers=headers)
                            return dest
                time.sleep(_POLL_INTERVAL)
        except RuntimeError:
            continue
    raise RuntimeError(
        "HF Shap-E space call failed — set HF_TOKEN and/or pip install gradio_client (pip install -e '.[3d-ai]')"
    )


def _generate_hf_shap_e(prompt: str, out_dir: Path) -> GeneratedMesh:
    path = _gradio_space_generate(prompt, out_dir)
    vertices, faces = _load_mesh_file(path)
    return GeneratedMesh(vertices, faces, "HuggingFace Shap-E Space", path)


def _poll_tripo_task(task_id: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {_tripo_key()}", "Content-Type": "application/json"}
    deadline = time.time() + _MAX_POLL_SECONDS
    while time.time() < deadline:
        payload = _http_json("GET", f"{_TRIPO_BASE}/{task_id}", headers=headers, timeout=30.0)
        data = payload.get("data") or payload
        status = (data.get("status") or "").lower()
        if status == "success":
            return data
        if status in {"failed", "banned", "expired", "cancelled"}:
            raise RuntimeError(f"Tripo task {status}: {data.get('error_msg') or data}")
        time.sleep(_POLL_INTERVAL)
    raise RuntimeError("Tripo task timed out")


def _generate_tripo(prompt: str, out_dir: Path) -> GeneratedMesh:
    key = _tripo_key()
    if not key:
        raise RuntimeError("TRIPO_API_KEY not set — sign up at https://platform.tripo3d.ai (300 free credits)")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "type": "text_to_model",
        "prompt": prompt,
    }
    texture = _env("TRIPO_TEXTURE", "0").lower() not in {"0", "false", "no", "off"}
    if texture:
        body["texture"] = True
    create = _http_json("POST", _TRIPO_BASE, headers=headers, body=body, timeout=60.0)
    data = create.get("data") or create
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"Tripo did not return task_id: {create}")
    result = _poll_tripo_task(task_id)
    output = result.get("output") or {}
    model_url = output.get("model") or output.get("pbr_model") or output.get("base_model")
    if not model_url:
        raise RuntimeError(f"Tripo success but no model URL in output: {output}")
    ext = ".glb"
    for candidate in (".obj", ".glb", ".fbx"):
        if candidate in model_url.lower():
            ext = candidate
            break
    dest = out_dir / f"tripo{ext}"
    _download_url(model_url, dest)
    vertices, faces = _load_mesh_file(dest)
    return GeneratedMesh(vertices, faces, "Tripo AI API", dest)


def _poll_meshy_task(task_id: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {_meshy_key()}"}
    deadline = time.time() + _MAX_POLL_SECONDS
    while time.time() < deadline:
        payload = _http_json("GET", f"{_MESHY_BASE}/{task_id}", headers=headers, timeout=30.0)
        status = (payload.get("status") or "").upper()
        if status == "SUCCEEDED":
            return payload
        if status == "FAILED":
            err = payload.get("task_error") or {}
            raise RuntimeError(f"Meshy task failed: {err.get('message') or payload}")
        time.sleep(_POLL_INTERVAL)
    raise RuntimeError("Meshy task timed out")


def _meshy_model_url(task: dict[str, Any]) -> str:
    urls = task.get("model_urls") or {}
    for key in ("obj", "glb", "stl"):
        url = urls.get(key)
        if url:
            return url
    raise RuntimeError(f"Meshy task succeeded but no model URL: {task}")


def _generate_meshy(prompt: str, out_dir: Path) -> GeneratedMesh:
    key = _meshy_key()
    if not key:
        raise RuntimeError("MESHY_API_KEY not set — API requires Meshy Pro+ (web free tier is UI-only)")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    preview = _http_json(
        "POST",
        _MESHY_BASE,
        headers=headers,
        body={"mode": "preview", "prompt": prompt, "should_remesh": True},
        timeout=60.0,
    )
    preview_id = preview.get("result")
    if not preview_id:
        raise RuntimeError(f"Meshy preview failed: {preview}")
    _poll_meshy_task(preview_id)
    refine = _http_json(
        "POST",
        _MESHY_BASE,
        headers=headers,
        body={"mode": "refine", "preview_task_id": preview_id, "enable_pbr": True},
        timeout=60.0,
    )
    refine_id = refine.get("result")
    if not refine_id:
        raise RuntimeError(f"Meshy refine failed: {refine}")
    task = _poll_meshy_task(refine_id)
    url = _meshy_model_url(task)
    ext = ".obj" if url.lower().endswith(".obj") else ".glb"
    dest = out_dir / f"meshy{ext}"
    _download_url(url, dest)
    vertices, faces = _load_mesh_file(dest)
    return GeneratedMesh(vertices, faces, "Meshy API", dest)


def _generate_openscad(prompt: str, out_dir: Path) -> GeneratedMesh:
    if not _openscad_available():
        raise RuntimeError("openscad not found on PATH — install from https://openscad.org")
    from arka.llm.cli import llm_complete

    scad = llm_complete(
        system=(
            "You are an OpenSCAD expert. Output ONLY valid OpenSCAD code for a printable 3D model. "
            "No markdown fences or explanations. Use union/difference/hull; keep under 200 lines."
        ),
        user=f"Create OpenSCAD for: {prompt}",
        temperature=0.2,
        task="create_3d_model",
        skill="compose_3d",
    )
    scad = re.sub(r"^```(?:scad|openscad)?\s*|\s*```$", "", scad.strip(), flags=re.I | re.M)
    scad_path = out_dir / "generated.scad"
    stl_path = out_dir / "openscad.stl"
    scad_path.write_text(scad + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["openscad", "-o", str(stl_path), str(scad_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not stl_path.is_file():
        raise RuntimeError(f"OpenSCAD failed: {proc.stderr.strip() or proc.stdout.strip()}")
    vertices, faces = _load_mesh_file(stl_path)
    return GeneratedMesh(vertices, faces, "OpenSCAD + LLM", stl_path)


_GENERATORS: dict[str, Callable[[str, Path], GeneratedMesh]] = {
    "shap-e": _generate_shap_e_local,
    "hf-shap-e": _generate_hf_shap_e,
    "tripo": _generate_tripo,
    "meshy": _generate_meshy,
    "openscad": _generate_openscad,
}


def generate_with_backend(
    prompt: str,
    backend: str,
    out_dir: Path,
    *,
    prefer_procedural: bool = False,
) -> GeneratedMesh:
    slug = (backend or "auto").strip().lower()
    if slug == "procedural":
        raise RuntimeError("procedural backend is handled by compose_3d templates")
    if slug == "llm":
        raise RuntimeError("llm backend is handled by compose_3d LLM OBJ path")

    backends = [slug] if slug != "auto" else auto_backend_order(prefer_procedural=prefer_procedural)
    errors: list[str] = []
    for name in backends:
        fn = _GENERATORS.get(name)
        if fn is None:
            continue
        try:
            print(f"Trying 3D backend: {name} …", file=sys.stderr)
            return fn(prompt, out_dir)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"  {name} unavailable — {exc}", file=sys.stderr)
    joined = "; ".join(errors) if errors else "no backends configured"
    raise RuntimeError(f"All 3D backends failed ({joined})")
