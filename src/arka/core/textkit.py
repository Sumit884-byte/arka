#!/usr/bin/env python3
"""Offline text utilities — UUID, hashing, and base64 (agent-friendly)."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import uuid
from typing import Any


def uuid_payload(
    *,
    version: int = 4,
    name: str | None = None,
    namespace: str = "url",
) -> dict[str, Any]:
    """Generate a UUID for MCP / automation clients."""
    version = int(version)
    if version == 4:
        value = str(uuid.uuid4())
        return {"ok": True, "version": 4, "uuid": value}
    if version == 5:
        ns_map = {
            "dns": uuid.NAMESPACE_DNS,
            "url": uuid.NAMESPACE_URL,
            "oid": uuid.NAMESPACE_OID,
            "x500": uuid.NAMESPACE_X500,
        }
        key = (namespace or "url").strip().lower()
        if key not in ns_map:
            raise ValueError("namespace must be dns, url, oid, or x500")
        if not (name or "").strip():
            raise ValueError("name is required for uuid version 5")
        value = str(uuid.uuid5(ns_map[key], name.strip()))
        return {
            "ok": True,
            "version": 5,
            "uuid": value,
            "name": name.strip(),
            "namespace": key,
        }
    raise ValueError("version must be 4 or 5")


def hash_payload(text: str, *, algorithm: str = "sha256") -> dict[str, Any]:
    """Hash text with a standard digest algorithm."""
    data = text if text is not None else ""
    algo = (algorithm or "sha256").strip().lower().replace("-", "")
    if algo == "sha1":
        digest = hashlib.sha1(data.encode("utf-8")).hexdigest()
    elif algo == "md5":
        digest = hashlib.md5(data.encode("utf-8")).hexdigest()
    elif algo == "sha256":
        digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    elif algo == "sha512":
        digest = hashlib.sha512(data.encode("utf-8")).hexdigest()
    else:
        raise ValueError("algorithm must be sha256, sha512, sha1, or md5")
    return {
        "ok": True,
        "algorithm": algo,
        "hex": digest,
        "bytes": len(data.encode("utf-8")),
    }


def base64_payload(text: str, *, action: str = "encode") -> dict[str, Any]:
    """Encode or decode base64 text."""
    mode = (action or "encode").strip().lower()
    if mode == "encode":
        encoded = base64.b64encode((text or "").encode("utf-8")).decode("ascii")
        return {"ok": True, "action": "encode", "result": encoded}
    if mode == "decode":
        raw = (text or "").strip()
        try:
            decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — surface decode errors
            raise ValueError(f"invalid base64: {exc}") from exc
        return {"ok": True, "action": "decode", "result": decoded}
    raise ValueError("action must be encode or decode")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arka text utilities (uuid/hash/base64)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_uuid = sub.add_parser("uuid", help="Generate a UUID")
    p_uuid.add_argument("--version", type=int, default=4, choices=[4, 5])
    p_uuid.add_argument("--name", default="", help="Name for uuid5")
    p_uuid.add_argument("--namespace", default="url", help="uuid5 namespace")

    p_hash = sub.add_parser("hash", help="Hash text")
    p_hash.add_argument("text", nargs="+", help="Text to hash")
    p_hash.add_argument("--algorithm", default="sha256")

    p_b64 = sub.add_parser("base64", help="Base64 encode/decode")
    p_b64.add_argument("action", choices=["encode", "decode"])
    p_b64.add_argument("text", nargs="+", help="Input text")

    args = parser.parse_args(argv)
    if args.cmd == "uuid":
        payload = uuid_payload(version=args.version, name=args.name or None, namespace=args.namespace)
    elif args.cmd == "hash":
        payload = hash_payload(" ".join(args.text), algorithm=args.algorithm)
    else:
        payload = base64_payload(" ".join(args.text), action=args.action)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
