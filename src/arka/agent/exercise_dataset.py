"""Import and query the hasaneyldrm/exercises-dataset metadata."""

from __future__ import annotations

import argparse
import csv
import json
import re
import signal
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from arka.paths import cache_dir


REPO_URL = "https://github.com/hasaneyldrm/exercises-dataset"
RAW_JSON_URL = "https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/main/data/exercises.json"
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
LICENSE_NOTE = (
    "Educational / non-commercial use only per upstream README; images and GIFs "
    "belong to their respective copyright holders."
)


def dataset_dir() -> Path:
    return cache_dir() / "datasets" / "exercises-dataset"


def data_path() -> Path:
    return dataset_dir() / "exercises.json"


def meta_path() -> Path:
    return dataset_dir() / "metadata.json"


class _DownloadDeadline(RuntimeError):
    pass


class _deadline:
    def __init__(self, seconds: float) -> None:
        self.seconds = max(1.0, seconds)
        self.previous_handler: Any = None
        self.enabled = False

    def __enter__(self) -> None:
        if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
            return

        def _raise_timeout(signum: int, frame: Any) -> None:
            raise _DownloadDeadline(f"download timed out after {self.seconds:g}s")

        self.previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        self.enabled = True

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.previous_handler)


def _download_text(url: str = RAW_JSON_URL, *, timeout: float = 30.0, max_bytes: int = MAX_DOWNLOAD_BYTES) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ArkaExerciseDataset/1.0"})
    with _deadline(timeout):
        with urllib.request.urlopen(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(f"dataset download exceeded {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8")


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    instructions = record.get("instructions") if isinstance(record.get("instructions"), dict) else {}
    secondary = record.get("secondary_muscles")
    if isinstance(secondary, str):
        secondary_muscles = [secondary]
    elif isinstance(secondary, list):
        secondary_muscles = [str(item) for item in secondary if str(item).strip()]
    else:
        secondary_muscles = []
    return {
        "id": str(record.get("id") or "").strip(),
        "name": str(record.get("name") or "").strip(),
        "category": str(record.get("category") or record.get("body_part") or "").strip().lower(),
        "body_part": str(record.get("body_part") or record.get("category") or "").strip().lower(),
        "equipment": str(record.get("equipment") or "").strip().lower(),
        "target": str(record.get("target") or "").strip().lower(),
        "muscle_group": str(record.get("muscle_group") or "").strip().lower(),
        "secondary_muscles": secondary_muscles,
        "instructions": {
            "en": str(instructions.get("en") or record.get("instructions_en") or "").strip(),
            "tr": str(instructions.get("tr") or record.get("instructions_tr") or "").strip(),
        },
        "image": str(record.get("image") or "").strip(),
        "gif_url": str(record.get("gif_url") or record.get("video") or "").strip(),
        "created_at": str(record.get("created_at") or "").strip(),
    }


def validate_records(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError("expected exercises.json to be a JSON array")
    normalized = [normalize_record(row) for row in records if isinstance(row, dict)]
    valid = [row for row in normalized if row["id"] and row["name"]]
    if not valid:
        raise ValueError("no valid exercise records found")
    return valid


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    categories = Counter(row["category"] or "unknown" for row in records)
    equipment = Counter(row["equipment"] or "unknown" for row in records)
    targets = Counter(row["target"] or "unknown" for row in records)
    return {
        "source": REPO_URL,
        "source_data": RAW_JSON_URL,
        "license_note": LICENSE_NOTE,
        "records": len(records),
        "categories": dict(categories.most_common()),
        "equipment": dict(equipment.most_common()),
        "top_targets": dict(targets.most_common(20)),
    }


def import_dataset(*, source: str = RAW_JSON_URL, force: bool = False, timeout: float = 30.0) -> dict[str, Any]:
    dataset_dir().mkdir(parents=True, exist_ok=True)
    target = data_path()
    if target.exists() and not force:
        records = validate_records(json.loads(target.read_text(encoding="utf-8")))
    else:
        try:
            text = _download_text(source, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"could not download exercise dataset: {exc}") from exc
        records = validate_records(json.loads(text))
        target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = summarize(records)
    meta["cache_path"] = str(target)
    meta_path().write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def load_records(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or data_path()
    if not target.is_file():
        raise FileNotFoundError("exercise dataset not imported; run: arka exercises import")
    return validate_records(json.loads(target.read_text(encoding="utf-8")))


def search_records(query: str = "", *, limit: int = 10, records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    data = records if records is not None else load_records()
    terms = [term.lower() for term in re.findall(r"[a-z0-9]+", query or "")]
    if not terms:
        return data[:limit]

    def score(row: dict[str, Any]) -> int:
        haystack = " ".join(
            [
                row["name"],
                row["category"],
                row["equipment"],
                row["target"],
                row["muscle_group"],
                " ".join(row["secondary_muscles"]),
            ]
        ).lower()
        return sum(1 for term in terms if term in haystack)

    ranked = sorted(((score(row), row) for row in data), key=lambda item: (-item[0], item[1]["name"]))
    return [row for value, row in ranked if value > 0][:limit]


def export_records(records: list[dict[str, Any]], output: Path, *, fmt: str = "json") -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        fields = ("id", "name", "category", "equipment", "target", "muscle_group", "image", "gif_url")
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in records:
                writer.writerow({key: row.get(key, "") for key in fields})
    elif fmt == "jsonl":
        output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    else:
        output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def route_command(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    mentions_repo = "hasaneyldrm/exercises-dataset" in clean or "exercises-dataset" in clean
    if not mentions_repo and not re.search(r"(?i)\b(?:exercise|fitness|workout)\b", clean):
        return ""
    if mentions_repo or re.search(r"(?i)\b(?:add|import|load|download|cache)\b.*\b(?:dataset|data)\b", clean):
        return "exercise_dataset import"
    if re.search(r"(?i)\b(?:search|find|show|list)\b", clean):
        query = re.sub(r"(?i)\b(?:search|find|show|list|exercise|exercises|fitness|workout|dataset|data|for|about)\b", " ", clean)
        return "exercise_dataset search " + " ".join(query.split())
    if re.search(r"(?i)\b(?:status|stats|summary)\b", clean):
        return "exercise_dataset status"
    return ""


def _print_summary(meta: dict[str, Any]) -> None:
    print(f"exercise records\t{meta['records']}")
    print(f"cache\t{meta.get('cache_path', data_path())}")
    print(f"source\t{meta['source']}")
    print(f"license\t{meta['license_note']}")
    cats = ", ".join(f"{name}:{count}" for name, count in list(meta["categories"].items())[:8])
    equip = ", ".join(f"{name}:{count}" for name, count in list(meta["equipment"].items())[:8])
    print(f"top categories\t{cats}")
    print(f"top equipment\t{equip}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka exercises")
    sub = parser.add_subparsers(dest="cmd")
    p_import = sub.add_parser("import", help="Download and cache exercise metadata")
    p_import.add_argument("--source", default=RAW_JSON_URL)
    p_import.add_argument("--force", action="store_true")
    p_import.add_argument("--timeout", type=float, default=30.0)
    p_import.add_argument("--json", action="store_true")
    p_status = sub.add_parser("status", help="Show cached dataset summary")
    p_status.add_argument("--json", action="store_true")
    p_search = sub.add_parser("search", help="Search cached exercises")
    p_search.add_argument("query", nargs="*")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--json", action="store_true")
    p_export = sub.add_parser("export", help="Export cached exercises")
    p_export.add_argument("--output", required=True)
    p_export.add_argument("--format", choices=("json", "jsonl", "csv"), default="json")
    args = parser.parse_args(argv or ["status"])
    try:
        if args.cmd == "import":
            meta = import_dataset(source=args.source, force=args.force, timeout=max(1.0, args.timeout))
            print(json.dumps(meta, indent=2) if args.json else "Imported exercise dataset")
            if not args.json:
                _print_summary(meta)
            return 0
        if args.cmd == "search":
            rows = search_records(" ".join(args.query), limit=max(1, min(args.limit, 100)))
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                for row in rows:
                    print(f"{row['id']}\t{row['name']}\t{row['category']}\t{row['equipment']}\t{row['target']}")
            return 0
        if args.cmd == "export":
            out = export_records(load_records(), Path(args.output).expanduser(), fmt=args.format)
            print(f"exported\t{out}")
            return 0
        records = load_records()
        meta = summarize(records)
        meta["cache_path"] = str(data_path())
        print(json.dumps(meta, indent=2) if getattr(args, "json", False) else "Exercise dataset cached")
        if not getattr(args, "json", False):
            _print_summary(meta)
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"exercise dataset error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
