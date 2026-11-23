"""One-time WhatsApp Web QR code login script.

Opens Google Chrome visibly using the persistent session profile.
Scans and waits until login is complete, saving authentication state.
"""
import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
from app.services.whatsapp_service import (
    WHATSAPP_SESSION_DIR,
    SELECTOR_CHAT_LIST,
    SELECTOR_QR_CODE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("whatsapp_login")


def main():
    WHATSAPP_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Opening visible Google Chrome for WhatsApp Web authentication...")
    logger.info("Session profile directory: %s", WHATSAPP_SESSION_DIR)

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(WHATSAPP_SESSION_DIR),
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                viewport={"width": 1280, "height": 800},
            )
        except Exception as e:
            logger.error("Failed to launch Google Chrome: %s", e)
            logger.error("Please ensure Google Chrome is installed on this system.")
            sys.exit(1)

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(180000)

        logger.info("Navigating to https://web.whatsapp.com ...")
        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        logger.info("=" * 60)
        logger.info("SCAN QR CODE: Open WhatsApp on your phone -> Linked Devices -> Link a Device")
        logger.info("Waiting for QR code scan and authentication (up to 3 minutes)...")
        logger.info("=" * 60)

        try:
            page.wait_for_selector(SELECTOR_CHAT_LIST, timeout=180000)
            logger.info("SUCCESS: WhatsApp Web logged in successfully!")
            logger.info("Authentication session saved to: %s", WHATSAPP_SESSION_DIR)
            logger.info("You can now send WhatsApp messages from FastAPI.")
        except Exception as e:
            logger.error("Login timed out or failed: %s", e)
            context.close()
            sys.exit(1)

        # Brief pause to ensure cookies/localStorage write to disk
        page.wait_for_timeout(3000)
        context.close()
        logger.info("Browser closed. Setup complete.")


if __name__ == "__main__":
    main()
