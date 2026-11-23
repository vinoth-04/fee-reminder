"""WhatsApp Web automation service using Playwright with persistent Chrome profile."""
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from app import config
from app.services.validators import format_inr

# ==============================================================================
# CSS Selectors for WhatsApp Web
# ==============================================================================
SELECTOR_CHAT_LIST = "div[id='pane-side'], div[data-tab='3'], div[data-testid='chat-list']"
SELECTOR_COMPOSE_BOX = "footer div[contenteditable='true'][role='textbox'], div[contenteditable='true'][data-tab='10'], div[contenteditable='true'][data-tab='6']"
SELECTOR_SEND_BUTTON = "button[aria-label='Send'], span[data-icon='send'], button[data-tab='11']"
SELECTOR_OUTGOING_BUBBLE = "div.message-out, div[data-testid='msg-container']"
SELECTOR_POPUP_CONTAINER = "div[data-animate-modal-popup='true'], div[role='dialog'], div[data-testid='popup-contents']"
SELECTOR_POPUP_DISMISS_BUTTON = "div[data-animate-modal-popup='true'] button, div[role='dialog'] button, button:has-text('OK')"
SELECTOR_QR_CODE = "canvas[aria-label='Scan me!'], div[data-ref]"
SELECTOR_MAIN_PANEL = "div[id='main'], div[data-testid='conversation-panel-wrapper']"

# ==============================================================================
# Environment Configuration
# ==============================================================================
WHATSAPP_HEADLESS = os.environ.get("WHATSAPP_HEADLESS", "false").lower() in ("1", "true", "yes")
WHATSAPP_SESSION_DIR = Path(os.environ.get("WHATSAPP_SESSION_DIR", config.DATA_DIR / "whatsapp_profile"))
DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "91").lstrip("+").strip()
MIN_SEND_DELAY = float(os.environ.get("WHATSAPP_MIN_DELAY", "5.0"))
MAX_SEND_DELAY = float(os.environ.get("WHATSAPP_MAX_DELAY", "15.0"))

logger = logging.getLogger("gym.whatsapp")


def mask_phone(phone: str) -> str:
    """Masks phone numbers for log privacy (e.g. 919876543210 -> 91******3210)."""
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) <= 4:
        return "***"
    if len(digits) <= 7:
        return digits[:2] + "***" + digits[-2:]
    return digits[:2] + "*" * (len(digits) - 6) + digits[-4:]


def normalize_phone(phone: str, default_country_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Normalizes phone numbers, prepending default country code if missing."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    code = (default_country_code or "91").lstrip("+").strip()
    if len(digits) == 10:
        return f"{code}{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"{code}{digits[1:]}"
    return digits


class WhatsAppService:
    """Playwright-based WhatsApp Web automation service."""

    def __init__(self):
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whatsapp_worker")
        self._playwright = None
        self._context = None
        self._page = None
        self._last_send_time = 0.0

    def _is_running(self) -> bool:
        if self._context is None or self._page is None:
            return False
        try:
            return not self._page.is_closed()
        except Exception:
            return False

    def _start_sync(self) -> tuple[bool, str]:
        """Launches persistent Chrome context on the dedicated worker thread."""
        try:
            from playwright.sync_api import sync_playwright

            WHATSAPP_SESSION_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Starting WhatsApp Playwright browser (session: %s, headless: %s)",
                        WHATSAPP_SESSION_DIR, WHATSAPP_HEADLESS)

            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(WHATSAPP_SESSION_DIR),
                channel="chrome",
                headless=WHATSAPP_HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-session-crashed-bubble",
                ],
                viewport={"width": 1280, "height": 800},
            )
            # Find an active open page or create a fresh one
            active_pages = [p for p in self._context.pages if not p.is_closed()]
            self._page = active_pages[0] if active_pages else self._context.new_page()
            self._page.set_default_timeout(30000)
            return True, ""
        except Exception as e:
            logger.exception("Failed to launch Playwright browser context: %s", e)
            self._close_sync()
            return False, f"Browser launch failed: {e}"

    def _ensure_page(self) -> tuple[bool, str]:
        """Ensures that the browser context and active page are open and healthy."""
        if not self._is_running():
            self._close_sync()
            started, err = self._start_sync()
            if not started:
                return False, err

        try:
            if self._page is None or self._page.is_closed():
                active_pages = [p for p in self._context.pages if not p.is_closed()] if self._context else []
                if active_pages:
                    self._page = active_pages[0]
                elif self._context:
                    self._page = self._context.new_page()
                    self._page.set_default_timeout(30000)
                else:
                    self._close_sync()
                    return self._start_sync()
            return True, ""
        except Exception as e:
            logger.warning("Browser or context was closed (%s). Restarting fresh context...", e)
            self._close_sync()
            return self._start_sync()

    def _check_invalid_number_popup(self) -> tuple[bool, str]:
        """Checks for invalid number modal matching 'invalid' or 'isn't on WhatsApp'."""
        if not self._page:
            return False, ""
        try:
            popup = self._page.locator(SELECTOR_POPUP_CONTAINER).first
            if popup.is_visible(timeout=3000):
                text = (popup.inner_text() or "").lower()
                if "invalid" in text or "isn't on whatsapp" in text or "is not on whatsapp" in text:
                    logger.warning("Detected invalid number popup: %s", text.strip())
                    try:
                        self._page.locator(SELECTOR_POPUP_DISMISS_BUTTON).first.click(timeout=2000)
                    except Exception:
                        pass
                    return True, "Phone number is invalid or not registered on WhatsApp."
        except Exception:
            pass
        return False, ""

    def _send_message_sync(self, phone: str, text: str) -> tuple[bool, str]:
        """Synchronously navigates, pre-fills, sends, and verifies message delivery."""
        try:
            # 1. Start or recover browser if closed
            ready, err = self._ensure_page()
            if not ready:
                return False, err

            clean_phone = normalize_phone(phone)
            if not clean_phone:
                return False, "Phone number is empty or invalid."

            masked = mask_phone(clean_phone)

            # 6. Random delay between consecutive sends (configurable 5-15s)
            if self._last_send_time > 0:
                delay = random.uniform(MIN_SEND_DELAY, MAX_SEND_DELAY)
                elapsed = time.time() - self._last_send_time
                if elapsed < delay:
                    wait_time = delay - elapsed
                    logger.info("Applying inter-send delay of %.1fs before sending to %s", wait_time, masked)
                    time.sleep(wait_time)

            logger.info("Navigating to WhatsApp Web for recipient %s", masked)
            target_url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={quote(text)}"

            try:
                self._page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                err_text = str(e).lower()
                if "closed" in err_text or "target" in err_text:
                    logger.warning("Target page/browser was closed during goto (%s). Restarting and retrying...", e)
                    self._close_sync()
                    ready, restart_err = self._start_sync()
                    if not ready:
                        return False, f"Browser crashed and failed to restart: {restart_err}"
                    self._page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                else:
                    raise

            # Check for invalid number popup
            is_invalid, invalid_msg = self._check_invalid_number_popup()
            if is_invalid:
                self._last_send_time = time.time()
                return False, invalid_msg

            # Wait for compose box
            try:
                self._page.wait_for_selector(SELECTOR_COMPOSE_BOX, timeout=30000)
            except Exception:
                is_invalid, invalid_msg = self._check_invalid_number_popup()
                if is_invalid:
                    self._last_send_time = time.time()
                    return False, invalid_msg
                return False, f"Timed out waiting for chat to load for {masked}."

            compose_box = self._page.locator(SELECTOR_COMPOSE_BOX).first
            initial_content = (compose_box.inner_text() or "").strip()

            # Attempt click on Send button
            send_btn = self._page.locator(SELECTOR_SEND_BUTTON).first
            clicked = False
            try:
                if send_btn.is_visible(timeout=4000):
                    send_btn.click(timeout=3000)
                    clicked = True
            except Exception:
                pass

            # 3. Use Enter fallback ONLY if compose box actually contains prefilled text
            remaining_content = (compose_box.inner_text() or "").strip()
            if not clicked or remaining_content:
                if initial_content or remaining_content:
                    logger.debug("Send button not clicked or text remaining; pressing Enter fallback")
                    compose_box.press("Enter")

            # 3. Confirm message went out (compose box empty again or outgoing bubble visible)
            confirmed = False
            deadline = time.time() + 10.0
            while time.time() < deadline:
                current_box_text = (compose_box.inner_text() or "").strip()
                if not current_box_text:
                    confirmed = True
                    break
                try:
                    if self._page.locator(SELECTOR_OUTGOING_BUBBLE).first.is_visible(timeout=500):
                        confirmed = True
                        break
                except Exception:
                    pass
                time.sleep(0.5)

            self._last_send_time = time.time()

            if not confirmed:
                logger.error("Message send unconfirmed for %s (compose box still has content)", masked)
                return False, "Failed to confirm message sent (compose box not cleared)."

            logger.info("Message successfully sent and confirmed for %s", masked)
            return True, "Message sent successfully."

        except Exception as e:
            self._last_send_time = time.time()
            logger.exception("Unexpected error sending WhatsApp message to %s: %s", mask_phone(phone), e)
            err_text = str(e).lower()
            if "target page, context or browser has been closed" in err_text or "target closed" in err_text or "closed" in err_text:
                self._close_sync()
            return False, str(e)

    def _is_logged_in_sync(self) -> bool:
        if not self._is_running():
            return False
        try:
            return bool(self._page.locator(SELECTOR_CHAT_LIST).first.is_visible(timeout=3000))
        except Exception:
            return False

    def _close_sync(self):
        if self._context:
            try:
                self._context.close()
            except Exception as e:
                logger.warning("Error closing context: %s", e)
            self._context = None
            self._page = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                logger.warning("Error stopping playwright: %s", e)
            self._playwright = None

    # Public API
    def send_message(self, phone: str, text: str) -> tuple[bool, str]:
        with self._lock:
            future = self._executor.submit(self._send_message_sync, phone, text)
            return future.result()

    def is_logged_in(self) -> bool:
        with self._lock:
            future = self._executor.submit(self._is_logged_in_sync)
            return future.result()

    def close(self):
        with self._lock:
            future = self._executor.submit(self._close_sync)
            return future.result()


# Singleton instance
_service = WhatsAppService()


def send_message(phone: str, text: str) -> tuple[bool, str]:
    """Public interface: sends message via Playwright WhatsApp Web. Returns (bool, str)."""
    return _service.send_message(phone, text)


def is_logged_in() -> bool:
    """Public interface: checks if WhatsApp Web is authenticated."""
    return _service.is_logged_in()


def close() -> None:
    """Public interface: closes browser and frees resources."""
    _service.close()


# ==============================================================================
# Helper message builders (preserved for compatibility)
# ==============================================================================
def _date_text(d) -> str:
    return f"{d.day} {d:%B %Y}"


def build_message(reminder_type: str, name: str, amount, due, gym_name: str = "") -> str:
    first = (name or "").split()[0] if name else "there"
    fee = format_inr(amount)
    if reminder_type == "Before Due":
        body = (f"Your gym membership fee of {fee} is due on {_date_text(due)}.\n\n"
                "Please complete your payment on time.")
    elif reminder_type == "Due Date":
        body = (f"This is a friendly reminder that your gym membership fee of {fee} is due today.\n\n"
                "Please complete your payment.")
    else:
        body = (f"Our records show that your gym membership fee of {fee} is still pending.\n\n"
                "Kindly complete the payment at your earliest convenience.")
    sign = "Thank you!" + (f"\n{gym_name}" if gym_name else "")
    return f"Hello {first},\n\n{body}\n\n{sign}"


def build_link(phone: str, message: str) -> str:
    phone = phone.replace("+", "").replace(" ", "")
    return f"https://web.whatsapp.com/send?phone={phone}&text={quote(message)}"
