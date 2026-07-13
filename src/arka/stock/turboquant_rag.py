#!/usr/bin/env python3
"""Unified TurboQuant vector RAG for documents, media transcripts, and web search."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

CACHE_ROOT = Path.home() / ".cache/fish-agent/turboquant"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))
TQ_BITS = int(os.environ.get("TURBOQUANT_BITS", "6"))
DEFAULT_CHUNK = int(os.environ.get("RAG_CHUNK_CHARS", "700"))
DEFAULT_TOP_K = int(os.environ.get("RAG_TOP_K", "24"))
DEFAULT_CONTEXT = int(os.environ.get("RAG_CONTEXT_CHARS", "14000"))

_STOP = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "why", "what", "who", "how", "when", "where",
    "do", "does", "did", "he", "she", "they", "his", "her", "them", "their", "you", "your",
    "not", "let", "someone", "anyone", "want", "wants", "wanted", "all", "any", "some",
    "could", "would", "should", "will", "been", "being", "into", "from", "with", "about",
    "there", "here", "this", "that", "these", "those", "and", "or", "but", "if", "then", "for",
    "can", "has", "have", "had", "also", "just", "like", "really", "very", "much", "many",
})


def use_turboquant() -> bool:
    backend = (os.environ.get("RAG_BACKEND") or "turboquant").strip().lower()
    return backend not in {"0", "false", "no", "off", "privategpt", "pgpt", "legacy"}


def _load_turboquant_index():
    """Import Firmamento TurboQuantIndex; reject PyPI torch-based package."""
    try:
        import importlib.metadata
        from turboquant import TurboQuantIndex
    except ImportError as exc:
        raise ImportError(
            "TurboQuant not installed. Run: arka rag setup\n"
            "Do NOT use: pip install turboquant  (PyPI package pulls PyTorch/CUDA)"
        ) from exc
    try:
        dist = importlib.metadata.distribution("turboquant")
        for req in dist.requires or []:
            head = req.split(";")[0].strip().lower()
            if head.startswith("torch") or head.startswith("transformers"):
                raise ImportError(
                    "Wrong 'turboquant' package (PyPI KV-cache + PyTorch). "
                    "Run: arka rag setup"
                )
    except importlib.metadata.PackageNotFoundError:
        pass
    return TurboQuantIndex


def _ollama_host() -> str:
    host = (os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434").replace("0.0.0.0", "127.0.0.1")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


def ollama_embed(texts: list[str]) -> list[list[float]] | None:
    if not texts:
        return []
    body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    headers = {"Content-Type": "application/json"}
    key = (os.environ.get("OLLAMA_API_KEY") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{_ollama_host()}/api/embed",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        embs = data.get("embeddings")
        if isinstance(embs, list) and len(embs) == len(texts):
            return embs
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        pass
    return None


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def chunk_text(text: str, chunk_chars: int = DEFAULT_CHUNK) -> list[str]:
    sents = _sentences(text)
    if not sents:
        return [text.strip()] if text.strip() else []
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for sent in sents:
        add = len(sent) + (1 if current else 0)
        if current and size + add > chunk_chars:
            chunks.append(" ".join(current))
            current = [sent]
            size = len(sent)
        else:
            current.append(sent)
            size += add
    if current:
        chunks.append(" ".join(current))
    return chunks


def _search_terms(question: str) -> list[str]:
    q = question.lower()
    terms = re.findall(r"[a-z0-9']{3,}", q)
    out: list[str] = []
    for t in terms:
        if t not in _STOP and t not in out:
            out.append(t)
    for word in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", question):
        w = word.lower()
        if w not in out:
            out.append(w)
    return out


def _keyword_score(chunk: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    low = chunk.lower()
    hits = sum(1 for t in terms if t in low)
    return hits / len(terms)


def _normalize_vectors(vectors: list[list[float]]) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[np.newaxis, :]
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.clip(norms, 1e-8, None)


def _tq_index_path(store_dir: Path) -> Path:
    return store_dir / "tq"


def _load_chunks(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_chunks(path: Path, chunks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")


class TurboQuantStore:
    """Persistent TurboQuant index with chunk metadata."""

    def __init__(self, name: str, *, chunk_chars: int = DEFAULT_CHUNK) -> None:
        self.name = name
        self.chunk_chars = chunk_chars
        self.dir = CACHE_ROOT / name
        self.chunks_path = self.dir / "chunks.json"
        self.registry_path = self.dir / "registry.json"
        self.chunks: list[dict] = []
        self.index: object | None = None

    def _load_index(self) -> object | None:
        tq_path = _tq_index_path(self.dir)
        if not (tq_path / "meta.json").is_file():
            return None
        try:
            TurboQuantIndex = _load_turboquant_index()
        except ImportError:
            return None
        try:
            return TurboQuantIndex.load(tq_path)
        except Exception:
            return None

    def load(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.chunks = _load_chunks(self.chunks_path)
        self.index = self._load_index()

    def _rebuild_index(self, vectors: np.ndarray) -> object:
        TurboQuantIndex = _load_turboquant_index()
        tq_path = _tq_index_path(self.dir)
        if tq_path.is_dir():
            shutil.rmtree(tq_path)
        index = TurboQuantIndex(dimension=EMBED_DIM, num_bits=TQ_BITS, metric="cosine")
        if vectors.size:
            index.add(vectors)
        index.save(tq_path)
        return index

    def _embed_chunks(self, texts: list[str]) -> np.ndarray | None:
        if not texts:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        batch = 32
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), batch):
            embs = ollama_embed(texts[i : i + batch])
            if embs is None:
                return None
            all_vecs.extend(embs)
        return _normalize_vectors(all_vecs)

    def set_chunks(self, entries: list[dict], *, rebuild: bool = True) -> bool:
        """Replace all chunks and optionally rebuild the TurboQuant index."""
        self.chunks = entries
        _save_chunks(self.chunks_path, self.chunks)
        if not rebuild:
            return True
        texts = [str(c.get("text") or "") for c in self.chunks]
        vectors = self._embed_chunks(texts)
        if vectors is None:
            return False
        self.index = self._rebuild_index(vectors)
        return True

    def add_entries(
        self,
        entries: list[dict],
        *,
        replace_artifact: str | None = None,
    ) -> bool:
        if replace_artifact:
            self.chunks = [c for c in self.chunks if c.get("artifact") != replace_artifact]
        self.chunks.extend(entries)
        return self.set_chunks(self.chunks, rebuild=True)

    def search(
        self,
        question: str,
        *,
        k: int = DEFAULT_TOP_K,
        artifact: str | None = None,
        max_chars: int = DEFAULT_CONTEXT,
        keyword_blend: float = 0.35,
    ) -> str:
        if not self.chunks:
            return ""

        candidates = self.chunks
        if artifact:
            candidates = [c for c in self.chunks if c.get("artifact") == artifact]
        if not candidates:
            return ""

        q_emb = ollama_embed([question])
        if not q_emb or not q_emb[0]:
            terms = _search_terms(question)
            scored = sorted(
                (( _keyword_score(c["text"], terms), i) for i, c in enumerate(candidates)),
                key=lambda x: (-x[0], x[1]),
            )
            picked = [candidates[i] for score, i in scored[:k] if score > 0]
            if not picked:
                picked = candidates[: min(k, len(candidates))]
            return _join_chunks(picked, max_chars)

        if self.index is None or self.index.size != len(self.chunks):
            texts = [str(c.get("text") or "") for c in self.chunks]
            vectors = self._embed_chunks(texts)
            if vectors is None:
                return ""
            self.index = self._rebuild_index(vectors)

        q_vec = _normalize_vectors(q_emb)
        sims, idxs = self.index.search(q_vec, k=min(len(self.chunks), max(k * 3, k)))
        terms = _search_terms(question)

        combined: list[tuple[float, int]] = []
        for sim, idx in zip(sims[0], idxs[0]):
            idx = int(idx)
            if artifact and self.chunks[idx].get("artifact") != artifact:
                continue
            kw = _keyword_score(self.chunks[idx]["text"], terms)
            score = (1.0 - keyword_blend) * float(sim) + keyword_blend * kw
            combined.append((score, idx))

        if not combined:
            return ""

        combined.sort(key=lambda x: (-x[0], x[1]))
        picked_idx: set[int] = set()
        for _, idx in combined[:k]:
            picked_idx.add(idx)
            if idx > 0:
                picked_idx.add(idx - 1)
            if idx + 1 < len(self.chunks):
                picked_idx.add(idx + 1)

        parts = [self.chunks[i]["text"] for i in sorted(picked_idx)]
        return _join_chunks([{"text": p} for p in parts], max_chars)

    def list_artifacts(self) -> list[dict]:
        reg: dict[str, dict] = {}
        for chunk in self.chunks:
            art = chunk.get("artifact")
            if not art:
                continue
            if art not in reg:
                reg[art] = {
                    "artifact": art,
                    "file_name": chunk.get("file_name") or art,
                }
        if self.registry_path.is_file():
            try:
                for item in json.loads(self.registry_path.read_text(encoding="utf-8")):
                    if isinstance(item, dict) and item.get("artifact"):
                        reg[item["artifact"]] = item
            except (json.JSONDecodeError, OSError):
                pass
        return sorted(reg.values(), key=lambda x: str(x.get("file_name") or ""))

    def update_registry(self, artifact: str, file_name: str, content_hash: str) -> None:
        items = self.list_artifacts()
        by_art = {i["artifact"]: i for i in items}
        by_art[artifact] = {
            "artifact": artifact,
            "file_name": file_name,
            "content_hash": content_hash,
        }
        self.registry_path.write_text(
            json.dumps(list(by_art.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _join_chunks(chunks: list[dict], max_chars: int) -> str:
    text = " ".join(str(c.get("text") or c) if isinstance(c, dict) else str(c) for c in chunks)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _doc_store() -> TurboQuantStore:
    store = TurboQuantStore("documents")
    store.load()
    return store


def _media_store(slug: str) -> TurboQuantStore:
    safe = re.sub(r"[^a-z0-9\-]+", "-", slug.lower()).strip("-") or "media"
    store = TurboQuantStore(f"media/{safe}")
    store.load()
    return store


def sanitize_artifact(name: str) -> str:
    stem = Path(name).stem
    clean = re.sub(r"[^\w\-]+", "-", stem.lower()).strip("-")
    return clean or "document"


def extract_pdf_text(path: Path) -> str | None:
    if shutil.which("pdftotext"):
        try:
            out = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            text = (out.stdout or "").strip()
            if text:
                return text
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def extract_docx_text(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        text = re.sub(r"<w:tab[^>]*/>", "\t", xml)
        text = re.sub(r"</w:p>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or None
    except (OSError, zipfile.BadZipFile, KeyError):
        return None


def index_document_text(
    artifact: str,
    file_name: str,
    text: str,
    *,
    chunk_chars: int = DEFAULT_CHUNK,
) -> tuple[bool, str]:
    text = text.strip()
    if not text:
        return False, "empty text"
    store = _doc_store()
    chunks = chunk_text(text, chunk_chars)
    entries = [
        {"text": c, "artifact": artifact, "file_name": file_name}
        for c in chunks
    ]
    ok = store.add_entries(entries, replace_artifact=artifact)
    if ok:
        store.update_registry(artifact, file_name, _text_hash(text))
    return ok, f"{len(entries)} chunks"


CODEBASE_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "venv", "venv-arka", "venv-voice-hf", ".venv", "env", "dist", "build",
    ".cache", ".turbo", "target", "vendor", ".idea", ".vscode", "coverage",
})
CODEBASE_SKIP_FILES = frozenset({
    ".ds_store", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
})
CODEBASE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".fish", ".sh", ".bash", ".zsh",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sql",
    ".rs", ".go", ".java", ".kt", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".css", ".scss", ".less", ".xml", ".tex", ".rst", ".md", ".mdx",
    ".rb", ".php", ".swift", ".lua", ".vim", ".dockerfile", ".gradle",
    ".properties", ".env.example", ".gitignore", ".csv", ".tsv", ".txt",
})
MAX_CODEBASE_FILES = int(os.environ.get("CODEBASE_MAX_FILES", "800"))
MAX_CODEBASE_BYTES = int(os.environ.get("CODEBASE_MAX_BYTES", str(512 * 1024)))


def _iter_codebase_files(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in CODEBASE_SKIP_DIRS for part in path.parts):
            continue
        if path.name.lower() in CODEBASE_SKIP_FILES:
            continue
        ext = path.suffix.lower()
        if ext not in CODEBASE_EXTENSIONS and path.name not in {"Dockerfile", "Makefile"}:
            continue
        try:
            if path.stat().st_size > MAX_CODEBASE_BYTES:
                continue
        except OSError:
            continue
        found.append(path)
        if len(found) >= MAX_CODEBASE_FILES:
            break
    return found


def index_codebase(root: Path, name: str | None = None) -> tuple[int, int, str]:
    """Index a project directory into TurboQuant. Returns (files, chunks, message)."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        return 0, 0, f"not a directory: {root}"

    label = sanitize_artifact(name or root.name)
    artifact = f"codebase-{label}"
    store = _doc_store()
    store.chunks = [c for c in store.chunks if c.get("codebase") != label]

    files = _iter_codebase_files(root)
    if not files:
        return 0, 0, "no indexable source files found"

    all_entries: list[dict] = []
    indexed = 0
    for path in files:
        try:
            rel = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            if b"\x00" in raw[:4096]:
                continue
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            header = f"# File: {rel}\n\n"
            body = header + text
            for chunk in chunk_text(body):
                all_entries.append({
                    "text": chunk,
                    "artifact": artifact,
                    "file_name": rel,
                    "codebase": label,
                })
            indexed += 1
        except (OSError, ValueError):
            continue

    if not all_entries:
        return 0, 0, "no readable source files"

    store.chunks.extend(all_entries)
    ok = store.set_chunks(store.chunks, rebuild=True)
    if ok:
        store.update_registry(artifact, f"{label} codebase ({root})", _text_hash(str(root)))
    if not ok:
        return indexed, 0, "embedding/index build failed (check Ollama + arka rag setup)"
    return indexed, len(all_entries), f"{indexed} files, {len(all_entries)} chunks"


def list_indexed_documents() -> list[dict]:
    return _doc_store().list_artifacts()


def resolve_indexed_document(ref: str) -> tuple[str | None, str | None, str | None]:
    if not ref or not str(ref).strip():
        return None, None, None
    needle = str(ref).strip().strip("'\"")
    needle_lower = needle.lower()
    docs = list_indexed_documents()
    if not docs:
        return None, None, "No ingested documents."

    exact: list[tuple[str, str]] = []
    partial: list[tuple[str, str]] = []
    for item in docs:
        artifact = str(item.get("artifact") or "")
        file_name = str(item.get("file_name") or artifact)
        file_lower = file_name.lower()
        stem_lower = Path(file_name).stem.lower()
        artifact_lower = artifact.lower()
        if artifact_lower.startswith("codebase-"):
            if needle_lower in {artifact_lower, file_lower, stem_lower}:
                exact.append((artifact, file_name))
                continue
            base = artifact_lower.removeprefix("codebase-")
            if needle_lower == base or f"{needle_lower} codebase" in file_lower:
                exact.append((artifact, file_name))
                continue
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
        names = ", ".join(n for _, n in exact)
        return None, None, f"Ambiguous document '{ref}'. Matches: {names}"
    if len(partial) == 1:
        return partial[0][0], partial[0][1], None
    if len(partial) > 1:
        names = ", ".join(n for _, n in partial[:5])
        return None, None, f"Ambiguous document '{ref}'. Did you mean: {names}"
    available = ", ".join(str(d.get("file_name") or "") for d in docs)
    return None, None, f"Unknown document '{ref}'. Available: {available}"


def search_documents(
    question: str,
    artifact: str | None = None,
    *,
    max_chars: int = 16000,
) -> tuple[int, str]:
    store = _doc_store()
    if not store.chunks:
        return 404, "No relevant passages found in your documents."
    context = store.search(question, artifact=artifact, max_chars=max_chars)
    if not context.strip():
        return 404, "No relevant passages found in your documents."
    return 0, context


def index_media_transcript(
    text: str,
    slug: str,
    *,
    chunk_chars: int = DEFAULT_CHUNK,
) -> bool:
    text = text.strip()
    if not text:
        return False
    store = _media_store(slug)
    content_hash = _text_hash(text)
    meta_path = store.dir / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("hash") == content_hash and store.chunks and store.index:
                return True
        except (json.JSONDecodeError, OSError):
            pass

    chunks = chunk_text(text, chunk_chars)
    entries = [{"text": c} for c in chunks]
    ok = store.set_chunks(entries, rebuild=True)
    if ok:
        meta_path.write_text(
            json.dumps({"hash": content_hash, "model": EMBED_MODEL, "slug": slug}, ensure_ascii=False),
            encoding="utf-8",
        )
    return ok


def retrieve_transcript_context(
    text: str,
    question: str,
    *,
    src: Path | None = None,
    max_chars: int = DEFAULT_CONTEXT,
) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text

    if src is not None:
        slug = re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-") or "media"
    else:
        slug = f"hash-{_text_hash(text)}"

    if not index_media_transcript(text, slug):
        return text[:max_chars]

    store = _media_store(slug)
    context = store.search(question, max_chars=max_chars)
    return context or text[:max_chars]


def retrieve_web_context(
    raw_pages: str,
    question: str,
    *,
    max_chars: int = 12000,
) -> str:
    raw_pages = raw_pages.strip()
    if not raw_pages:
        return ""
    if len(raw_pages) <= max_chars:
        return raw_pages

    session = _text_hash(raw_pages[:8000] + question)
    store = TurboQuantStore(f"web/{session}", chunk_chars=900)
    store.load()
    if not store.chunks:
        parts = re.split(r"\n{2,}", raw_pages)
        entries = [{"text": p.strip()} for p in parts if p.strip()]
        if not entries:
            entries = [{"text": raw_pages}]
        if not store.set_chunks(entries, rebuild=True):
            return raw_pages[:max_chars]

    context = store.search(question, k=16, max_chars=max_chars, keyword_blend=0.25)
    return context or raw_pages[:max_chars]
