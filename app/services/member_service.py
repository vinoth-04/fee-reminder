"""Add, edit, search and deactivate members. Members are never deleted."""
from datetime import date

from app import config
from app.errors import AppError
from app.services import excel_service as xs
from app.services.due_date_service import calculate_due_date, parse_date
from app.services.validators import (clean_text, normalize_phone, normalize_status,
                                     parse_fee)


def public(m: dict) -> dict:
    out = dict(m)
    out["monthly_fee"] = parse_fee(m.get("monthly_fee")) or 0
    return out


def list_members(q: str = "", status: str = "") -> list[dict]:
    members = xs.records(xs.read_all()["Members"])
    q = (q or "").strip().lower()
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        members = [m for m in members if q in m["name"].lower() or q in m["member_id"].lower()
                   or (digits and digits in m["phone"])]
    if status:
        members = [m for m in members if m["status"].lower() == status.lower()]
    return [public(m) for m in members]


def get_member(member_id: str) -> dict:
    for m in xs.records(xs.read_all()["Members"]):
        if m["member_id"] == member_id:
            return public(m)
    raise AppError(404, f"Member {member_id} not found.")


def _read_fields(data: dict, partial: bool, today: date):
    """Validate the fields present in data. Returns (clean, errors)."""
    cc = config.load_settings()["default_country_code"]
    clean, errors = {}, []

    def present(k):
        return k in data and data[k] is not None

    if present("name") or not partial:
        name = clean_text(data.get("name"))
        if not name:
            errors.append("Name is required.")
        elif len(name) > 80:
            errors.append("Name must be 80 characters or fewer.")
        else:
            clean["name"] = name
    if present("phone") or not partial:
        phone = normalize_phone(data.get("phone"), cc)
        if not phone:
            errors.append("Enter a valid phone number.")
        else:
            clean["phone"] = phone
    if present("monthly_fee") or not partial:
        fee = parse_fee(data.get("monthly_fee"))
        if fee is None:
            errors.append("Monthly fee must be a number greater than 0.")
        else:
            clean["monthly_fee"] = str(fee)
    for key, label in (("joining_date", "Joining date"), ("due_date", "Due date")):
        raw = str(data.get(key) or "").strip()
        if present(key) and raw:
            d = parse_date(raw)
            if d is None:
                errors.append(f"{label} is not a valid date.")
            else:
                clean[key] = d.isoformat()
        elif present(key):
            clean[key] = ""
    if present("status") or not partial:
        status = normalize_status(data.get("status") or "Active")
        if status is None:
            errors.append("Status must be Active or Inactive.")
        else:
            clean["status"] = status
    return clean, errors


def _check_duplicate(members, name, phone, ignore_id=None):
    for m in members:
        if m["member_id"] != ignore_id and m["name"].lower() == name.lower() and m["phone"] == phone:
            raise AppError(409, f"{m['name']} with this phone number already exists ({m['member_id']}).")


def add_member(data: dict, today: date | None = None) -> dict:
    today = today or date.today()
    clean, errors = _read_fields(data, partial=False, today=today)
    if not errors and not clean.get("due_date") and not clean.get("joining_date"):
        errors.append("Enter a joining date or a due date. A due date is never guessed.")
    if errors:
        raise AppError(422, " ".join(errors))
    with xs.transaction() as wb:
        members = xs.records(wb["Members"])
        _check_duplicate(members, clean["name"], clean["phone"])
        if not clean.get("due_date"):
            clean["due_date"] = calculate_due_date(parse_date(clean["joining_date"]), today).isoformat()
        clean["member_id"] = xs.next_id(wb["Members"], "member_id", "M")
        xs.append_row(wb["Members"], clean)
    return public(clean)


def update_member(member_id: str, data: dict, today: date | None = None) -> dict:
    today = today or date.today()
    clean, errors = _read_fields(data, partial=True, today=today)
    if errors:
        raise AppError(422, " ".join(errors))
    with xs.transaction() as wb:
        members = xs.records(wb["Members"])
        current = next((m for m in members if m["member_id"] == member_id), None)
        if current is None:
            raise AppError(404, f"Member {member_id} not found.")
        merged = {**current, **clean}
        if not merged["due_date"]:
            if not merged["joining_date"]:
                raise AppError(422, "A member needs a due date or a joining date.")
            merged["due_date"] = calculate_due_date(parse_date(merged["joining_date"]), today).isoformat()
        _check_duplicate(members, merged["name"], merged["phone"], ignore_id=member_id)
        wb["Members"] = xs.pd.DataFrame(
            [merged if m["member_id"] == member_id else m for m in members],
            columns=xs.MEMBER_COLS, dtype=object)
    return public(merged)
