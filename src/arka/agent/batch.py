"""Prompt batching for delayed combined implementation."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from arka.paths import cache_dir

BATCH_FILE = cache_dir() / "prompt-batches.json"


@dataclass(frozen=True)
class BatchItem:
    prompt: str
    created_at: str


@dataclass(frozen=True)
class PromptBatch:
    name: str
    due_at: str
    items: list[BatchItem]


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _load(path: Path | None = None) -> dict[str, PromptBatch]:
    path = path or BATCH_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    batches: dict[str, PromptBatch] = {}
    for name, data in raw.items():
        items = [BatchItem(prompt=str(row.get("prompt", "")), created_at=str(row.get("created_at", ""))) for row in data.get("items", [])]
        batches[name] = PromptBatch(name=name, due_at=str(data.get("due_at", "")), items=[item for item in items if item.prompt])
    return batches


def _save(batches: dict[str, PromptBatch], path: Path | None = None) -> None:
    path = path or BATCH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({name: {"name": batch.name, "due_at": batch.due_at, "items": [asdict(item) for item in batch.items]} for name, batch in sorted(batches.items())}, indent=2),
        encoding="utf-8",
    )


@contextmanager
def _locked_batches():
    lock_path = BATCH_FILE.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        batches = _load()
        yield batches
        _save(batches)
        try:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass


def parse_due_at(value: str, *, base: datetime | None = None) -> str:
    base = base or _now()
    text = value.strip().lower()
    if not text:
        raise ValueError("missing due time")
    if text in {"now", "immediately"}:
        return base.isoformat()
    m = re.fullmatch(r"(?:in\s+)?(\d+)\s*(m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days)", text)
    if m:
        qty = int(m.group(1))
        unit = m.group(2)
        delta = timedelta(minutes=qty) if unit.startswith(("m", "min")) else timedelta(hours=qty) if unit.startswith(("h", "hr")) else timedelta(days=qty)
        return (base + delta).isoformat()
    m = re.fullmatch(r"(?:today\s+)?(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        mer = m.group(3)
        if mer == "pm" and hour < 12:
            hour += 12
        if mer == "am" and hour == 12:
            hour = 0
        candidate = base.replace(hour=hour, minute=minute, second=0)
        if candidate < base:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    try:
        return datetime.fromisoformat(value.strip()).replace(microsecond=0).isoformat()
    except ValueError as exc:
        raise ValueError(f"could not parse due time: {value}") from exc


def route_command(text: str) -> str | None:
    clean = text.strip()
    low = clean.lower()
    if re.search(r"\b(?:batch|collect)\b.*\b(?:prompts?|requests?|tasks?)\b.*\b(?:until|till|by|for)\b", low):
        due = re.sub(r"(?i)^.*?\b(?:until|till|by|for)\b\s+", "", clean).strip()
        return "batch start --until " + shlex.quote(due or "1h")
    if re.search(r"\b(?:add|queue|collect)\b.*\b(?:to|in|into)\s+(?:the\s+)?batch\b", low) or low.startswith("batch add "):
        prompt = re.sub(r"(?i)^(?:batch\s+add|add|queue|collect)\s+", "", clean).strip()
        prompt = re.sub(r"(?i)\s+(?:to|in|into)\s+(?:the\s+)?batch\b", "", prompt).strip()
        return "batch add " + shlex.quote(prompt) if prompt else "batch add"
    if re.search(r"\b(?:list|show|status)\b.*\bbatch\b", low) or low in {"batch", "batch list"}:
        return "batch list"
    if re.search(r"\b(?:run|execute|implement)\b.*\bbatch\b", low) or low == "batch run":
        return "batch run"
    if re.search(r"\b(?:due|ready)\b.*\bbatch\b", low) or low == "batch due":
        return "batch due"
    return None


def combined_prompt(batch: PromptBatch) -> str:
    lines = [
        "Implement this Arka prompt batch as one coherent change.",
        "Preserve the user's intent for each item. Do not invent requirements.",
        "Resolve conflicts by choosing the smallest safe implementation and report any skipped item.",
        "",
        f"Batch: {batch.name}",
        f"Due at: {batch.due_at}",
        "Prompts:",
    ]
    lines.extend(f"{index}. {item.prompt}" for index, item in enumerate(batch.items, 1))
    return "\n".join(lines)


def _print_batches(batches: dict[str, PromptBatch]) -> None:
    if not batches:
        print("No prompt batches.")
        return
    for batch in batches.values():
        print(f"{batch.name}\tdue={batch.due_at}\titems={len(batch.items)}")


def _batch_or_default(batches: dict[str, PromptBatch], name: str) -> PromptBatch | None:
    return batches.get(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka batch")
    sub = parser.add_subparsers(dest="cmd")
    p_start = sub.add_parser("start", help="create or update the active prompt batch")
    p_start.add_argument("--name", default="default")
    p_start.add_argument("--until", required=True)
    p_add = sub.add_parser("add", help="add one prompt to a batch")
    p_add.add_argument("prompt", nargs="+")
    p_add.add_argument("--name", default="default")
    p_add.add_argument("--until", default="")
    p_list = sub.add_parser("list", help="list batches")
    p_list.add_argument("--json", action="store_true")
    p_run = sub.add_parser("run", help="run a batch through the coding agent")
    p_run.add_argument("--name", default="default")
    p_run.add_argument("--print", action="store_true", dest="print_only")
    p_run.add_argument("--keep", action="store_true")
    p_due = sub.add_parser("due", help="run the batch only when its due time has arrived")
    p_due.add_argument("--name", default="default")
    p_due.add_argument("--print", action="store_true", dest="print_only")
    p_due.add_argument("--keep", action="store_true")
    p_clear = sub.add_parser("clear", help="delete a batch")
    p_clear.add_argument("--name", default="default")
    args = parser.parse_args(argv)

    if args.cmd == "start":
        try:
            due_at = parse_due_at(args.until)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        with _locked_batches() as batches:
            old = batches.get(args.name)
            batches[args.name] = PromptBatch(name=args.name, due_at=due_at, items=list(old.items) if old else [])
        print(f"Batch '{args.name}' collecting until {due_at}.")
        return 0
    if args.cmd == "add":
        prompt = " ".join(args.prompt).strip()
        if not prompt:
            print("Usage: arka batch add <prompt>", file=sys.stderr)
            return 2
        with _locked_batches() as batches:
            due_at = parse_due_at(args.until) if args.until else batches.get(args.name, PromptBatch(args.name, parse_due_at("1h"), [])).due_at
            old = batches.get(args.name)
            items = list(old.items) if old else []
            items.append(BatchItem(prompt=prompt, created_at=_now().isoformat()))
            batches[args.name] = PromptBatch(name=args.name, due_at=due_at, items=items)
        print(f"Added to batch '{args.name}' ({len(items)} item(s), due {due_at}).")
        return 0
    if args.cmd == "list":
        batches = _load()
        if args.json:
            print(json.dumps({name: {"name": b.name, "due_at": b.due_at, "items": [asdict(i) for i in b.items]} for name, b in batches.items()}, indent=2))
        else:
            _print_batches(batches)
        return 0
    if args.cmd in {"run", "due"}:
        batches = _load()
        batch = _batch_or_default(batches, args.name)
        if not batch or not batch.items:
            print(f"Batch '{args.name}' has no prompts.", file=sys.stderr)
            return 1
        if args.cmd == "due" and datetime.fromisoformat(batch.due_at) > _now():
            print(f"Batch '{args.name}' is not due yet ({batch.due_at}).")
            return 0
        prompt = combined_prompt(batch)
        if args.print_only:
            print(prompt)
            return 0
        from arka.dispatch import run_skill

        code = run_skill("agent_code " + shlex.quote(prompt))
        if code == 0 and not args.keep:
            with _locked_batches() as batches:
                batches.pop(args.name, None)
        return code
    if args.cmd == "clear":
        with _locked_batches() as batches:
            existed = args.name in batches
            batches.pop(args.name, None)
        print(f"Cleared batch '{args.name}'." if existed else f"Batch '{args.name}' was already empty.")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
