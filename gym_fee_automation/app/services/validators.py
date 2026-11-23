"""Small, strict validators shared by import, member and payment code."""
import re
from decimal import Decimal, InvalidOperation

PAYMENT_MODES = ["UPI", "Cash", "Bank Transfer", "Other"]

_ACTIVE = {"active", "a", "yes", "y", "true", "1", "ongoing", "current"}
_INACTIVE = {"inactive", "i", "no", "n", "false", "0", "left", "closed", "cancelled",
             "canceled", "suspended", "expired", "stopped", "discontinued"}


def normalize_phone(raw, default_cc: str = "91"):
    """Return digits with country code (e.g. 919876543210) or None if invalid."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    elif re.fullmatch(r"\d(\.\d+)?[eE]\+?\d+", s):
        try:
            s = str(int(Decimal(s)))
        except (InvalidOperation, ValueError):
            return None
    explicit = s.startswith("+") or s.startswith("00")
    digits = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digits = digits[2:]
    if explicit:
        return digits if 8 <= len(digits) <= 15 else None
    digits = digits.lstrip("0")
    if default_cc == "91":
        if len(digits) == 10 and digits[0] in "6789":
            return "91" + digits
        if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
            return digits
        return None
    if digits.startswith(default_cc) and 10 <= len(digits) <= 15:
        return digits
    return default_cc + digits if 6 <= len(digits) <= 12 else None


def parse_fee(raw):
    """Parse a money value like '₹1,000' or '1200.50'. Returns a number > 0 or None."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return None
    s = re.sub(r"(?i)(₹|rs\.?|inr|/-|,|\s)", "", s)
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite() or d <= 0 or d > 10_000_000:
        return None
    return int(d) if d == d.to_integral_value() else round(float(d), 2)


def normalize_status(raw):
    """Blank means Active. Returns 'Active', 'Inactive' or None if unrecognised."""
    s = str(raw if raw is not None else "").strip().lower()
    if not s:
        return "Active"
    if s in _ACTIVE:
        return "Active"
    if s in _INACTIVE:
        return "Inactive"
    return None


def clean_id(raw) -> str:
    s = str(raw if raw is not None else "").strip()
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s[:40]


def clean_text(raw, limit: int = 80) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(raw if raw is not None else "")).strip()
    return re.sub(r"\s+", " ", s)[:limit + 1]


def format_inr(amount) -> str:
    n = float(amount)
    whole = int(abs(n))
    frac = round(abs(n) - whole, 2)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    if frac:
        s += f"{frac:.2f}"[1:]
    return ("-" if n < 0 else "") + "₹" + s
