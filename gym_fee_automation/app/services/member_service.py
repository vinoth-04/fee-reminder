"""Add, edit, search and deactivate members. Members are never deleted."""
import sqlite3
from datetime import date

from app import config, db
from app.errors import AppError
from app.services import excel_service as xs
from app.services.due_date_service import calculate_due_date, parse_date
from app.services.validators import clean_text, normalize_phone, normalize_status, parse_fee

COLS = "member_id, name, phone, monthly_fee, joining_date, due_date, status"


def _sync_to_excel(clean: dict):
    """Keep Excel workbook in sync with SQLite member changes."""
    try:
        with xs.transaction() as wb:
            df = wb["Members"]
            idx = df.index[df["member_id"] == clean["member_id"]]
            if len(idx) > 0:
                for k in xs.MEMBER_COLS:
                    if k in clean:
                        df.at[idx[0], k] = str(clean[k])
            else:
                row = {c: str(clean.get(c, "")) for c in xs.MEMBER_COLS}
                xs.append_row(df, row)
    except Exception:
        pass


def list_members(q: str = "", status: str = "") -> list[dict]:
    sql, params = f"SELECT {COLS} FROM members WHERE 1=1", []
    q = (q or "").strip().lower()
    if q:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        digits = "".join(ch for ch in q if ch.isdigit())
        clause = "(lower(name) LIKE ? ESCAPE '\\' OR lower(member_id) LIKE ? ESCAPE '\\'"
        params += [f"%{esc}%", f"%{esc}%"]
        if digits:
            clause += " OR phone LIKE ?"
            params.append(f"%{digits}%")
        sql += " AND " + clause + ")"
    if status:
        sql += " AND lower(status) = ?"
        params.append(status.lower())
    with db.read() as conn:
        return db.rows(conn, sql + " ORDER BY member_id", params)


def get_member(member_id: str) -> dict:
    with db.read() as conn:
        found = db.rows(conn, f"SELECT {COLS} FROM members WHERE member_id = ?", (member_id,))
    if not found:
        raise AppError(404, f"Member {member_id} not found.")
    return found[0]


def _read_fields(data: dict, partial: bool):
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
            clean["monthly_fee"] = fee
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


def _duplicate(conn, name, phone, ignore_id=None):
    row = conn.execute("SELECT member_id, name FROM members WHERE lower(name) = ? AND phone = ? AND member_id != ?",
                       (name.lower(), phone, ignore_id or "")).fetchone()
    if row:
        raise AppError(409, f"{row['name']} with this phone number already exists ({row['member_id']}).")


def add_member(data: dict, today: date | None = None) -> dict:
    today = today or date.today()
    clean, errors = _read_fields(data, partial=False)
    if not errors and not clean.get("due_date") and not clean.get("joining_date"):
        errors.append("Enter a joining date or a due date. A due date is never guessed.")
    if errors:
        raise AppError(422, " ".join(errors))
    clean.setdefault("joining_date", "")
    with db.transaction() as conn:
        _duplicate(conn, clean["name"], clean["phone"])
        if not clean.get("due_date"):
            clean["due_date"] = calculate_due_date(parse_date(clean["joining_date"]), today).isoformat()
        clean["member_id"] = db.next_id(conn, "members", "member_id", "M")
        try:
            conn.execute(f"INSERT INTO members ({COLS}) VALUES (?,?,?,?,?,?,?)",
                         [clean[c.strip()] for c in COLS.split(",")])
        except sqlite3.IntegrityError as e:
            raise AppError(409, f"Could not save member: {e}")
    _sync_to_excel(clean)
    return clean


def update_member(member_id: str, data: dict, today: date | None = None) -> dict:
    today = today or date.today()
    clean, errors = _read_fields(data, partial=True)
    if errors:
        raise AppError(422, " ".join(errors))
    with db.transaction() as conn:
        rows = db.rows(conn, f"SELECT {COLS} FROM members WHERE member_id = ?", (member_id,))
        if not rows:
            raise AppError(404, f"Member {member_id} not found.")
        merged = {**rows[0], **clean}
        if not merged["due_date"]:
            if not merged["joining_date"]:
                raise AppError(422, "A member needs a due date or a joining date.")
            merged["due_date"] = calculate_due_date(parse_date(merged["joining_date"]), today).isoformat()
        _duplicate(conn, merged["name"], merged["phone"], ignore_id=member_id)
        try:
            conn.execute("UPDATE members SET name=?, phone=?, monthly_fee=?, joining_date=?, due_date=?, status=? "
                         "WHERE member_id=?",
                         (merged["name"], merged["phone"], merged["monthly_fee"], merged["joining_date"],
                          merged["due_date"], merged["status"], member_id))
        except sqlite3.IntegrityError as e:
            raise AppError(409, f"Could not save member: {e}")
    _sync_to_excel(merged)
    return merged