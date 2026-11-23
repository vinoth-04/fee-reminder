"""Builds personalised messages and WhatsApp Click-to-Chat links. Never sends anything."""
from urllib.parse import quote

from app.services.validators import format_inr


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
    return f"https://wa.me/{phone}?text={quote(message, safe='')}"
