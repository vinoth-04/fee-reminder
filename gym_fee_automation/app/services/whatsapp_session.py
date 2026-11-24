"""Optional WhatsApp Web link (Playwright). The admin scans a QR from the dashboard once;
the saved browser profile keeps the link. Everything is opt-in: if Playwright is missing or
the link is down, reminders still work through click-to-chat (whatsapp_service.build_link).

NOTE: automating WhatsApp Web is unofficial and can get a number banned. Keep volume low;
the daily cap and random delays below exist for that reason."""
import json
import logging
import os
import random
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import quote

from app import config
from app.services.whatsapp_service import mask_phone, normalize_phone

logger = logging.getLogger("gym.whatsapp")

SESSION_DIR = Path(os.environ.get("WHATSAPP_SESSION_DIR", config.DATA_DIR / "whatsapp_profile"))
COUNTER_PATH = config.DATA_DIR / "whatsapp_sent_today.json"
HEADLESS = os.environ.get("WHATSAPP_HEADLESS", "true").lower() in ("1", "true", "yes")
CHANNEL = os.environ.get("WHATSAPP_BROWSER_CHANNEL", "chrome")      # installed Chrome; falls back to bundled Chromium
DAILY_CAP = int(os.environ.get("WHATSAPP_DAILY_CAP", "40"))
MIN_DELAY = float(os.environ.get("WHATSAPP_MIN_DELAY", "5"))
MAX_DELAY = float(os.environ.get("WHATSAPP_MAX_DELAY", "15"))
QR_WAIT_SECONDS = 150
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

SEL_CHAT_LIST = "div[id='pane-side'], div[data-testid='chat-list']"
SEL_QR = "canvas[aria-label='Scan me!'], div[data-ref] canvas, div[data-ref]"
SEL_COMPOSE = "footer div[contenteditable='true'][role='textbox'], div[contenteditable='true'][data-tab='10']"
SEL_SEND = "button[aria-label='Send'], span[data-icon='send']"
SEL_POPUP = "div[data-animate-modal-popup='true'], div[role='dialog']"
SEL_POPUP_OK = "div[data-animate-modal-popup='true'] button, div[role='dialog'] button"

DISCONNECTED, STARTING, QR, CONNECTED, ERROR = "disconnected", "starting", "qr", "connected", "error"


def installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


# ---- daily counter (persisted so a restart doesn't reset the safety cap) ----
def sent_today() -> int:
    try:
        d = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
        return int(d["count"]) if d.get("date") == date.today().isoformat() else 0
    except (OSError, ValueError, KeyError):
        return 0


def _bump_counter() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    COUNTER_PATH.write_text(json.dumps({"date": date.today().isoformat(), "count": sent_today() + 1}),
                            encoding="utf-8")


class _Session:
    def __init__(self):
        self._lock = threading.Lock()                      # guards the fields below
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wa")  # Playwright is thread-bound
        self._pw = self._ctx = self._page = None
        self._state, self._message, self._qr = DISCONNECTED, "", None
        self._connecting = False
        self._last_send = 0.0

    # ---------- state (never blocks on the browser thread) ----------
    def _set(self, state=None, message=None, qr="keep"):
        with self._lock:
            if state is not None:
                self._state = state
            if message is not None:
                self._message = message
            if qr != "keep":
                self._qr = qr

    def status(self) -> dict:
        with self._lock:
            state, message = self._state, self._message
        return {"installed": installed(), "state": state, "message": message,
                "has_saved_session": SESSION_DIR.exists() and any(SESSION_DIR.iterdir()),
                "sent_today": sent_today(), "daily_cap": DAILY_CAP}

    def qr_png(self):
        with self._lock:
            return self._qr if self._state == QR else None

    def is_connected(self) -> bool:
        with self._lock:
            return self._state == CONNECTED

    # ---------- browser thread ----------
    def _open(self):
        from playwright.sync_api import sync_playwright
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        opts = dict(user_data_dir=str(SESSION_DIR), headless=HEADLESS, user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    args=["--no-first-run", "--no-default-browser-check", "--disable-dev-shm-usage"])
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(channel=CHANNEL, **opts)
        except Exception as e:
            logger.warning("Chrome channel '%s' unavailable (%s); trying bundled Chromium", CHANNEL, e)
            self._ctx = self._pw.chromium.launch_persistent_context(**opts)
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        self._page = pages[0] if pages else self._ctx.new_page()
        self._page.set_default_timeout(30000)

    def _close_browser(self):
        for obj, fn in ((self._ctx, "close"), (self._pw, "stop")):
            if obj:
                try:
                    getattr(obj, fn)()
                except Exception as e:
                    logger.warning("WhatsApp browser %s failed: %s", fn, e)
        self._pw = self._ctx = self._page = None

    def _visible(self, selector: str, timeout=1500) -> bool:
        try:
            return bool(self._page.locator(selector).first.is_visible(timeout=timeout))
        except Exception:
            return False

    def _connect_sync(self):
        try:
            self._set(STARTING, "Opening WhatsApp Web...", None)
            if self._page is None or self._page.is_closed():
                self._close_browser()
                self._open()
            self._page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=45000)
            deadline = time.time() + QR_WAIT_SECONDS
            while time.time() < deadline:
                if self._visible(SEL_CHAT_LIST):
                    self._set(CONNECTED, "WhatsApp is linked.", None)
                    return
                if self._visible(SEL_QR):
                    try:
                        png = self._page.locator(SEL_QR).first.screenshot(timeout=3000)
                        self._set(QR, "Scan this QR with WhatsApp > Linked devices > Link a device.", png)
                    except Exception:
                        pass
                else:
                    self._set(STARTING, "Loading WhatsApp Web...")
                time.sleep(2)
            self._set(ERROR, "QR was not scanned in time. Click Connect to try again.", None)
            self._close_browser()
        except Exception as e:
            logger.exception("WhatsApp connect failed")
            self._close_browser()
            self._set(ERROR, f"Could not start the browser: {e}", None)
        finally:
            with self._lock:
                self._connecting = False

    def _popup_invalid(self) -> bool:
        try:
            popup = self._page.locator(SEL_POPUP).first
            if popup.is_visible(timeout=3000):
                text = (popup.inner_text() or "").lower()
                if "invalid" in text or "isn't on whatsapp" in text or "not on whatsapp" in text:
                    try:
                        self._page.locator(SEL_POPUP_OK).first.click(timeout=2000)
                    except Exception:
                        pass
                    return True
        except Exception:
            pass
        return False

    def _send_sync(self, phone: str, text: str) -> tuple[bool, str]:
        masked = mask_phone(phone)
        try:
            if self._page is None or self._page.is_closed():
                self._set(ERROR, "The WhatsApp browser was closed. Click Connect again.")
                return False, "WhatsApp browser is not running. Reconnect WhatsApp."
            wait = random.uniform(MIN_DELAY, MAX_DELAY) - (time.time() - self._last_send)
            if self._last_send and wait > 0:
                time.sleep(wait)
            self._page.goto(f"https://web.whatsapp.com/send?phone={phone}&text={quote(text)}",
                            wait_until="domcontentloaded", timeout=45000)
            try:
                self._page.wait_for_selector(SEL_COMPOSE, timeout=30000)
            except Exception:
                if self._visible(SEL_QR, 500):
                    self._set(DISCONNECTED, "WhatsApp was unlinked from the phone. Connect again.", None)
                    return False, "WhatsApp is no longer linked. Reconnect WhatsApp."
                if self._popup_invalid():
                    return False, "Phone number is invalid or not on WhatsApp."
                return False, f"Chat did not load for {masked}."
            box = self._page.locator(SEL_COMPOSE).first
            if not (box.inner_text() or "").strip():
                return False, "Message text did not load into the chat."
            try:
                self._page.locator(SEL_SEND).first.click(timeout=4000)
            except Exception:
                box.press("Enter")
            deadline = time.time() + 10
            while time.time() < deadline:
                if not (box.inner_text() or "").strip():
                    _bump_counter()
                    return True, ""
                time.sleep(0.5)
            return False, "Could not confirm the message was sent."
        except Exception as e:
            logger.exception("WhatsApp send to %s failed", masked)
            return False, str(e)
        finally:
            self._last_send = time.time()

    def _disconnect_sync(self, forget: bool):
        self._close_browser()
        if forget:
            shutil.rmtree(SESSION_DIR, ignore_errors=True)
        self._set(DISCONNECTED, "Disconnected." if not forget else "Unlinked. A new QR is needed to connect.", None)

    # ---------- public ----------
    def connect(self) -> dict:
        if not installed():
            self._set(ERROR, "Playwright is not installed. Run: pip install playwright")
            return self.status()
        with self._lock:
            if self._connecting or self._state == CONNECTED:
                return self.status()
            self._connecting = True
        self._pool.submit(self._connect_sync)
        return self.status()

    def send(self, phone: str, text: str) -> tuple[bool, str]:
        if not self.is_connected():
            return False, "WhatsApp is not connected."
        return self._pool.submit(self._send_sync, phone, text).result()

    def disconnect(self, forget: bool = False) -> dict:
        self._pool.submit(self._disconnect_sync, forget).result()
        return self.status()

    def shutdown(self):
        try:
            self._pool.submit(self._close_browser).result(timeout=20)
        except Exception:
            pass


_session = _Session()
status, qr_png, is_connected = _session.status, _session.qr_png, _session.is_connected
connect, send, disconnect, shutdown = _session.connect, _session.send, _session.disconnect, _session.shutdown


def send_to(phone: str, text: str) -> tuple[bool, str]:
    """Normalize the number with the gym's country code, then send."""
    clean = normalize_phone(phone, config.load_settings()["default_country_code"])
    if not clean:
        return False, "Phone number is empty or invalid."
    return send(clean, text)
