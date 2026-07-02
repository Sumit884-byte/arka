"""WhatsApp Web automation — Selenium listen + optional pywhatkit send."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

try:
    from arka.paths import cache_dir
except ImportError:
    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

CACHE = cache_dir()
DEBUG_LOG = CACHE / "whatsapp_debug.log"
PROFILE_DIR = CACHE / "whatsapp-chrome-profile"
SEEN_PATH = CACHE / "whatsapp_seen.json"


def _host_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _backend() -> str:
    raw = os.environ.get("ARKA_WHATSAPP_BACKEND", "auto").strip().lower()
    if raw in ("desktop", "native", "app"):
        return "desktop"
    if raw in ("web", "selenium", "chrome", "browser"):
        return "web"
    if _host_platform() == "macos":
        return "desktop"
    return "web"


def backend_label() -> str:
    b = _backend()
    if b == "desktop" and _host_platform() == "macos":
        app = os.environ.get("ARKA_WHATSAPP_APP", "").strip() or "WhatsApp"
        for name in ("WhatsApp", "WhatsApp Desktop"):
            if os.path.isdir(f"/Applications/{name}.app"):
                app = os.environ.get("ARKA_WHATSAPP_APP", "").strip() or name
                break
        return f"desktop ({app}.app)"
    if b == "desktop":
        return "desktop"
    return "web (Selenium + WhatsApp Web)"


def wa_log(event: str, **fields) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **fields}
    line = json.dumps(row, ensure_ascii=False, default=str)
    with open(DEBUG_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    if os.environ.get("ARKA_WHATSAPP_DEBUG", "0").strip().lower() in ("1", "true", "yes"):
        print(line, file=sys.stderr, flush=True)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    default_cc = re.sub(r"\D", "", os.environ.get("ARKA_WHATSAPP_DEFAULT_CC", "91"))
    if len(digits) == 10 and default_cc:
        digits = default_cc + digits
    return "+" + digits


def phone_matches(a: str, b: str) -> bool:
    da = re.sub(r"\D", "", normalize_phone(a))
    db = re.sub(r"\D", "", normalize_phone(b))
    if not da or not db:
        return False
    if da == db:
        return True
    if len(da) >= 10 and len(db) >= 10:
        return da[-10:] == db[-10:]
    return da.endswith(db) or db.endswith(da)


def _load_seen() -> set[str]:
    if not SEEN_PATH.is_file():
        return set()
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        return set(data.get("keys", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_seen(keys: set[str]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    trimmed = list(keys)[-1000:]
    SEEN_PATH.write_text(json.dumps({"keys": trimmed}, indent=2), encoding="utf-8")


def send_instant(phone: str, message: str) -> None:
    """Send a WhatsApp message via native desktop app (macOS) or web automation."""
    message = (message or "").strip()
    if not message:
        raise SystemExit("empty message")
    target = normalize_phone(phone) if re.search(r"\d", phone or "") else (phone or "").strip()
    if not target:
        raise SystemExit(f"invalid phone/contact: {phone}")

    if _backend() == "desktop" and _host_platform() == "macos":
        from macos_desktop import send_via_desktop, send_via_desktop_search

        digits = re.sub(r"\D", "", normalize_phone(phone))
        if len(digits) >= 7:
            send_via_desktop(phone, message)
        else:
            send_via_desktop_search(phone, message)
        return

    try:
        import pywhatkit as pwk  # type: ignore

        digits = re.sub(r"\D", "", normalize_phone(phone))
        wa_log("send_pywhatkit", to=normalize_phone(phone) or phone, chars=len(message))
        pwk.sendwhatmsg_instantly(
            f"+{digits}",
            message,
            wait_time=int(os.environ.get("ARKA_WHATSAPP_SEND_WAIT", "12")),
            tab_close=True,
            close_time=3,
        )
        return
    except ImportError:
        pass

    _send_via_selenium(normalize_phone(phone) or phone, message)


def _build_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    if os.environ.get("ARKA_WHATSAPP_HEADLESS", "0").strip().lower() in ("1", "true", "yes"):
        opts.add_argument("--headless=new")
    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(1280, 900)
    return driver


def _wait_logged_in(driver, timeout: float = 120) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get("https://web.whatsapp.com/")
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='3'], #side")
        )
    )


def _send_via_selenium(phone: str, message: str) -> None:
    driver = _build_driver()
    try:
        _wait_logged_in(driver)
        _open_chat(driver, phone)
        _type_reply(driver, message)
        wa_log("send_selenium", to=phone, chars=len(message))
    finally:
        driver.quit()


def _open_chat(driver, phone: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    query = re.sub(r"\D", "", normalize_phone(phone))
    search = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='3']"))
    )
    search.click()
    search.send_keys(Keys.CONTROL + "a")
    search.send_keys(Keys.BACKSPACE)
    search.send_keys(query)
    time.sleep(1.5)
    search.send_keys(Keys.ENTER)
    time.sleep(1.0)


def _type_reply(driver, text: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    box = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "footer div[contenteditable='true'][data-tab='10'], footer div[contenteditable='true']")
        )
    )
    box.click()
    box.send_keys(text)
    box.send_keys(Keys.ENTER)


def _chat_rows(driver):
    from selenium.webdriver.common.by import By

    return driver.find_elements(By.CSS_SELECTOR, "#pane-side div[role='listitem'], #pane-side div[role='row']")


def _row_title(row) -> str:
    for sel in ("span[title]", "span[dir='auto']"):
        try:
            el = row.find_element("css selector", sel)
            title = (el.get_attribute("title") or el.text or "").strip()
            if title:
                return title
        except Exception:
            continue
    return ""


def _row_unread(row) -> bool:
    try:
        badges = row.find_elements(By.CSS_SELECTOR, "span[aria-label*='unread'], span[data-icon='muted']")
        for el in badges:
            label = (el.get_attribute("aria-label") or "").lower()
            if "unread" in label:
                return True
        green = row.find_elements("css selector", "span[aria-label*='unread message']")
        if green:
            return True
    except Exception:
        pass
    return False


def _latest_incoming(driver) -> tuple[str, str]:
    from selenium.webdriver.common.by import By

    incoming = driver.find_elements(By.CSS_SELECTOR, "div.message-in")
    if not incoming:
        return "", ""
    last = incoming[-1]
    try:
        text_el = last.find_element(By.CSS_SELECTOR, "span.selectable-text, span[dir='ltr'], span[dir='auto']")
        text = (text_el.text or "").strip()
    except Exception:
        text = (last.text or "").strip()
    msg_id = last.get_attribute("data-id") or text
    return msg_id, text


def listen_inbox(
    senders: list[str],
    handler: Callable[[str, str], str | None],
    *,
    poll: float = 5.0,
    reply_in_browser: bool = True,
) -> None:
    """Poll WhatsApp for messages from allowed senders; handler returns optional reply."""
    allowed = [normalize_phone(s) for s in senders if normalize_phone(s)]
    if not allowed:
        raise SystemExit("No allowed senders")

    if _backend() == "desktop" and _host_platform() == "macos":
        from macos_desktop import listen_inbox_desktop

        listen_inbox_desktop(
            senders,
            handler,
            poll=poll,
            reply_in_browser=reply_in_browser,
        )
        return

    try:
        import selenium  # noqa: F401
    except ImportError as exc:
        raise SystemExit("Install: pip install selenium") from exc

    seen = _load_seen()
    driver = _build_driver()
    wa_log("listen_start", senders=allowed, poll=poll, reply_in_browser=reply_in_browser)
    try:
        _wait_logged_in(driver, timeout=180)
        wa_log("listen_ready")
        while True:
            try:
                for row in _chat_rows(driver):
                    title = _row_title(row)
                    if not title:
                        continue
                    if not any(phone_matches(title, s) for s in allowed):
                        if not _row_unread(row):
                            continue
                        digits = re.sub(r"\D", "", title)
                        if digits and not any(phone_matches(digits, s) for s in allowed):
                            continue
                    if not _row_unread(row):
                        continue
                    row.click()
                    time.sleep(0.8)
                    msg_id, text = _latest_incoming(driver)
                    if not text:
                        continue
                    sender = normalize_phone(title) or title
                    key = msg_id or f"{sender}|{text}"
                    if key in seen:
                        continue
                    seen.add(key)
                    _save_seen(seen)
                    wa_log("message_in", from_=sender, text=text[:200])
                    reply = handler(sender, text)
                    if reply and reply_in_browser:
                        try:
                            from message_state import format_bot_reply, register_outgoing

                            reply = format_bot_reply(reply[:1500])
                            register_outgoing(reply)
                        except ImportError:
                            pass
                        _type_reply(driver, reply)
                        wa_log("message_out", to=sender, text=reply[:200])
            except Exception as exc:
                wa_log("listen_error", error=str(exc))
            time.sleep(max(1.0, float(poll)))
    finally:
        driver.quit()
