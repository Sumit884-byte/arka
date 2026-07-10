#!/usr/bin/env python3
"""Platform-specific app/window UI how-to answers."""

from __future__ import annotations

import sys

from arka.routing.platform_howto import platform_howto_system_prompt


def answer_platform_howto(question: str, *, platform: str | None = None) -> str:
    question = " ".join((question or "").split()).strip()
    if not question:
        return ""

    if platform is None:
        try:
            from arka.platform_info import system as cached_system

            platform = cached_system()
        except ImportError:
            import sys as _sys

            if _sys.platform == "darwin":
                platform = "macos"
            elif _sys.platform.startswith("linux"):
                platform = "linux"
            elif _sys.platform == "win32":
                platform = "windows"
            else:
                platform = _sys.platform

    system = platform_howto_system_prompt(platform)
    user = f"Question: {question}"

    try:
        from arka.llm.cli import llm_complete

        return llm_complete(system, user, temperature=0.2, task="chat", skill="platform_howto").strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system, user, temperature=0.2, task="chat")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: platform_howto.py <question>", file=sys.stderr)
        return 1
    answer = answer_platform_howto(" ".join(args))
    if not answer:
        print("Could not get an answer (check LLM API keys)", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
