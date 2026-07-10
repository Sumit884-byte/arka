"""Detect local OS/app UI how-to questions and build platform-specific prompts."""

from __future__ import annotations

import re

_EXCLUDE = re.compile(
    r"(?i)\bhow\s+to\s+(?:install|download|setup|set\s*up|uninstall|upgrade|update|fix|invest|survive|get\s+by)\b"
)
_UI_ACTION = re.compile(
    r"(?i)\b(?:close|minimize|maximize|quit|exit|hide|show|switch|move|reload|refresh|bookmark|"
    r"find|search|zoom|fullscreen|restore|snap|split|pin|unpin|mute|screenshot|print|duplicate|"
    r"reopen|undo|redo|copy|paste|cut|navigate|hard\s+refresh|incognito|private\s+(?:window|tab)|"
    r"split\s+screen)\b"
)
_UI_TARGET = re.compile(
    r"(?i)\b(?:window|tab|tabs|browser|menu|toolbar|sidebar|address\s*bar|title\s*bar|dev\s*tools|"
    r"settings|preferences|split\s+view|brave|chrome|chromium|firefox|safari|edge|opera|arc|vivaldi)\b"
)
_HOWTO = re.compile(
    r"(?i)\b(?:how\s+(?:do\s+i|can\s+i|to)|keyboard\s+shortcut|shortcut\s+(?:for|to)|"
    r"what(?:'s|\s+is)\s+the\s+(?:shortcut|key))\b"
)
_ON_APP = re.compile(r"(?i)\b(?:on|in|with|using)\s+(?:brave|chrome|chromium|firefox|safari|edge|opera|arc|vivaldi)\b")


def is_platform_howto_question(text: str) -> bool:
    """True for local app/window UI how-tos (close tab, shortcuts), not install/fix/invest."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return False
    if _EXCLUDE.search(clean):
        return False
    if not _UI_ACTION.search(clean) or not _UI_TARGET.search(clean):
        return False
    return bool(_HOWTO.search(clean) or _ON_APP.search(clean))


def platform_label(platform: str) -> str:
    plat = (platform or "").strip().lower()
    if plat == "macos":
        return "macOS (Darwin)"
    if plat == "linux":
        return "Linux"
    if plat == "windows":
        return "Windows"
    return plat or "unknown"


def platform_ui_shortcuts(platform: str) -> str:
    plat = (platform or "").strip().lower()
    if plat == "macos":
        return (
            "macOS UI: red close button top-left of each window; yellow minimizes; green zooms. "
            "Common shortcuts: Cmd+W closes tab/window, Cmd+Q quits the app, Cmd+Tab switches apps, "
            "Cmd+H hides app, Cmd+M minimizes window."
        )
    if plat == "linux":
        return (
            "Linux UI: window close/minimize/maximize buttons usually top-right (depends on DE). "
            "Common shortcuts: Ctrl+W closes tab, Alt+F4 closes window, Super key opens app launcher."
        )
    if plat == "windows":
        return (
            "Windows UI: close (X), minimize, maximize buttons top-right. "
            "Common shortcuts: Ctrl+W closes tab, Alt+F4 closes window, Win key opens Start."
        )
    return "Use shortcuts and window controls appropriate for the user's OS only."


def platform_howto_system_prompt(platform: str) -> str:
    label = platform_label(platform)
    shortcuts = platform_ui_shortcuts(platform)
    return (
        f"You are a helpful assistant on {label}. "
        f"Answer UI/how-to questions ONLY for {label}. {shortcuts} "
        "Do NOT mention Windows, Linux, or macOS alternatives unless the user explicitly asks. "
        "Give 2-4 short, direct sentences suitable for text-to-speech."
    )


def platform_web_answer_system_prompt(platform: str) -> str:
    """Lighter platform hint for web_answer LLM fallback."""
    label = platform_label(platform)
    shortcuts = platform_ui_shortcuts(platform)
    return (
        "You are a helpful assistant. Answer clearly in 2-5 short sentences for TTS. "
        "Start with [FROM MEMORY] or [FROM SEARCH]. Be factual. "
        f"The user is on {label}. {shortcuts} "
        f"When the question is about app/window UI, answer ONLY for {label} — do not list other OSes."
    )
