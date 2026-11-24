"""WhatsApp click-to-chat helpers. Nothing is sent automatically: the admin opens the
link, checks the message and presses Send in WhatsApp themselves."""
import re
from urllib.parse import quote

from app.config import DEFAULT_TEMPLATES, TEMPLATE_KEYS
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


def render_template(template: str, name: str, amount, due, gym_name: str = "") -> str:
    """Fill {name}, {full_name}, {amount}, {due_date}, {gym_name}. Unknown {words} are left as typed."""
    full = (name or "").strip()
    values = {"name": full.split()[0] if full else "there", "full_name": full or "there",
              "amount": format_inr(amount), "due_date": _date_text(due) if due else "",
              "gym_name": gym_name or ""}
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template or "").strip()


def build_message(reminder_type: str, name: str, amount, due, gym_name: str = "", template: str | None = None) -> str:
    """template=None uses the default text for this reminder type."""
    template = template or DEFAULT_TEMPLATES[TEMPLATE_KEYS[reminder_type]]
    return render_template(template, name, amount, due, gym_name)


def build_link(phone: str, message: str) -> str:
    """wa.me click-to-chat link. Opens WhatsApp (app or web) with the message prefilled."""
    phone = re.sub(r"\D", "", str(phone or ""))
    return f"https://wa.me/{phone}?text={quote(message)}"
