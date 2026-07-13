#!/usr/bin/env python3
"""PrivateGPT document RAG wrapper for Arka (PDF, Office, text, code, and more)."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8080"
DEFAULT_COLLECTION = "pgpt_collection"
DEFAULT_HOME = Path.home() / "Projects" / "private-gpt"
CACHE_DIR = Path.home() / ".cache" / "fish-agent"
PID_FILE = CACHE_DIR / "privategpt.pid"
LOG_FILE = CACHE_DIR / "privategpt.log"
SYNC_MARKER = CACHE_DIR / "privategpt_synced"
HEALTH_POLL = 0.5
QDRANT_CONTAINER = "arka-qdrant"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"

# Formats PrivateGPT ingests natively (see private_gpt/components/readers/registry.py)
PGPT_NATIVE_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".pptx", ".docx", ".xlsx", ".xls", ".md", ".html", ".htm",
    ".xhtml", ".xht", ".shtml", ".shtm", ".stm", ".txt", ".csv", ".tsv", ".psv", ".eml",
})

# Text/code formats: extract locally and ingest as plain text
TEXT_EXTRACT_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".fish", ".sh", ".bash", ".zsh",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sql",
    ".rs", ".go", ".java", ".kt", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".css", ".scss", ".less", ".xml", ".tex", ".rst", ".log", ".mdx",
    ".rb", ".php", ".swift", ".lua", ".vim", ".dockerfile", ".gradle",
    ".properties", ".env", ".gitignore", ".csv", ".tsv",
})

MAX_TEXT_BYTES = 8 * 1024 * 1024


def supported_extensions() -> frozenset[str]:
    return PGPT_NATIVE_EXTENSIONS | TEXT_EXTRACT_EXTENSIONS


def extension_pattern() -> str:
    parts = sorted({ext.lstrip(".") for ext in supported_extensions()}, key=len, reverse=True)
    return "|".join(re.escape(p) for p in parts)


def _file_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PGPT_NATIVE_EXTENSIONS:
        return "native"
    if ext in TEXT_EXTRACT_EXTENSIONS:
        return "text"
    if not ext:
        return "probe"
    return "unknown"


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data[:4096]:
        return False
    sample = data[:8192]
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError(f"File too large for text ingest ({len(raw)} bytes, max {MAX_TEXT_BYTES})")
    if not _looks_like_text(raw):
        raise ValueError(f"File does not look like UTF-8 text: {path.name}")
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError(f"File is empty: {path.name}")
    header = f"# Source file: {path.name}\n\n"
    return header + text


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def quiet_status() -> bool:
    return env("PDF_QUIET") == "1"


def status_msg(msg: str) -> None:
    if not quiet_status():
        print(msg, file=sys.stderr)


def base_url() -> str:
    return (env("PDF_RAG_URL") or env("PRIVATEGPT_URL") or DEFAULT_URL).rstrip("/")


def collection() -> str:
    return env("PDF_COLLECTION") or env("PRIVATEGPT_COLLECTION") or DEFAULT_COLLECTION


def privategpt_home() -> Path:
    raw = env("PRIVATEGPT_HOME") or env("PRIVATEGPT_HOME")
    return Path(raw).expanduser() if raw else DEFAULT_HOME


def auto_start_enabled() -> bool:
    value = env("PDF_RAG_AUTO_START", "1").lower()
    return value not in {"0", "false", "no", "off"}


def start_timeout() -> float:
    raw = env("PDF_RAG_START_TIMEOUT", "120")
    try:
        return max(10.0, float(raw))
    except ValueError:
        return 120.0


def url_host_port() -> tuple[str, int]:
    parsed = urllib.parse.urlparse(base_url())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 8080)
    return host, port


def auth_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "arka-pdf-rag/1.0",
    }
    secret = env("PRIVATEGPT_AUTH") or env("PDF_RAG_AUTH")
    if not secret:
        return headers
    if not secret.lower().startswith("basic "):
        if ":" in secret and not secret.startswith("Basic "):
            secret = "Basic " + base64.b64encode(secret.encode()).decode()
        elif ":" not in secret:
            secret = f"Basic {secret}"
    headers["Authorization"] = secret
    return headers


def api_request(
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 300,
) -> tuple[int, object]:
    url = f"{base_url()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=auth_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw}
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc.reason)}
    except Exception as exc:
        return 0, {"error": str(exc)}


def is_up() -> bool:
    status, _ = api_request("GET", "/health", timeout=5)
    if status == 200:
        return True
    status, _ = api_request(
        "GET",
        f"/v1/artifacts/list?collection={urllib.parse.quote(collection())}",
        timeout=5,
    )
    return status == 200


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


def _find_serve_cmd(port: int) -> tuple[list[str], Path | None]:
    home = privategpt_home()
    host, _ = url_host_port()
    serve_args = ["serve", "--host", host, "--port", str(port)]

    if shutil.which("uv") and home.is_dir() and (home / "pyproject.toml").is_file():
        return ["uv", "run", "private-gpt", *serve_args], home

    if bin_path := shutil.which("private-gpt"):
        return [bin_path, *serve_args], None

    venv_bin = home / ".venv" / "bin" / "private-gpt"
    if venv_bin.is_file():
        return [str(venv_bin), *serve_args], home

    if shutil.which("uv"):
        return ["uv", "tool", "run", "private-gpt", *serve_args], None

    return [], None


def _qdrant_url() -> str:
    return env("PGPT_QDRANT_URL") or env("QDRANT_URL") or DEFAULT_QDRANT_URL


def _qdrant_is_up() -> bool:
    url = _qdrant_url().rstrip("/") + "/"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status < 500
    except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError):
        return False


def _ensure_qdrant() -> bool:
    if _qdrant_is_up():
        return True
    if env("QDRANT_AUTO_START", "1").lower() in {"0", "false", "no", "off"}:
        return False
    if not shutil.which("docker"):
        print("Qdrant is not running and docker is unavailable.", file=sys.stderr)
        return False

    print(f"Starting Qdrant ({QDRANT_CONTAINER})…", file=sys.stderr)
    started = subprocess.run(
        ["docker", "start", QDRANT_CONTAINER],
        capture_output=True,
        text=True,
    )
    if started.returncode != 0:
        created = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                QDRANT_CONTAINER,
                "-p",
                "6333:6333",
                "-v",
                f"{QDRANT_CONTAINER}-data:/qdrant/storage",
                "qdrant/qdrant:latest",
            ],
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            print(created.stderr or created.stdout, file=sys.stderr)
            return False

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _qdrant_is_up():
            return True
        time.sleep(HEALTH_POLL)
    print("Qdrant did not become ready in time.", file=sys.stderr)
    return False


def _serve_env() -> dict[str, str]:
    run_env = os.environ.copy()
    if not run_env.get("PGPT_QDRANT_URL"):
        run_env["PGPT_QDRANT_URL"] = _qdrant_url()

    override_dir = Path.home() / ".config" / "fish" / "privategpt"
    pkg_override = Path(__file__).resolve().parent / "privategpt"
    settings_folders = [str(override_dir), str(pkg_override), str(privategpt_home())]
    if existing := run_env.get("PGPT_SETTINGS_FOLDER"):
        settings_folders.append(existing)
    run_env["PGPT_SETTINGS_FOLDER"] = ",".join(settings_folders)

    ollama_host = run_env.get("OLLAMA_HOST", "127.0.0.1:11434")
    if not ollama_host.startswith("http"):
        ollama_host = f"http://{ollama_host}"
    ollama_base = ollama_host.rstrip("/") + "/v1"
    run_env.setdefault("OPENAI_API_BASE", ollama_base)
    run_env.setdefault("OPENAI_EMBEDDING_API_BASE", ollama_base)
    run_env.setdefault("OPENAI_API_KEY", run_env.get("OLLAMA_API_KEY", "ollama"))
    return run_env


def _stop_server() -> None:
    pid = _read_pid()
    if pid is None:
        try:
            pid = int(PID_FILE.read_text().strip())
        except (OSError, ValueError):
            pid = None
    if pid is not None and _pid_alive(pid):
        try:
            os.killpg(pid, 15)
            time.sleep(1)
        except OSError:
            pass
    subprocess.run(["pkill", "-f", "private-gpt serve"], capture_output=True)
    PID_FILE.unlink(missing_ok=True)
    time.sleep(1)


def _ensure_deps() -> bool:
    if SYNC_MARKER.exists():
        return True
    home = privategpt_home()
    if not shutil.which("uv") or not (home / "pyproject.toml").is_file():
        return True

    extra = env("PRIVATEGPT_EXTRA", "core")
    print(
        f"Installing PrivateGPT dependencies (uv sync --extra {extra}; first run may take several minutes)…",
        file=sys.stderr,
    )
    proc = subprocess.run(
        ["uv", "sync", "--extra", extra],
        cwd=str(home),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
        return False
    SYNC_MARKER.write_text(str(home))
    return True


def _wait_for_server(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_up():
            return True
        time.sleep(HEALTH_POLL)
    return False


def ensure_server(*, auto_start: bool, force_restart: bool = False) -> bool:
    if is_up() and not force_restart:
        return True

    if is_up() and force_restart:
        _stop_server()

    if not auto_start or not auto_start_enabled():
        return False

    if _read_pid() is not None and not force_restart:
        print("Waiting for PrivateGPT to become ready…", file=sys.stderr)
        if _wait_for_server(start_timeout()):
            return True
        print("PrivateGPT process exists but server is not responding.", file=sys.stderr)
        _stop_server()

    if not _ensure_qdrant():
        print("Warning: continuing without Qdrant server (ingest may fail).", file=sys.stderr)

    host, port = url_host_port()
    cmd, cwd = _find_serve_cmd(port)
    if not cmd:
        print("Cannot find private-gpt. Set ARKA_PRIVATEGPT_HOME or install private-gpt.", file=sys.stderr)
        return False

    if not _ensure_deps():
        return False

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Starting PrivateGPT ({' '.join(cmd)})…", file=sys.stderr)
    print(f"Logs: {LOG_FILE}", file=sys.stderr)

    try:
        with LOG_FILE.open("ab") as log:
            proc = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=log,
                start_new_session=True,
                cwd=str(cwd) if cwd else None,
                env=_serve_env(),
            )
        PID_FILE.write_text(str(proc.pid))
    except OSError as exc:
        print(f"Failed to start PrivateGPT: {exc}", file=sys.stderr)
        return False

    if _wait_for_server(start_timeout()):
        print(f"PrivateGPT is ready at {base_url()}", file=sys.stderr)
        return True

    print(
        f"PrivateGPT did not respond within {int(start_timeout())}s. Check {LOG_FILE}",
        file=sys.stderr,
    )
    return False


def list_documents() -> list[dict]:
    status, data = api_request(
        "GET",
        f"/v1/artifacts/list?collection={urllib.parse.quote(collection())}",
    )
    if status != 200 or not isinstance(data, dict):
        return []
    docs = data.get("data")
    return docs if isinstance(docs, list) else []


def _doc_names(item: dict) -> tuple[str, str]:
    meta = item.get("doc_metadata") if isinstance(item.get("doc_metadata"), dict) else {}
    file_name = str(meta.get("file_name") or item.get("artifact") or "")
    artifact = str(item.get("artifact") or sanitize_id(file_name))
    return artifact, file_name


def resolve_document(ref: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (artifact_id, file_name, error)."""
    if not ref or not str(ref).strip():
        return None, None, None

    needle = str(ref).strip().strip("'\"")
    needle_lower = needle.lower()
    docs = list_documents()
    if not docs:
        return None, None, "No ingested documents."

    exact: list[tuple[str, str]] = []
    partial: list[tuple[str, str]] = []
    for item in docs:
        if not isinstance(item, dict):
            continue
        artifact, file_name = _doc_names(item)
        file_lower = file_name.lower()
        stem_lower = Path(file_name).stem.lower()
        artifact_lower = artifact.lower()
        if needle_lower in {artifact_lower, file_lower, stem_lower}:
            exact.append((artifact, file_name))
            continue
        if (
            needle_lower in file_lower
            or needle_lower in stem_lower
            or needle_lower in artifact_lower
            or file_lower in needle_lower
            or stem_lower in needle_lower
        ):
            partial.append((artifact, file_name))

    if len(exact) == 1:
        return exact[0][0], exact[0][1], None
    if len(exact) > 1:
        names = ", ".join(name for _, name in exact)
        return None, None, f"Ambiguous document '{ref}'. Matches: {names}"

    if len(partial) == 1:
        return partial[0][0], partial[0][1], None
    if len(partial) > 1:
        names = ", ".join(name for _, name in partial[:5])
        return None, None, f"Ambiguous document '{ref}'. Did you mean: {names}"

    available = ", ".join(_doc_names(item)[1] for item in docs if isinstance(item, dict))
    return None, None, f"Unknown document '{ref}'. Available: {available}"


def context_filter(artifact: str | None = None) -> dict:
    filt: dict = {"collection": collection()}
    if artifact:
        filt["artifacts"] = [artifact]
    return filt


def sanitize_id(name: str) -> str:
    stem = Path(name).stem
    clean = re.sub(r"[^\w\-]+", "-", stem.lower()).strip("-")
    return clean or "document"


def _turboquant_rag():
    from arka.stock.turboquant_rag import use_turboquant

    return use_turboquant()


def _extract_document_text(path: Path) -> str | None:
    kind = _file_kind(path)
    if kind == "text" or kind == "probe":
        try:
            return _read_text_file(path)
        except ValueError:
            return None
    if kind == "native":
        ext = path.suffix.lower()
        if ext == ".pdf":
            from arka.stock.turboquant_rag import extract_pdf_text

            return extract_pdf_text(path)
        if ext == ".docx":
            from arka.stock.turboquant_rag import extract_docx_text

            return extract_docx_text(path)
        if ext in {".txt", ".md", ".csv", ".html", ".htm"}:
            try:
                return _read_text_file(path)
            except ValueError:
                return None
    return None


def _index_document_turboquant(path: Path, text: str | None = None) -> tuple[bool, str]:
    from arka.stock.turboquant_rag import index_document_text

    artifact = sanitize_id(path.name)
    if text is None:
        text = _extract_document_text(path)
    if not text:
        return False, "no extractable text"
    ok, detail = index_document_text(artifact, path.name, text)
    return ok, detail


def _list_turboquant_documents() -> list[dict]:
    try:
        from arka.stock.turboquant_rag import list_indexed_documents

        return list_indexed_documents()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        return []


def _resolve_turboquant_document(ref: str | None) -> tuple[str | None, str | None, str | None]:
    from arka.stock.turboquant_rag import resolve_indexed_document

    return resolve_indexed_document(ref)


def format_error(data: object) -> str:
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        if "error" in data:
            return str(data["error"])
    return str(data)


def cmd_status() -> int:
    tq_docs = _list_turboquant_documents() if _turboquant_rag() else []
    if _turboquant_rag():
        print("RAG backend: TurboQuant (Ollama embeddings)")
        print(f"Indexed documents: {len(tq_docs)}")
        for item in tq_docs[:20]:
            print(f"  • {item.get('file_name') or item.get('artifact')}")
        if len(tq_docs) > 20:
            print(f"  … and {len(tq_docs) - 20} more")

    url = base_url()
    col = collection()
    if not is_up():
        if _turboquant_rag() and tq_docs:
            return 0
        print(f"PrivateGPT is not reachable at {url}")
        print("Start it with: cd ~/Projects/private-gpt && private-gpt serve")
        print("Or: uv tool run private-gpt serve")
        return 1
    docs = list_documents()
    print(f"PrivateGPT: online ({url})")
    print(f"Collection: {col}")
    print(f"Documents: {len(docs)}")
    for item in docs[:20]:
        meta = item.get("doc_metadata") if isinstance(item, dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        name = meta.get("file_name") or (item.get("artifact") if isinstance(item, dict) else "?")
        print(f"  • {name}")
    if len(docs) > 20:
        print(f"  … and {len(docs) - 20} more")
    return 0


def cmd_list() -> int:
    if _turboquant_rag():
        docs = _list_turboquant_documents()
        if docs:
            for item in docs:
                print(f"{item.get('artifact')}\t{item.get('file_name') or item.get('artifact')}")
            return 0
    if not is_up():
        print("PrivateGPT is not running.", file=sys.stderr)
        return 1
    docs = list_documents()
    if not docs:
        print("No ingested documents.")
        return 0
    for item in docs:
        if not isinstance(item, dict):
            continue
        meta = item.get("doc_metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        name = meta.get("file_name") or item.get("artifact") or "?"
        artifact = item.get("artifact") or "?"
        print(f"{name}\t{artifact}")
    return 0


def _is_qdrant_lock_error(data: object) -> bool:
    return "already accessed by another instance" in format_error(data).lower()


def _ingest_file_bytes(path: Path) -> tuple[int, str]:
    artifact = sanitize_id(path.name)
    body = {
        "artifact": artifact,
        "collection": collection(),
        "input": {"type": "file", "value": base64.b64encode(path.read_bytes()).decode("ascii")},
        "metadata": {"file_name": path.name},
    }
    print(f"Ingesting {path.name} as '{artifact}'…", file=sys.stderr)
    status, data = api_request("POST", "/v1/artifacts/ingest", body, timeout=900)
    if status == 200:
        return 0, artifact
    return status, format_error(data)


def _ingest_text_content(text: str, file_name: str) -> tuple[int, str]:
    artifact = sanitize_id(file_name)
    body = {
        "artifact": artifact,
        "collection": collection(),
        "input": {"type": "text", "value": text},
        "metadata": {"file_name": file_name},
    }
    print(f"Ingesting text from {file_name} as '{artifact}'…", file=sys.stderr)
    status, data = api_request("POST", "/v1/artifacts/ingest", body, timeout=900)
    if status == 200:
        return 0, artifact
    return status, format_error(data)


def _ingest_path(path: Path) -> tuple[int, str]:
    kind = _file_kind(path)
    if kind == "native":
        return _ingest_file_bytes(path)
    if kind == "text":
        return _ingest_text_content(_read_text_file(path), path.name)
    if kind == "probe":
        try:
            return _ingest_text_content(_read_text_file(path), path.name)
        except ValueError as exc:
            return 400, str(exc)
    exts = ", ".join(sorted(supported_extensions()))
    return 400, f"Unsupported format '{path.suffix}'. Supported: {exts}"


def cmd_formats() -> int:
    print("Native (PrivateGPT):", ", ".join(sorted(PGPT_NATIVE_EXTENSIONS)))
    print("Text/code (local extract):", ", ".join(sorted(TEXT_EXTRACT_EXTENSIONS - PGPT_NATIVE_EXTENSIONS)))
    return 0


def cmd_ingest(path: str) -> int:
    doc = Path(path).expanduser().resolve()
    if not doc.is_file():
        print(f"Not a file: {doc}", file=sys.stderr)
        return 1

    tq_ok = False
    tq_detail = ""
    if _turboquant_rag():
        status_msg("Indexing with TurboQuant…")
        tq_ok, tq_detail = _index_document_turboquant(doc)
        if tq_ok:
            status_msg(f"TurboQuant: {tq_detail}")
        else:
            status_msg(f"TurboQuant index skipped: {tq_detail}")

    pgpt_wanted = env("PDF_RAG_PGPT", "1").lower() not in {"0", "false", "no", "off"}
    if not pgpt_wanted:
        if tq_ok:
            print(f"✓ Indexed {doc.name} (TurboQuant: {tq_detail})")
            return 0
        print(f"Ingest failed: {tq_detail or 'could not index document'}", file=sys.stderr)
        return 1

    if not is_up():
        if not ensure_server(auto_start=True):
            if tq_ok:
                print(f"✓ Indexed {doc.name} (TurboQuant: {tq_detail}; PrivateGPT offline)")
                return 0
            print(f"PrivateGPT is not running at {base_url()}.", file=sys.stderr)
            print("Start it with: private-gpt serve", file=sys.stderr)
            return 1

    for attempt in range(2):
        status, result = _ingest_path(doc)
        if status == 0:
            if tq_ok:
                print(f"✓ Ingested {doc.name} (artifact: {result}, TurboQuant: {tq_detail})")
            else:
                print(f"✓ Ingested {doc.name} (artifact: {result})")
            return 0
        if attempt == 0 and _is_qdrant_lock_error(result):
            print("Restarting PrivateGPT with Qdrant server…", file=sys.stderr)
            if not ensure_server(auto_start=True, force_restart=True):
                if tq_ok:
                    print(f"✓ Indexed {doc.name} (TurboQuant: {tq_detail}; PrivateGPT failed)")
                    return 0
                print(f"Ingest failed ({status}): {result}", file=sys.stderr)
                return 1
            continue
        if tq_ok:
            print(f"✓ Indexed {doc.name} (TurboQuant: {tq_detail}; PrivateGPT: {result})")
            return 0
        print(f"Ingest failed ({status}): {result}", file=sys.stderr)
        return 1
    return 1


def extract_answer(data: dict) -> str:
    parts: list[str] = []
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = str(block.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def extract_search_context(data: dict) -> str:
    parts: list[str] = []
    for block in data.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "source":
            for src in block.get("sources") or []:
                if isinstance(src, dict) and src.get("text"):
                    parts.append(str(src["text"]).strip())
        elif block.get("type") == "text":
            text = str(block.get("text") or "")
            text = re.sub(r"^---\s*\nContent:\s*\n", "", text)
            text = re.sub(r"\n===$", "", text).strip()
            if text:
                parts.append(text)
    return "\n\n".join(dict.fromkeys(parts))[:8000]


def semantic_search_context(question: str, artifact: str | None = None) -> tuple[int, str]:
    if _turboquant_rag():
        from arka.stock.turboquant_rag import search_documents

        return search_documents(question, artifact)

    body = {
        "query": question,
        "context_filter": context_filter(artifact),
        "format": "default",
    }
    status, data = api_request("POST", "/v1/tools/semantic-search", body, timeout=120)
    if status != 200 or not isinstance(data, dict):
        return status, format_error(data)
    if data.get("is_error"):
        return 500, format_error(data)
    context = extract_search_context(data)
    if not context:
        return 404, "No relevant passages found in your documents."
    return 0, context


def _ollama_chat_model(default: str = "llama3.2:1b") -> str:
    return env("PDF_RAG_MODEL") or env("OLLAMA_CHAT_MODEL") or default


def _ollama_api_base() -> str:
    host = env("OLLAMA_HOST", "127.0.0.1:11434")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


def _gemini_models() -> list[str]:
    preferred = env("AI_PREFERRED_MODEL")
    models = [
        preferred,
        env("PDF_RAG_MODEL"),
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    out: list[str] = []
    for model in models:
        if model and model not in out:
            out.append(model)
    return out


def _wants_summary(question: str) -> bool:
    q = question.lower()
    return bool(
        re.search(
            r"\b(summarize|summary|summarise|tldr|tl;dr|overview|brief|short recap)\b",
            q,
        )
    )


def _search_queries(question: str) -> list[str]:
    q = question.lower().strip()
    queries = [question.strip()]
    if re.search(r"\b(skill|skills|expertise|competenc|strength|qualification)\b", q):
        queries.extend(
            [
                "skills experience education summary qualifications technologies programming",
                "work experience job title role responsibilities",
            ]
        )
    elif re.search(r"\b(name|who is|person|profile|about)\b", q):
        queries.append("name summary experience education contact")
    elif re.search(r"\b(work|job|company|employer|experience)\b", q):
        queries.append("experience work employment company role")
    elif re.search(r"\b(education|degree|university|college|studied)\b", q):
        queries.append("education degree university college")
    out: list[str] = []
    for item in queries:
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out


def gather_search_context(question: str, artifact: str | None = None) -> tuple[int, str]:
    parts: list[str] = []
    for query in _search_queries(question):
        status, chunk = semantic_search_context(query, artifact)
        if status == 0 and chunk:
            parts.append(chunk)
        elif status not in (0, 404) and not parts:
            return status, chunk
    if not parts:
        return 404, "No relevant passages found in your documents."
    merged: list[str] = []
    for part in parts:
        if part not in merged:
            merged.append(part)
    return 0, "\n\n---\n\n".join(merged)[:16000]


def _is_profile_skills_question(question: str) -> bool:
    return bool(
        re.search(
            r"\b(skill|skills|expertise|competenc|strength|what can|good at|knows)\b",
            question,
            re.I,
        )
    )


def _llm_synthesize(question: str, context: str, doc_name: str | None = None) -> str:
    doc_hint = f" from {doc_name}" if doc_name else ""
    if _wants_summary(question):
        system = (
            f"Summarize the document excerpts below{doc_hint} in clear, concise prose. "
            "Use short paragraphs or bullet points. Cover the main topics only; "
            "do not quote large blocks verbatim. Max ~200 words unless asked for more."
        )
    elif _is_profile_skills_question(question):
        system = (
            f"Answer the question using the document excerpts below{doc_hint}. "
            "This may be a profile, resume, or CV. Infer skills and strengths from "
            "job titles, experience, education, summary, and projects even when there "
            "is no explicit Skills section. List concrete skills as bullet points. "
            "Do not say information is missing if experience or education clearly implies it."
        )
    else:
        system = (
            f"Answer the question using the document excerpts below{doc_hint}. "
            "Be direct and helpful. Reasonable inference from context is allowed "
            "(e.g. job titles and degrees imply related skills). "
            "Only say the excerpts lack enough information as a last resort."
        )
    trimmed = context[:12000]
    if len(context) > len(trimmed):
        trimmed += "\n\n[…truncated for length…]"
    user = f"Document excerpts:\n{trimmed}\n\nQuestion: {question}"

    from arka.llm.cli import llm_complete

    return llm_complete(system, user, task="pdf")


def _tools_unsupported_error(data: object) -> bool:
    msg = format_error(data).lower()
    return "does not support tools" in msg or "tool" in msg and "not support" in msg


def _ask_via_search(
    question: str,
    artifact: str | None = None,
    doc_name: str | None = None,
) -> tuple[int, str]:
    status, context = gather_search_context(question, artifact)
    if status != 0:
        return status, context
    answer = _llm_synthesize(question, context, doc_name=doc_name)
    if answer:
        return 0, answer
    return 500, "Could not synthesize an answer (check GEMINI_API_KEY or other LLM providers)."


def _strip_doc_prefix(question: str) -> str:
    q = question.strip()
    patterns = [
        r"^(please\s+)?(can you\s+)?(ask|query|search)\s+(my\s+)?(pdf|pdfs|document|docs?|file|files)\s+",
        r"^what\s+does\s+(my\s+)?(the\s+)?(pdf|document|file)\s+(say|mention)\s+about\s+",
        r"^(summarize|summary\s+of)\s+(my\s+)?(pdf|document|uploaded\s+docs?|file)\s*",
        r"^(please\s+)?",
    ]
    for pat in patterns:
        q = re.sub(pat, "", q, flags=re.I).strip()
    return q


_SUMMARY_VERBS = r"summarize|summary|summarise|overview|tldr|tl;dr|brief|recap"
_ASK_VERBS = r"about|on|regarding|summarize|summary|summarise|what|who|when|where|why|how|explain|describe|list|tell|overview|tldr|tl;dr|brief|recap"
_EXT = extension_pattern()
_FILE_SUFFIX = rf"(?:{_EXT})"


def _try_resolve_doc(ref: str) -> tuple[str | None, str | None]:
    artifact, file_name, err = resolve_document(ref)
    if artifact and not err:
        return file_name or ref, artifact
    return None, None


def _parse_doc_and_question(text: str) -> tuple[str | None, str]:
    q = _strip_doc_prefix(text)
    if not q:
        return None, text.strip()

    patterns = [
        rf"^(?P<doc>.+?\.{_FILE_SUFFIX})\s+(?P<q>{_SUMMARY_VERBS})(?:\s+(?P<rest>.+))?$",
        rf"^(?P<q>{_SUMMARY_VERBS})\s+(?P<doc>.+?\.{_FILE_SUFFIX})(?:\s+(?P<rest>.+))?$",
        rf"^(?:ask|query|search)\s+(?P<doc>[^\s]+\.{_FILE_SUFFIX})\s+(?:about\s+)?(?P<q>.+)$",
        rf"^(?P<doc>[^\s]+\.{_FILE_SUFFIX})\s+(?P<q>.+)$",
        rf"^(?P<doc>[^\s]+)\s+(?P<q>{_ASK_VERBS}\b.+)$",
        rf"^(?:from|in)\s+(?P<doc>[^\s]+\.{_FILE_SUFFIX}|\S+(?:\s+\S+)?)\s*,?\s+(?P<q>.+)$",
        rf"^(?P<q>.+?)\s+(?:from|in)\s+(?P<doc>[^\s]+\.{_FILE_SUFFIX}|\S+(?:\s+\S+)?)\s*$",
        r"^(?P<q>.+?)\s+(?:in|from)\s+(?:document|pdf|file)\s+(?P<doc>\S.+?)\s*$",
    ]
    for pat in patterns:
        m = re.match(pat, q, flags=re.I)
        if not m:
            continue
        doc = (m.groupdict().get("doc") or "").strip(" ,.")
        question = (m.groupdict().get("q") or "").strip(" ,.")
        rest = (m.groupdict().get("rest") or "").strip(" ,.")
        if rest:
            question = f"{question} {rest}".strip()
        if doc and question:
            if not re.search(rf"\.{_FILE_SUFFIX}$", doc, re.I):
                resolved_name, _ = _try_resolve_doc(doc)
                if not resolved_name:
                    continue
            return doc, question

    m = re.match(rf"^(?P<doc>.+?)\s+(?P<q>{_SUMMARY_VERBS})\s*$", q, re.I)
    if m:
        doc_name, _ = _try_resolve_doc(m.group("doc").strip())
        if doc_name:
            return doc_name, m.group("q")

    m = re.match(rf"^(?P<q>{_SUMMARY_VERBS})\s+(?P<doc>.+)$", q, re.I)
    if m:
        doc_name, _ = _try_resolve_doc(m.group("doc").strip())
        if doc_name:
            question = m.group("q")
            return doc_name, question

    return None, q


def cmd_parse_ask(text: str) -> int:
    doc_ref, question = _parse_doc_and_question(text)
    if doc_ref:
        artifact, file_name, err = resolve_document(doc_ref)
        if artifact and not err:
            print(f"{artifact}\t{file_name}\t{question}")
            return 0
    print(f"\t\t{question or text.strip()}")
    return 0


def cmd_ask(question: str, document: str | None = None) -> int:
    question = " ".join(question.split())
    if not question:
        print("Usage: ask [--doc DOCUMENT] <question>", file=sys.stderr)
        return 1

    artifact: str | None = None
    doc_name: str | None = None
    if document:
        if _turboquant_rag():
            artifact, doc_name, err = _resolve_turboquant_document(document)
            if err and is_up():
                artifact, doc_name, err = resolve_document(document)
        else:
            artifact, doc_name, err = resolve_document(document)
        if err:
            print(err, file=sys.stderr)
            return 1
        status_msg(f"Using document: {doc_name}")

    tq_docs = _list_turboquant_documents() if _turboquant_rag() else []
    if _turboquant_rag() and tq_docs:
        mode = env("PDF_RAG_ASK_MODE", "search").lower()
        if mode in {"search", "semantic", "auto", "turboquant"}:
            status, answer = _ask_via_search(question, artifact, doc_name)
            if status != 0:
                print(f"Query failed ({status}): {answer}", file=sys.stderr)
                return 1
            print(answer)
            return 0

    if not is_up():
        if not ensure_server(auto_start=True):
            print(f"PrivateGPT is not running at {base_url()}.", file=sys.stderr)
            print("Start it with: private-gpt serve", file=sys.stderr)
            return 1

    docs = list_documents()
    if not docs and not tq_docs:
        print("No documents ingested yet. Ingest one first, e.g.:", file=sys.stderr)
        print("  arka pdf ingest ~/Documents/report.pdf", file=sys.stderr)
        print("  doc_ingest ~/Notes/readme.md", file=sys.stderr)
        return 1

    mode = env("PDF_RAG_ASK_MODE", "auto").lower()
    if mode in {"search", "semantic"}:
        status, answer = _ask_via_search(question, artifact, doc_name)
        if status != 0:
            print(f"Query failed ({status}): {answer}", file=sys.stderr)
            return 1
        print(answer)
        return 0

    body = {
        "model": "default",
        "stream": False,
        "messages": [{"role": "user", "content": question}],
        "system": [
            {
                "text": (
                    "Answer using only the ingested documents. "
                    "Be concise, accurate, and cite sources when available."
                ),
                "citations": {"enabled": True},
                "extensions": ["zylon"],
            }
        ],
        "tools": [{"name": "semantic_search", "type": "semantic_search_v1"}],
        "tool_context": [
            {
                "type": "ingested_artifact",
                "context_filter": context_filter(artifact),
            }
        ],
    }
    status, data = api_request("POST", "/v1/messages", body, timeout=900)
    if status == 200 and isinstance(data, dict):
        answer = extract_answer(data)
        if answer:
            print(answer)
            return 0

    if mode == "tools" or (mode == "auto" and not _tools_unsupported_error(data)):
        print(f"Query failed ({status}): {format_error(data)}", file=sys.stderr)
        return 1

    status_msg("Using semantic search (LLM does not support tools)…")
    status, answer = _ask_via_search(question, artifact, doc_name)
    if status != 0:
        print(f"Query failed ({status}): {answer}", file=sys.stderr)
        return 1
    print(answer)
    return 0


def cmd_batch_ingest(
    directory: str,
    extensions: frozenset[str] | None = None,
    recursive: bool = True,
) -> int:
    """Ingest every matching file under a directory (default: all PDFs)."""
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    exts = extensions or frozenset({".pdf"})
    glob_pat = "**/*" if recursive else "*"
    files = sorted(
        p for p in root.glob(glob_pat) if p.is_file() and p.suffix.lower() in exts
    )
    if not files:
        ext_label = ", ".join(sorted(exts))
        print(f"No files ({ext_label}) under {root}", file=sys.stderr)
        return 1

    ext_label = ", ".join(sorted(exts))
    print(f"Ingesting {len(files)} file(s) ({ext_label}) from {root}", file=sys.stderr)

    pgpt_wanted = env("PDF_RAG_PGPT", "1").lower() not in {"0", "false", "no", "off"}
    if pgpt_wanted and not is_up():
        ensure_server(auto_start=True)

    ok = 0
    failed = 0
    for i, doc in enumerate(files, 1):
        try:
            rel = doc.relative_to(root)
        except ValueError:
            rel = doc.name
        print(f"\n[{i}/{len(files)}] {rel}", file=sys.stderr)
        if cmd_ingest(str(doc)) == 0:
            ok += 1
        else:
            failed += 1

    print(f"\nBatch ingest done: {ok} ok, {failed} failed, {len(files)} total", file=sys.stderr)
    return 0 if failed == 0 else 1


def cmd_codebase_ingest(path: str, name: str | None = None) -> int:
    from arka.stock.turboquant_rag import index_codebase, use_turboquant

    if not use_turboquant():
        print("TurboQuant RAG is disabled (ARKA_RAG_BACKEND).", file=sys.stderr)
        return 1
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1
    status_msg(f"Indexing codebase {root} …")
    files, chunks, detail = index_codebase(root, name)
    if files <= 0:
        print(f"Codebase ingest failed: {detail}", file=sys.stderr)
        return 1
    label = name or root.name
    from arka.stock.turboquant_rag import sanitize_artifact

    art = f"codebase-{sanitize_artifact(label)}"
    print(f"✓ Indexed codebase '{label}': {detail}")
    print(f"Ask with: doc_ask --doc {art} \"your question\"")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka document RAG (PrivateGPT)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Check PrivateGPT and document count")
    sub.add_parser("list", help="List ingested documents")
    sub.add_parser("formats", help="Show supported ingest file formats")

    ingest = sub.add_parser("ingest", help="Ingest a document (PDF, Office, text, code, …)")
    ingest.add_argument("path")

    ask = sub.add_parser("ask", help="Ask a question over ingested documents")
    ask.add_argument("-d", "--doc", metavar="DOCUMENT", help="Limit search to one file")
    ask.add_argument("question", nargs="+")

    parse_ask = sub.add_parser("parse-ask", help="Parse NL document question into doc + question")
    parse_ask.add_argument("text")

    cb = sub.add_parser("codebase-ingest", help="Index a project folder for Q&A (TurboQuant)")
    cb.add_argument("path")
    cb.add_argument("-n", "--name", help="Short name for this codebase (default: folder name)")

    batch = sub.add_parser("batch-ingest", help="Ingest all matching files in a directory")
    batch.add_argument("path", help="Directory to scan (e.g. ~/Documents)")
    batch.add_argument(
        "--ext",
        action="append",
        default=[".pdf"],
        help="File extension(s) to ingest (repeatable, default: .pdf)",
    )
    batch.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only files in the top directory, not subfolders",
    )

    args = parser.parse_args()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "formats":
        return cmd_formats()
    if args.cmd == "ingest":
        return cmd_ingest(args.path)
    if args.cmd == "parse-ask":
        return cmd_parse_ask(args.text)
    if args.cmd == "ask":
        return cmd_ask(" ".join(args.question), args.doc)
    if args.cmd == "codebase-ingest":
        return cmd_codebase_ingest(args.path, args.name)
    if args.cmd == "batch-ingest":
        exts = frozenset(
            (e if e.startswith(".") else f".{e}").lower() for e in args.ext
        )
        return cmd_batch_ingest(args.path, extensions=exts, recursive=not args.no_recursive)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
