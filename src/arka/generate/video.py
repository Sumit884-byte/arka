#!/usr/bin/env python3
"""Generate real AI video — re-exports unified ai_video module for backward compatibility."""

from arka.media.ai_video import (
    ALLOWED_ASPECTS,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_POLLINATIONS_MODEL,
    ai_video_result,
    generate,
    generate_gemini,
    generate_pollinations,
    main,
    nl_to_argv,
)

__all__ = [
    "ALLOWED_ASPECTS",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_POLLINATIONS_MODEL",
    "ai_video_result",
    "generate",
    "generate_gemini",
    "generate_pollinations",
    "main",
    "nl_to_argv",
]

if __name__ == "__main__":
    raise SystemExit(main())
