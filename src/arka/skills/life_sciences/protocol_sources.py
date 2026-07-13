"""Science protocol sources for Arka flow — bundled index, PubMed, protocols.io mirror."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

PROTOCOLS_IO_MIRROR = (
    "https://raw.githubusercontent.com/protocolsio/protocols/master/protocols"
)
_PROTOCOLS_CACHE: dict[str, Any] | None = None


def _skill_root() -> Path:
    return Path(__file__).resolve().parent


def load_protocol_index() -> dict[str, Any]:
    global _PROTOCOLS_CACHE
    if _PROTOCOLS_CACHE is not None:
        return _PROTOCOLS_CACHE
    path = _skill_root() / "protocols.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid protocols.json")
    _PROTOCOLS_CACHE = data
    return data


def _normalize_topic(text: str) -> str:
    t = re.sub(r"[^\w\s-]", " ", text.lower())
    return " ".join(t.split())


def match_bundled_protocol(topic: str) -> dict[str, Any] | None:
    """Return bundled protocol entry when topic matches aliases or title."""
    topic_norm = _normalize_topic(topic)
    if not topic_norm:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for entry in load_protocol_index().get("protocols") or []:
        if not isinstance(entry, dict):
            continue
        candidates = [entry.get("id", ""), entry.get("title", "")]
        candidates.extend(entry.get("aliases") or [])
        for raw in candidates:
            alias = _normalize_topic(str(raw))
            if not alias:
                continue
            if alias == topic_norm or alias in topic_norm or topic_norm in alias:
                score = len(alias)
                if best is None or score > best[0]:
                    best = (score, entry)
    return best[1] if best else None


def _section_lines(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    lines = [f"## {title}"]
    lines.extend(f"{i}. {item}" for i, item in enumerate(items, 1))
    return lines


def format_protocol_flow(
    *,
    title: str,
    steps: list[str],
    source: str,
    materials: list[str] | None = None,
    safety: list[str] | None = None,
    references: list[str] | None = None,
) -> str:
    """Render protocol data as Arka flow markdown with source attribution."""
    blocks: list[str] = [f"## {title}"]
    blocks.extend(_section_lines("Materials", materials or []))
    blocks.extend(_section_lines("Safety", safety or []))
    blocks.extend(_section_lines("Steps", steps))
    if references:
        blocks.append("## References")
        blocks.extend(f"{i}. {url}" for i, url in enumerate(references, 1))
    blocks.append(f"\n*Source: {source}*")
    return "\n".join(blocks).strip()


def _component_text(component: dict[str, Any]) -> str:
    data = component.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    source = component.get("source_data")
    if isinstance(source, dict):
        for key in ("description", "text", "content"):
            val = source.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    step = component.get("step")
    if isinstance(step, str) and step.strip():
        if step.startswith("{"):
            try:
                blocks = json.loads(step).get("blocks") or []
                parts = [b.get("text", "").strip() for b in blocks if b.get("text", "").strip()]
                if parts:
                    return " ".join(parts)
            except json.JSONDecodeError:
                pass
        return step.strip()
    return ""


def parse_protocols_io_json(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract title and step text from protocols.io mirror JSON."""
    title = (data.get("title") or data.get("name") or "").strip()
    if not title:
        stem = (data.get("uri") or data.get("slug") or "").strip()
        if stem:
            title = stem.replace("-", " ").strip()
    steps: list[str] = []
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        texts: list[str] = []
        for comp in step.get("components") or []:
            if not isinstance(comp, dict):
                continue
            if comp.get("name") not in (None, "Description", "Section", "Note"):
                continue
            text = _component_text(comp)
            if text and text not in texts:
                texts.append(text)
        if not texts:
            text = _component_text(step)
            if text:
                texts.append(text)
        if texts:
            steps.append(" ".join(texts))
    if not steps:
        return None
    doi = (data.get("doi") or "").strip()
    source = "protocols.io public mirror (GitHub)"
    if doi:
        source = f"protocols.io ({doi})"
    refs = []
    if doi:
        refs.append(f"https://{doi}" if not doi.startswith("http") else doi)
    return {
        "title": title or "Protocol",
        "steps": steps,
        "source": source,
        "references": refs,
    }


def fetch_protocols_io_mirror(filename: str, *, timeout: float = 20.0) -> dict[str, Any] | None:
    """Fetch and parse a protocol JSON file from the protocols.io GitHub mirror."""
    name = filename.strip().lstrip("/")
    if not name or ".." in name.split("/"):
        return None
    url = f"{PROTOCOLS_IO_MIRROR}/{urllib.parse.quote(name)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return parse_protocols_io_json(data)


def fetch_pubmed_abstract(pmid: str, *, timeout: float = 20.0) -> str | None:
    """Fetch PubMed abstract text via NCBI efetch."""
    uid = re.sub(r"\D", "", pmid)
    if not uid:
        return None
    params = urllib.parse.urlencode(
        {"db": "pubmed", "id": uid, "retmode": "xml", "rettype": "abstract"}
    )
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            root = ET.fromstring(resp.read())
    except (urllib.error.URLError, TimeoutError, ET.ParseError):
        return None
    parts: list[str] = []
    for abstract in root.findall(".//AbstractText"):
        label = abstract.attrib.get("Label", "").strip()
        text = "".join(abstract.itertext()).strip()
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    joined = "\n".join(parts).strip()
    return joined or None


def search_pubmed_protocol(topic: str, *, retmax: int = 3) -> dict[str, str] | None:
    """Search PubMed for a methods/protocol paper and return metadata + abstract."""
    query = f'("{topic}"[Title/Abstract]) AND (protocol[Title/Abstract] OR methods[Title/Abstract])'
    params = urllib.parse.urlencode(
        {"db": "pubmed", "term": query, "retmax": retmax, "retmode": "json"}
    )
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
    ids = data.get("esearchresult", {}).get("idlist") or []
    if not ids:
        return None

    summary_params = urllib.parse.urlencode(
        {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    )
    summary_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{summary_params}"
    )
    try:
        with urllib.request.urlopen(summary_url, timeout=20) as resp:
            root = ET.fromstring(resp.read())
    except (urllib.error.URLError, TimeoutError, ET.ParseError):
        return None

    for doc in root.findall(".//DocSum"):
        uid = (doc.findtext("Id") or "").strip()
        title = ""
        for item in doc.findall("Item"):
            if item.attrib.get("Name") == "Title":
                title = (item.text or "").strip()
        if not uid:
            continue
        abstract = fetch_pubmed_abstract(uid)
        if not abstract:
            continue
        return {
            "pmid": uid,
            "title": title,
            "abstract": abstract,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
        }
    return None


def resolve_bundled_flow(topic: str) -> tuple[str, str] | None:
    """Return (markdown, source_kind) from bundled index, optionally enriched by mirror."""
    entry = match_bundled_protocol(topic)
    if not entry:
        return None

    title = str(entry.get("title") or entry.get("id") or topic)
    steps = list(entry.get("steps") or [])
    source = str(entry.get("source") or "Arka protocol index")
    materials = list(entry.get("materials") or [])
    safety = list(entry.get("safety") or [])
    references = list(entry.get("references") or [])

    mirror_file = (entry.get("mirror_file") or "").strip()
    if mirror_file:
        mirror = fetch_protocols_io_mirror(mirror_file)
        if mirror and mirror.get("steps"):
            mirror_steps = mirror["steps"]
            if len(mirror_steps) >= len(steps):
                steps = mirror_steps
                source = str(mirror.get("source") or source)
                refs = mirror.get("references") or []
                if refs:
                    references = list(refs)

    if not steps:
        return None

    markdown = format_protocol_flow(
        title=title,
        steps=steps,
        source=source,
        materials=materials,
        safety=safety,
        references=references,
    )
    return markdown, "bundled"


def try_science_flow_from_sources(topic: str) -> tuple[str | None, str]:
    """
    Try external protocol sources before LLM.

    Returns (markdown_or_context, source_kind) where source_kind is
    bundled | protocols_io | pubmed | none.
    """
    bundled = resolve_bundled_flow(topic)
    if bundled:
        return bundled[0], bundled[1]

    pubmed = search_pubmed_protocol(topic)
    if pubmed:
        context = (
            f"PubMed paper: {pubmed['title']}\n"
            f"URL: {pubmed['url']}\n\n"
            f"Abstract:\n{pubmed['abstract']}"
        )
        return context, "pubmed"

    return None, "none"
