"""macOS native WhatsApp Desktop app — send via whatsapp:// + AppleScript UI automation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import Callable
from urllib.parse import quote

from message_state import (
    chat_title_allowed,
    find_new_user_messages,
    is_user_message,
    register_outgoing,
    self_chat_enabled,
    sender_for_chat,
)
from whatsapp_automation import (
    DEBUG_LOG,
    normalize_phone,
    wa_log,
)


def _app_name() -> str:
    override = os.environ.get("ARKA_WHATSAPP_APP", "").strip()
    if override:
        return override
    for name in ("WhatsApp", "WhatsApp Desktop"):
        app_path = f"/Applications/{name}.app"
        if os.path.isdir(app_path):
            return name
    return "WhatsApp"


def _auto_send() -> bool:
    return os.environ.get("ARKA_WHATSAPP_AUTO_SEND", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _run_osascript(script: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("ARKA_WHATSAPP_OSASCRIPT_TIMEOUT", "30")),
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _ensure_accessibility_hint(err: str) -> None:
    if "-1743" in err or "Not authorised" in err or "assistive access" in err.lower():
        print(
            "WhatsApp desktop automation needs Accessibility permission for your terminal app "
            "(System Settings → Privacy & Security → Accessibility).",
            file=sys.stderr,
        )
    if "1002" in err or "keystrokes" in err.lower():
        print(
            "WhatsApp desktop automation needs Accessibility permission for your terminal app "
            "(System Settings → Privacy & Security → Accessibility).",
            file=sys.stderr,
        )


def _parse_osascript_list(out: str) -> list[str]:
    if not out:
        return []
    if out.startswith("[") and out.endswith("]"):
        try:
            data = json.loads(out.replace("\\", "\\\\"))
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except json.JSONDecodeError:
            pass
    parts = out.split(", ")
    return [p.strip() for p in parts if p.strip()]


def send_via_desktop(phone: str, message: str) -> None:
    """Open the native WhatsApp app with a pre-filled message to a phone number."""
    message = (message or "").strip()
    if not message:
        raise SystemExit("empty message")
    digits = re.sub(r"\D", "", normalize_phone(phone))
    if not digits:
        raise SystemExit(f"invalid phone: {phone}")

    app = _app_name()
    url = f"whatsapp://send?phone={digits}&text={quote(message)}"
    subprocess.run(["open", "-a", app, url], check=True)
    wa_log("send_desktop_url", app=app, to=f"+{digits}", chars=len(message))

    if _auto_send():
        time.sleep(float(os.environ.get("ARKA_WHATSAPP_SEND_DELAY", "1.2")))
        code, _out, err = _run_osascript(
            f'''
tell application "{app}" to activate
delay 0.4
tell application "System Events"
  tell process "{app}"
    keystroke return
  end tell
end tell
'''
        )
        if code != 0:
            _ensure_accessibility_hint(err)
            wa_log("send_desktop_confirm_failed", error=err)
        else:
            wa_log("send_desktop_confirm", app=app)
    register_outgoing(message)


def send_via_desktop_search(contact: str, message: str) -> None:
    """Send to a contact name via in-app search (requires Accessibility)."""
    message = (message or "").strip()
    contact = (contact or "").strip()
    if not contact or not message:
        raise SystemExit("contact and message required")
    app = _app_name()
    esc_contact = contact.replace("\\", "\\\\").replace('"', '\\"')
    _type_reply(message, focus_search=contact)
    wa_log("send_desktop_search", app=app, contact=esc_contact, chars=len(message))
    register_outgoing(message)


def _list_sidebar_chats() -> list[str]:
    app = _app_name()
    script = f'''
tell application "{app}" to activate
delay 0.25
tell application "System Events"
  tell process "{app}"
    set results to {{}}
    try
      set frontWindow to front window
      set scrollAreas to scroll areas of frontWindow
      repeat with sa in scrollAreas
        try
          set chatRows to UI elements of sa
          repeat with r in chatRows
            try
              set rowTitle to ""
              try
                set rowTitle to value of static text 1 of r as text
              end try
              if rowTitle is "" then
                try
                  set rowTitle to name of r as text
                end try
              end if
              if rowTitle is not "" then
                set end of results to rowTitle
              end if
            end try
          end repeat
        end try
      end repeat
    end try
    return results
  end tell
end tell
'''
    code, out, err = _run_osascript(script)
    if code != 0:
        _ensure_accessibility_hint(err)
        wa_log("desktop_sidebar_error", error=err)
        return []
    return _parse_osascript_list(out)


def _poll_unread() -> list[tuple[str, str]]:
    """Return [(chat_title, preview_text), ...] for chats that look unread."""
    app = _app_name()
    script = f'''
tell application "{app}" to activate
delay 0.25
tell application "System Events"
  tell process "{app}"
    set results to {{}}
    try
      set frontWindow to front window
      set scrollAreas to scroll areas of frontWindow
      repeat with sa in scrollAreas
        try
          set chatRows to UI elements of sa
          repeat with r in chatRows
            try
              set rowDesc to description of r as text
              set rowTitle to ""
              try
                set rowTitle to value of static text 1 of r as text
              end try
              if rowTitle is "" then
                try
                  set rowTitle to name of r as text
                end try
              end if
              if rowTitle is not "" then
                if rowDesc contains "unread" or rowDesc contains "Unread" then
                  set end of results to rowTitle & "|||" & rowDesc
                end if
              end if
            end try
          end repeat
        end try
      end repeat
    end try
    return results
  end tell
end tell
'''
    code, out, err = _run_osascript(script)
    if code != 0:
        _ensure_accessibility_hint(err)
        wa_log("desktop_poll_error", error=err)
        return []

    rows: list[tuple[str, str]] = []
    for chunk in _parse_osascript_list(out):
        if "|||" in chunk:
            title, desc = chunk.split("|||", 1)
        else:
            title, desc = chunk, ""
        rows.append((title.strip(), desc.strip()))
    return rows


def _open_chat_title(title: str) -> bool:
    app = _app_name()
    esc = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "{app}" to activate
delay 0.25
tell application "System Events"
  tell process "{app}"
    try
      set frontWindow to front window
      set scrollAreas to scroll areas of frontWindow
      repeat with sa in scrollAreas
        set chatRows to UI elements of sa
        repeat with r in chatRows
          try
            set rowTitle to value of static text 1 of r as text
            if rowTitle is "{esc}" then
              click r
              return "ok"
            end if
          end try
        end repeat
      end repeat
    end try
    return "miss"
  end tell
end tell
'''
    code, out, err = _run_osascript(script)
    if code != 0:
        wa_log("desktop_open_chat_error", title=title, error=err)
        return False
    return out.strip() == "ok"


def _conversation_snapshot() -> list[str]:
    """Read visible message texts from the open conversation."""
    app = _app_name()
    script = f'''
tell application "System Events"
  tell process "{app}"
    set allTexts to {{}}
    try
      set frontWindow to front window
      repeat with g in groups of frontWindow
        try
          repeat with st in static texts of g
            try
              set t to value of st as text
              if t is not "" then
                set end of allTexts to t
              end if
            end try
          end repeat
        end try
      end repeat
      repeat with sa in scroll areas of frontWindow
        try
          repeat with st in static texts of sa
            try
              set t to value of st as text
              if t is not "" then
                set end of allTexts to t
              end if
            end try
          end repeat
        end try
      end repeat
    end try
    return allTexts
  end tell
end tell
'''
    code, out, err = _run_osascript(script)
    if code != 0:
        wa_log("desktop_read_error", error=err)
        return []

    raw = _parse_osascript_list(out)
    skip = {
        "search",
        "type a message",
        "online",
        "last seen",
        "click here for contact info",
    }
    seen: set[str] = set()
    texts: list[str] = []
    for t in raw:
        t = t.strip()
        if not t or len(t) < 2:
            continue
        low = t.lower()
        if low in skip or low.startswith("messages and calls are"):
            continue
        if re.fullmatch(r"\d{1,2}:\d{2}(\s?[AP]M)?", t, re.I):
            continue
        if re.fullmatch(r"(today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday).*", low):
            continue
        if t in seen:
            continue
        seen.add(t)
        texts.append(t)
    return texts


def _type_reply(message: str, *, focus_search: str = "") -> None:
    app = _app_name()
    message = (message or "").strip()
    if not message:
        return
    esc = message.replace("\\", "\\\\").replace('"', '\\"')
    use_clipboard = len(message) > 180 or "\n" in message or '"' in message
    if focus_search:
        esc_contact = focus_search.replace("\\", "\\\\").replace('"', '\\"')
        search_block = f'''
    keystroke "f" using command down
    delay 0.3
    keystroke "a" using command down
    keystroke "{esc_contact}"
    delay 1.0
    key code 36
    delay 0.8
'''
    else:
        search_block = ""

    if use_clipboard:
        send_block = '''
    set the clipboard to "''' + esc + '''"
    delay 0.1
    keystroke "v" using command down
    delay 0.15
    keystroke return
'''
    else:
        send_block = f'''
    keystroke "{esc}"
    delay 0.15
    keystroke return
'''

    script = f'''
tell application "{app}" to activate
delay 0.2
tell application "System Events"
  tell process "{app}"
{search_block}{send_block}
  end tell
end tell
'''
    code, _out, err = _run_osascript(script)
    if code != 0:
        _ensure_accessibility_hint(err)
        wa_log("desktop_reply_error", error=err)
        return
    wa_log("desktop_reply_sent", app=app, chars=len(message))


def _chats_to_monitor(allowed: list[str]) -> list[tuple[str, bool]]:
    """Return [(chat_title, is_unread), ...] to check this poll cycle."""
    targets: dict[str, bool] = {}
    sidebar = _list_sidebar_chats()

    for title in sidebar:
        if chat_title_allowed(title, allowed):
            targets[title] = targets.get(title, False)

    for title, _desc in _poll_unread():
        if chat_title_allowed(title, allowed):
            targets[title] = True

    return sorted(targets.items(), key=lambda x: (not x[1], x[0].lower()))


def listen_inbox_desktop(
    senders: list[str],
    handler: Callable[[str, str], str | None],
    *,
    poll: float = 5.0,
    reply_in_browser: bool = True,
) -> None:
    """Poll native WhatsApp Desktop for messages from allowed senders."""
    app = _app_name()
    allowed = [normalize_phone(s) for s in senders if normalize_phone(s)]
    if not allowed:
        raise SystemExit("No allowed senders")

    subprocess.run(["open", "-a", app], check=False)
    wa_log(
        "listen_desktop_start",
        app=app,
        senders=allowed,
        poll=poll,
        self_chat=self_chat_enabled(len(allowed)),
    )
    print(f"Using native {app} (desktop). Grant Accessibility to your terminal if prompted.")
    if self_chat_enabled(len(allowed)):
        print("Self-chat mode: watching “You” / message-yourself + allowed numbers.")
    print(f"Log: {DEBUG_LOG}")

    while True:
        try:
            for title, is_unread in _chats_to_monitor(allowed):
                if not _open_chat_title(title):
                    continue
                time.sleep(0.55)
                snapshot = _conversation_snapshot()
                if not snapshot:
                    continue

                new_msgs = find_new_user_messages(title, snapshot)
                if not new_msgs and is_unread and snapshot:
                    for text in reversed(snapshot):
                        if is_user_message(text):
                            new_msgs = [text]
                            break

                sender = sender_for_chat(title, allowed)
                for text in new_msgs:
                    if not is_user_message(text):
                        wa_log("skip", reason="bot/outgoing echo", from_=sender, text=text[:120])
                        continue
                    wa_log("message_in", from_=sender, chat=title, text=text[:200], via="desktop")
                    reply = handler(sender, text)
                    if reply and reply_in_browser:
                        register_outgoing(reply)
                        _type_reply(reply)
                        wa_log("message_out", to=sender, chat=title, text=reply[:200], via="desktop")
        except Exception as exc:
            wa_log("listen_desktop_error", error=str(exc))
        time.sleep(max(1.0, float(poll)))
