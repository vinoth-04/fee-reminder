"""WhatsApp click-to-chat helpers. Nothing is sent automatically: the admin opens the
link, checks the message and presses Send in WhatsApp themselves."""
import re
from urllib.parse import quote

from app.services.validators import format_inr

DEFAULT_COUNTRY_CODE = "91"


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
    """wa.me click-to-chat link. Opens WhatsApp (app or web) with the message prefilled."""
    phone = re.sub(r"\D", "", str(phone or ""))
    return f"https://wa.me/{phone}?text={quote(message)}"
