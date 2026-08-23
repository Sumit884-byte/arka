#!/usr/bin/env python3
"""Document RAG — MCP arka_rag and dispatch arka_rag over PrivateGPT/TurboQuant."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from arka.integrations.mcp_local_files import (
    INCREMENTAL_VERIFY_NOTICE,
    LOCAL_FILE_TOOL_NOTICE,
    require_local_path,
)


def _agent_rules(*, ingest: bool = False) -> dict[str, str]:
    rules = {
        "incremental_verify": INCREMENTAL_VERIFY_NOTICE,
    }
    if ingest:
        rules["demo_order"] = (
            "Ingest one local file, ask one question, then ingest a second file and ask again "
            "before reporting the RAG workflow verified."
        )
    return rules


def _rag():
    from arka.pdf import rag as rag_mod

    return rag_mod


def status_payload() -> dict[str, Any]:
    rag = _rag()
    tq_enabled = rag._turboquant_rag()
    tq_docs = rag._list_turboquant_documents() if tq_enabled else []
    pgpt_online = rag.is_up()
    pgpt_docs: list[dict[str, Any]] = []
    if pgpt_online:
        raw = rag.list_documents()
        for item in raw:
            if not isinstance(item, dict):
                continue
            meta = item.get("doc_metadata") if isinstance(item.get("doc_metadata"), dict) else {}
            pgpt_docs.append(
                {
                    "artifact": item.get("artifact"),
                    "file_name": meta.get("file_name") or item.get("artifact"),
                }
            )
    return {
        "turboquant_enabled": tq_enabled,
        "turboquant_documents": tq_docs,
        "privategpt_online": pgpt_online,
        "privategpt_url": rag.base_url(),
        "privategpt_collection": rag.collection(),
        "privategpt_documents": pgpt_docs,
        "local_files_required_for_ingest": True,
        "notice": LOCAL_FILE_TOOL_NOTICE,
        "agent_rules": _agent_rules(),
    }


def list_payload() -> dict[str, Any]:
    rag = _rag()
    documents: list[dict[str, str | None]] = []
    if rag._turboquant_rag():
        for item in rag._list_turboquant_documents():
            documents.append(
                {
                    "artifact": str(item.get("artifact") or ""),
                    "file_name": str(item.get("file_name") or item.get("artifact") or ""),
                    "backend": "turboquant",
                }
            )
    if rag.is_up():
        for item in rag.list_documents():
            if not isinstance(item, dict):
                continue
            meta = item.get("doc_metadata") if isinstance(item.get("doc_metadata"), dict) else {}
            documents.append(
                {
                    "artifact": str(item.get("artifact") or ""),
                    "file_name": str(meta.get("file_name") or item.get("artifact") or ""),
                    "backend": "privategpt",
                }
            )
    return {"documents": documents, "count": len(documents)}


def formats_payload() -> dict[str, Any]:
    rag = _rag()
    native = sorted(rag.PGPT_NATIVE_EXTENSIONS)
    text = sorted(rag.TEXT_EXTRACT_EXTENSIONS - rag.PGPT_NATIVE_EXTENSIONS)
    return {
        "native": native,
        "text_extract": text,
        "supported": sorted(rag.supported_extensions()),
        "local_files_required_for_ingest": True,
        "agent_rules": _agent_rules(ingest=True),
    }


def ingest_payload(path: str | Path) -> dict[str, Any]:
    doc = require_local_path(str(path), kind="file", label="path")
    rag = _rag()
    turboquant_detail = ""
    turboquant_ok = False
    if rag._turboquant_rag():
        turboquant_ok, turboquant_detail = rag._index_document_turboquant(doc)

    pgpt_wanted, pgpt_auto_start = rag._privategpt_ingest_plan(turboquant_ok=turboquant_ok)
    pgpt_artifact = ""
    pgpt_error = ""
    if pgpt_wanted:
        if not rag.is_up() and pgpt_auto_start and not rag.ensure_server(auto_start=True):
            if turboquant_ok:
                return {
                    "path": str(doc),
                    "artifact": None,
                    "turboquant": {"ok": True, "detail": turboquant_detail},
                    "privategpt": {"ok": False, "error": "PrivateGPT offline"},
                    "local_files_required": True,
                    "agent_rules": _agent_rules(ingest=True),
                }
            raise ValueError(
                f"PrivateGPT is not running at {rag.base_url()} and TurboQuant indexing failed "
                f"— {LOCAL_FILE_TOOL_NOTICE}"
            )
        if rag.is_up():
            status, result = rag._ingest_path(doc)
            if status == 0:
                pgpt_artifact = result
            else:
                pgpt_error = result
    elif turboquant_ok:
        return {
            "path": str(doc),
            "artifact": None,
            "turboquant": {"ok": True, "detail": turboquant_detail},
            "privategpt": {"ok": False, "error": "skipped (TurboQuant indexed; PDF_RAG_PGPT=auto)"},
            "local_files_required": True,
            "agent_rules": _agent_rules(ingest=True),
        }

    if not turboquant_ok and not pgpt_artifact:
        detail = pgpt_error or turboquant_detail or "ingest failed"
        raise ValueError(detail)

    return {
        "path": str(doc),
        "artifact": pgpt_artifact or None,
        "turboquant": {"ok": turboquant_ok, "detail": turboquant_detail or None},
        "privategpt": {"ok": bool(pgpt_artifact), "artifact": pgpt_artifact or None, "error": pgpt_error or None},
        "local_files_required": True,
        "agent_rules": _agent_rules(ingest=True),
    }


def ask_payload(question: str, *, document: str | None = None) -> dict[str, Any]:
    q = " ".join(str(question or "").split())
    if not q:
        raise ValueError("question is required")
    rag = _rag()
    artifact: str | None = None
    doc_name: str | None = None
    if document:
        if rag._turboquant_rag():
            artifact, doc_name, err = rag._resolve_turboquant_document(document)
            if err and rag.is_up():
                artifact, doc_name, err = rag.resolve_document(document)
        else:
            artifact, doc_name, err = rag.resolve_document(document)
        if err:
            raise ValueError(err)

    status, answer = rag._ask_via_search(q, artifact, doc_name)
    if status != 0:
        raise ValueError(answer)
    return {
        "question": q,
        "document": doc_name or document,
        "artifact": artifact,
        "answer": answer,
    }


def codebase_ingest_payload(path: str | Path, *, name: str | None = None) -> dict[str, Any]:
    root = require_local_path(str(path), kind="dir", label="path")
    from arka.stock.turboquant_rag import index_codebase, sanitize_artifact, use_turboquant

    if not use_turboquant():
        raise ValueError("TurboQuant RAG is disabled (set ARKA_RAG_BACKEND or enable TurboQuant)")
    label = (name or root.name).strip() or root.name
    files, chunks, detail = index_codebase(root, label)
    if files <= 0:
        raise ValueError(detail or "codebase ingest failed")
    artifact = f"codebase-{sanitize_artifact(label)}"
    return {
        "path": str(root),
        "name": label,
        "artifact": artifact,
        "files": files,
        "chunks": chunks,
        "detail": detail,
        "local_files_required": True,
        "agent_rules": _agent_rules(ingest=True),
    }


def batch_ingest_payload(
    path: str | Path,
    *,
    extensions: list[str] | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    root = require_local_path(str(path), kind="dir", label="path")
    _rag()
    exts = frozenset((e if e.startswith(".") else f".{e}").lower() for e in (extensions or [".pdf"]))
    ingested: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    iterator = root.rglob("*") if recursive else root.iterdir()
    for candidate in sorted(iterator):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in exts:
            continue
        try:
            result = ingest_payload(candidate)
            ingested.append({"path": str(candidate), "artifact": str(result.get("artifact") or "")})
        except ValueError as exc:
            errors.append({"path": str(candidate), "error": str(exc)})
    return {
        "directory": str(root),
        "extensions": sorted(exts),
        "recursive": recursive,
        "ingested": ingested,
        "errors": errors,
        "local_files_required": True,
        "agent_rules": _agent_rules(ingest=True),
    }


def rag_payload(
    *,
    action: str,
    path: str | None = None,
    question: str | None = None,
    document: str | None = None,
    name: str | None = None,
    extensions: list[str] | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    act = (action or "status").strip().lower()
    if act == "status":
        return status_payload()
    if act in {"list", "documents"}:
        return list_payload()
    if act == "formats":
        return formats_payload()
    if act == "ingest":
        if not path:
            raise ValueError(f"path is required for ingest — {LOCAL_FILE_TOOL_NOTICE}")
        return ingest_payload(path)
    if act == "ask":
        if not question:
            raise ValueError("question is required for ask")
        return ask_payload(question, document=document)
    if act in {"codebase_ingest", "codebase-ingest"}:
        if not path:
            raise ValueError(f"path is required for codebase_ingest — {LOCAL_FILE_TOOL_NOTICE}")
        return codebase_ingest_payload(path, name=name)
    if act in {"batch_ingest", "batch-ingest"}:
        if not path:
            raise ValueError(f"path is required for batch_ingest — {LOCAL_FILE_TOOL_NOTICE}")
        return batch_ingest_payload(path, extensions=extensions, recursive=recursive)
    raise ValueError("action must be status, list, formats, ingest, ask, codebase_ingest, or batch_ingest")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arka_rag", description="Document RAG over ingested local files")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("list")
    sub.add_parser("formats")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")

    ask = sub.add_parser("ask")
    ask.add_argument("-d", "--doc")
    ask.add_argument("question", nargs="+")

    codebase = sub.add_parser("codebase-ingest")
    codebase.add_argument("path")
    codebase.add_argument("-n", "--name")

    batch = sub.add_parser("batch-ingest")
    batch.add_argument("path")
    batch.add_argument("--ext", action="append", default=[".pdf"])
    batch.add_argument("--no-recursive", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "status":
            payload = status_payload()
        elif args.cmd == "list":
            payload = list_payload()
        elif args.cmd == "formats":
            payload = formats_payload()
        elif args.cmd == "ingest":
            payload = ingest_payload(args.path)
        elif args.cmd == "ask":
            payload = ask_payload(" ".join(args.question), document=args.doc)
        elif args.cmd == "codebase-ingest":
            payload = codebase_ingest_payload(args.path, name=args.name)
        elif args.cmd == "batch-ingest":
            exts = list(args.ext or [".pdf"])
            payload = batch_ingest_payload(args.path, extensions=exts, recursive=not args.no_recursive)
        else:
            parser.print_help()
            return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
