#!/usr/bin/env python3
"""Generate music — backward-compatible entrypoint for arka.generate.music."""

from arka.media.music_generate import (
    DEFAULT_DURATION,
    DEFAULT_MODEL,
    MAX_DURATION,
    MIN_DURATION,
    _compose_input,
    _extract_lyrics,
    _extract_music_prompt,
    build_parser,
    cmd_check,
    cmd_generate,
    cmd_parse,
    generate,
    generate_pollinations,
    generate_synthesize,
    main,
    music_generate_result,
    nl_to_argv,
)

__all__ = [
    "DEFAULT_DURATION",
    "DEFAULT_MODEL",
    "MAX_DURATION",
    "MIN_DURATION",
    "_compose_input",
    "_extract_lyrics",
    "_extract_music_prompt",
    "build_parser",
    "cmd_check",
    "cmd_generate",
    "cmd_parse",
    "generate",
    "generate_pollinations",
    "generate_synthesize",
    "main",
    "music_generate_result",
    "nl_to_argv",
]

if __name__ == "__main__":
    raise SystemExit(main())
