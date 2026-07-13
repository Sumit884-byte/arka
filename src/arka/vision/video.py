#!/usr/bin/env python3
"""Describe people in video frames via the vision stack."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from arka.core.compute import ffmpeg_thread_args
from arka.media.compose_video import _ffprobe_duration, _which
from arka.media.convert_media import VIDEO_EXTS

try:
    from arka.paths import cache_dir
except ImportError:
    cache_dir = lambda: Path.home() / ".cache" / "fish-agent"  # noqa: E731

DEFAULT_FRAME_COUNT = 5
DEFAULT_PROMPT = (
    "List each visible person in this video frame. For each person give: "
    "(1) brief description (clothing, role if apparent), "
    "(2) approximate center position as x%, y% (0=left/top, 100=right/bottom), "
    "(3) screen zone (e.g. top-left, center, bottom-right). "
    "If no people are visible, say 'No people visible.' "
    "Be concise and structured."
)

_KNOWN_CMDS = frozenset({"describe", "parse", "help"})
_VIDEO_EXT_RE = "|".join(ext.lstrip(".") for ext in sorted(VIDEO_EXTS))

_REJECT = re.compile(
    r"(?i)\b(?:summarize|summary|transcript|transcribe|villain|protagonist|narrator|"
    r"who\s+said|who\s+did|plot|story|happens|ending|compose|generate|create|make)\b"
)

_VIDEO_PEOPLE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:who|which)\s+(?:people|persons?)\s+(?:are\s+)?(?:in|appear(?:s|ing)?\s+in)\b"
    ),
    re.compile(
        r"(?i)\bwho\s+(?:is|are)\s+(?:in|on|visible\s+in)\s+"
        r"(?:this|the|my)?\s*(?:video|clip|footage|recording|movie)\b"
    ),
    re.compile(
        r"(?i)\b(?:people|persons?)\s+in\s+(?:this\s+)?(?:video|clip|footage)\b.*\bwhere\b"
    ),
    re.compile(
        r"(?i)\bwhere\s+(?:are|is)\s+(?:the\s+)?(?:people|persons?)\s+(?:in|on)\s+"
    ),
    re.compile(
        r"(?i)\b(?:identify|find|locate|spot)\s+(?:the\s+)?(?:people|persons?)\s+in\s+"
    ),
    re.compile(
        rf"(?i)\b(?:people|persons?|who)\b.*\.(?:{_VIDEO_EXT_RE})\b"
    ),
    re.compile(
        rf"(?i)\.(?:{_VIDEO_EXT_RE})\b.*\b(?:people|persons?|who\s+(?:is|are)\s+in)\b"
    ),
    re.compile(
        r"(?i)\b(?:which\s+people|who)\s+(?:is\s+)?(?:in|are\s+in)\b.*\b(?:video|clip|footage)\b"
    ),
)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _frame_count() -> int:
    raw = _env("DESCRIBE_VIDEO_FRAME_COUNT", str(DEFAULT_FRAME_COUNT))
    try:
        return max(1, min(20, int(raw)))
    except ValueError:
        return DEFAULT_FRAME_COUNT


def _normalize(text: str) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t


def _is_url(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def _looks_like_video_source(source: str) -> bool:
    if _is_url(source):
        return True
    return Path(source).suffix.lower() in VIDEO_EXTS


def is_video_people_request(text: str) -> bool:
    t = _normalize(text)
    if not t or _REJECT.search(t):
        return False
    if any(pat.search(t) for pat in _VIDEO_PEOPLE_PATTERNS):
        return True
    source = _extract_video_source(t)
    if source and _looks_like_video_source(source):
        if re.search(r"(?i)\b(?:people|persons?|who\s+(?:is|are)\s+in|where)\b", t):
            return True
    return False


def _extract_video_source(text: str) -> str | None:
    t = _normalize(text)
    url_m = re.search(r"(https?://[^\s\"']+)", t, re.I)
    if url_m:
        return url_m.group(1).rstrip(".,)")
    path_m = re.search(
        rf"((?:~|\.|/|[\w.-]+/)[\w./ -]*\.(?:{_VIDEO_EXT_RE})|"
        rf"[\w.-]+\.(?:{_VIDEO_EXT_RE}))",
        t,
        re.I,
    )
    if path_m:
        return path_m.group(1).strip("'\"")
    return None


def _strip_video_words(text: str, source: str) -> str:
    t = text.strip()
    t = re.sub(re.escape(source), " ", t, count=1, flags=re.I)
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:who|which)\s+(?:people|persons?)\s+(?:are\s+)?(?:in|appear(?:s|ing)?\s+in)\s*",
        "",
        t,
    )
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:who\s+(?:is|are)|who\s+appears?)\s+(?:in|on)\s+",
        "",
        t,
    )
    t = re.sub(
        r"(?i)^(?:please\s+)?where\s+(?:are|is)\s+(?:the\s+)?(?:people|persons?)\s+(?:in|on)?\s*",
        "",
        t,
    )
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:identify|find|locate|spot)\s+(?:the\s+)?(?:people|persons?)\s+in\s*",
        "",
        t,
    )
    t = re.sub(r"(?i)\b(?:and\s+)?where\s+(?:they\s+are|are\s+they)\b", " ", t)
    t = re.sub(r"(?i)\b(?:who|which)\s+(?:people|persons?)\s+(?:are\s+)?(?:in|appear(?:s|ing)?\s+in)\b", " ", t)
    t = re.sub(r"(?i)\b(?:this|the|my|an?)\s+(?:video|clip|footage|recording|movie)\b", " ", t)
    t = re.sub(r"(?i)\b(?:video|clip|footage|recording|movie)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,-")
    return t


def _resolve_source(source: str) -> Path | str:
    src = source.strip().strip("'\"")
    if _is_url(src):
        return src
    path = Path(src).expanduser()
    if not path.is_file():
        raise SystemExit(f"Video not found: {src}")
    return path


def _probe_duration(source: Path | str) -> float:
    if isinstance(source, Path):
        return _ffprobe_duration(source)
    ffprobe = _which("ffprobe")
    if not ffprobe:
        return 0.0
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return max(0.5, float((proc.stdout or "0").strip()))
    except ValueError:
        return 0.0


def sample_timestamps(duration: float, count: int) -> list[float]:
    duration = max(0.5, duration)
    count = max(1, count)
    if count == 1:
        return [duration / 2]
    step = duration / (count + 1)
    return [step * (i + 1) for i in range(count)]


def extract_frame(video: Path | str, timestamp: float, out_path: Path) -> bool:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            *ffmpeg_thread_args(),
            str(out_path),
        ],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0 and out_path.is_file()


def _fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def describe_video(source: str, question: str | None = None, *, frame_count: int | None = None) -> str:
    resolved = _resolve_source(source)
    duration = _probe_duration(resolved)
    count = frame_count if frame_count is not None else _frame_count()
    timestamps = sample_timestamps(duration, count)
    prompt = (question or "").strip() or DEFAULT_PROMPT

    try:
        from arka.vision.describe import describe_source
    except ImportError as exc:
        raise SystemExit(f"Vision stack unavailable: {exc}") from exc

    work = Path(tempfile.mkdtemp(prefix="arka-video-", dir=cache_dir()))
    sections: list[str] = []
    try:
        for i, t in enumerate(timestamps):
            frame_path = work / f"frame_{i:02d}.jpg"
            if not extract_frame(resolved, t, frame_path):
                continue
            analysis = describe_source(str(frame_path), prompt)
            sections.append(f"### t={_fmt_time(t)} ({t:.1f}s)\n{analysis.strip()}")
    finally:
        for child in work.glob("*"):
            child.unlink(missing_ok=True)
        work.rmdir()

    if not sections:
        raise SystemExit(
            "Could not extract frames from video. Install ffmpeg (brew install ffmpeg) "
            "and ensure the file is a readable video."
        )

    header = f"Video: {source}\nDuration: {_fmt_time(duration)} ({duration:.1f}s) — {len(sections)} frame(s) analyzed\n"
    return header + "\n\n".join(sections)


def nl_to_argv(text: str) -> list[str]:
    if not is_video_people_request(text):
        return []
    t = _normalize(text)
    source = _extract_video_source(t)
    if not source:
        return []
    question = _strip_video_words(t, source)
    if question and question.lower() not in {"in", "and where they are", "where they are"}:
        return ["describe", source, question]
    return ["describe", source]


def cmd_describe(args: argparse.Namespace) -> int:
    question = " ".join(args.question).strip() if args.question else None
    print(describe_video(args.source, question, frame_count=args.frames))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(_normalize(" ".join(args.text)))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Find people in a video and where they appear")
    sub = p.add_subparsers(dest="cmd")

    p_desc = sub.add_parser("describe", help="Sample video frames and describe visible people")
    p_desc.add_argument("source", help="Video path or http(s) URL")
    p_desc.add_argument("question", nargs="*", help="Optional focus question")
    p_desc.add_argument(
        "--frames",
        type=int,
        default=None,
        help=f"Number of frames to sample (default {DEFAULT_FRAME_COUNT}, env DESCRIBE_VIDEO_FRAME_COUNT)",
    )
    p_desc.set_defaults(func=cmd_describe)

    p_parse = sub.add_parser("parse", help="Parse natural language → describe_video args (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    sub.add_parser("help", help="Show usage").set_defaults(
        func=lambda _a: (build_parser().print_help(), 0)[1]
    )
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
        elif _looks_like_video_source(argv[0]):
            argv = ["describe", *argv]
        else:
            print("Could not parse video people request. Try:", file=sys.stderr)
            print('  describe_video clip.mp4', file=sys.stderr)
            print('  arka who is in ~/Videos/meeting.mp4', file=sys.stderr)
            print('  arka which people are in the video and where they are', file=sys.stderr)
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
