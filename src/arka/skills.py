"""Map portable skills to Python scripts."""

from __future__ import annotations

import sys

from arka.dispatch import run_script


def run_password(args: list[str]) -> int:
    if not args:
        print("Usage: arka password save|set|get|list|delete|rotate ...")
        print("  arka password save <name> [length]  — generate + store")
        print("  arka password set <name> <secret>   — store existing password")
        print("  arka password get <name>")
        return 0

    sub = args[0].lower()
    rest = args[1:]

    if sub in ("save", "store", "remember"):
        if not rest:
            print("Usage: arka password save <name> [length]", file=sys.stderr)
            return 1
        name = rest[0]
        length = rest[1] if len(rest) > 1 and rest[1].isdigit() else "20"
        return run_script("arka_password_vault.py", ["generate", name, "--length", length])

    if sub in ("set", "put", "write"):
        if len(rest) < 2:
            print("Usage: arka password set <name> <password>", file=sys.stderr)
            return 1
        name, pwd = rest[0], " ".join(rest[1:])
        return run_script("arka_password_vault.py", ["set", name, "--password", pwd])

    if sub in ("get", "show", "retrieve"):
        if not rest:
            print("Usage: arka password get <name>", file=sys.stderr)
            return 1
        return run_script("arka_password_vault.py", ["get", rest[0]])

    if sub in ("list", "ls"):
        return run_script("arka_password_vault.py", ["list"])

    if sub in ("delete", "rm", "remove"):
        if not rest:
            return 1
        return run_script("arka_password_vault.py", ["delete", rest[0]])

    if sub in ("rotate", "renew"):
        if not rest:
            return 1
        extra = ["--length", rest[1]] if len(rest) > 1 and rest[1].isdigit() else []
        return run_script("arka_password_vault.py", ["rotate", rest[0], *extra])

    if sub.isdigit():
        # One-time generation handled in CLI layer
        return 1

    return run_script("arka_password_vault.py", args)


def run_chat_ask(question: str, *, deep: bool = False) -> int:
    cmd = ["ask", question]
    if deep:
        cmd.append("--deep")
    return run_script("arka_chat.py", cmd)


def run_chat_calc(expression: str) -> int:
    return run_script("arka_chat.py", ["calc", expression])


def run_chat_weather(query: str) -> int:
    parts = query.split() if query else []
    return run_script("arka_chat.py", ["weather", *parts])
