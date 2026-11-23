"""Date parsing and monthly billing-cycle maths. Never guesses a due date."""
import calendar
import re
from datetime import date, datetime, timedelta

_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d-%m-%y", "%d/%m/%y", "%d.%m.%y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y",
    "%d-%b-%y", "%d %b, %Y", "%d %B, %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d",
    "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S",
]


def parse_date(value):
    """Parse many date styles (day first, as used in India). Returns a date or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none", "null", "-"}:
        return None
    result = None
    if re.fullmatch(r"\d{5}(\.\d+)?", s):  # Excel serial number
        serial = int(float(s))
        if 20000 <= serial <= 80000:
            result = date(1899, 12, 30) + timedelta(days=serial)
    else:
        for fmt in _FORMATS:
            try:
                result = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
    if result and not (1990 <= result.year <= 2100):
        return None
    return result


def last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def date_in_month(year: int, month: int, day: int) -> date:
    """The given day in a month, clamped to the month's last day (31 Jan -> 28 Feb)."""
    return date(year, month, min(day, last_day(year, month)))


def add_months(d: date, months: int, anchor: int | None = None) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    return date_in_month(year, month + 1, anchor or d.day)


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def split_month(ym: str):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(ym)):
        raise ValueError(f"Invalid month '{ym}'. Use YYYY-MM.")
    return int(ym[:4]), int(ym[5:7])


def next_month_key(ym: str) -> str:
    y, m = split_month(ym)
    return month_key(date_in_month(y + (m == 12), 1 if m == 12 else m + 1, 1))


def due_date_for_month(ym: str, anchor: int) -> date:
    y, m = split_month(ym)
    return date_in_month(y, m, anchor)


def anchor_day(joining: date | None, due: date | None) -> int | None:
    """The day of the month payments fall on.

    A supplied due date keeps its own day. If that day was only a clamped
    month-end (e.g. 28 Feb for a 31st joiner) the joining day is used instead.
    """
    if due and joining:
        clamped = due.day == last_day(due.year, due.month) and due.day < joining.day
        return joining.day if (due.day == joining.day or clamped) else due.day
    if due:
        return due.day
    if joining:
        return joining.day
    return None


def calculate_due_date(joining: date, today: date | None = None) -> date:
    """Next payment date for a member with no supplied due date.

    Cycle: joining day each month. A member who has not joined yet owes on the
    joining date; otherwise it is the first cycle date on or after today.
    """
    today = today or date.today()
    if joining >= today:
        return joining
    k = max(1, (today.year - joining.year) * 12 + today.month - joining.month - 1)
    while add_months(joining, k) < today:
        k += 1
    return add_months(joining, k)
