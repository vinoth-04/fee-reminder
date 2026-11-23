"""Payments are tracked per member and per billing month (YYYY-MM)."""
from datetime import date

from app import db
from app.errors import AppError
from app.services.due_date_service import (anchor_day, due_date_for_month, next_month_key,
                                           parse_date, split_month)
from app.services.validators import PAYMENT_MODES, parse_fee

_SELECT = """SELECT p.payment_id, p.member_id, p.payment_month, p.amount, p.payment_date,
                    p.payment_status, p.payment_mode,
                    COALESCE(m.name, '') AS member_name, COALESCE(m.phone, '') AS phone
             FROM payments p LEFT JOIN members m ON m.member_id = p.member_id"""


def list_payments(status: str = "", month: str = "", member_id: str = "") -> list[dict]:
    sql, params = _SELECT + " WHERE 1=1", []
    if status:
        sql += " AND lower(p.payment_status) = ?"
        params.append(status.lower())
    if month:
        sql += " AND p.payment_month = ?"
        params.append(month)
    if member_id:
        sql += " AND p.member_id = ?"
        params.append(member_id)
    with db.read() as conn:
        return db.rows(conn, sql + " ORDER BY p.payment_month DESC, p.payment_id DESC", params)


def _plan(conn, month: str):
    result = {"month": month, "created": 0, "already_exists": 0,
              "not_started": 0, "no_due_info": 0, "inactive": 0}
    existing = {r[0] for r in conn.execute("SELECT member_id FROM payments WHERE payment_month = ?", (month,))}
    new_rows = []
    for m in db.rows(conn, "SELECT member_id, monthly_fee, joining_date, due_date, status "
                           "FROM members ORDER BY member_id"):
        if m["status"] != "Active":
            result["inactive"] += 1
            continue
        joining, due = parse_date(m["joining_date"]), parse_date(m["due_date"])
        anchor = anchor_day(joining, due)
        if anchor is None:
            result["no_due_info"] += 1
        elif joining and due_date_for_month(month, anchor) < joining:
            result["not_started"] += 1
        elif m["member_id"] in existing:
            result["already_exists"] += 1
        else:
            new_rows.append((m["member_id"], month, m["monthly_fee"]))
    result["created"] = len(new_rows)
    return result, new_rows


def generate_billing(month: str, dry_run: bool = False, today: date | None = None) -> dict:
    """Create a Pending payment for every active member for one billing month.

    This is the explicit step that makes a month 'generated'. Existing records
    are never duplicated or changed (the database also enforces one per member per month).
    """
    try:
        split_month(month)
    except ValueError as e:
        raise AppError(422, str(e))
    with db.read() as conn:
        result, _ = _plan(conn, month)
    if dry_run or not result["created"]:
        return result
    db.backup("billing")
    with db.transaction() as conn:
        result, new_rows = _plan(conn, month)
        for member_id, ym, amount in new_rows:
            conn.execute("INSERT INTO payments (payment_id, member_id, payment_month, amount, payment_status) "
                         "VALUES (?, ?, ?, ?, 'Pending')",
                         (db.next_id(conn, "payments", "payment_id", "P", 6), member_id, ym, amount))
    return result


def mark_paid(payment_id: str, payment_date: str | None = None, payment_mode: str = "Cash",
              amount=None, today: date | None = None) -> dict:
    today = today or date.today()
    mode = next((m for m in PAYMENT_MODES if m.lower() == str(payment_mode or "").strip().lower()), None)
    if mode is None:
        raise AppError(422, "Payment mode must be one of: " + ", ".join(PAYMENT_MODES) + ".")
    paid_on = parse_date(payment_date) if payment_date else today
    if paid_on is None:
        raise AppError(422, "Payment date is not a valid date.")
    if paid_on > today:
        raise AppError(422, "Payment date cannot be in the future.")
    fee = None
    if amount not in (None, ""):
        fee = parse_fee(amount)
        if fee is None:
            raise AppError(422, "Amount must be a number greater than 0.")
    with db.transaction() as conn:
        p = conn.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
        if p is None:
            raise AppError(404, f"Payment {payment_id} not found.")
        if p["payment_status"] == "Paid":
            raise AppError(409, "This payment is already marked as paid.")
        conn.execute("UPDATE payments SET payment_status='Paid', payment_date=?, payment_mode=?, amount=? "
                     "WHERE payment_id=?", (paid_on.isoformat(), mode, fee if fee is not None else p["amount"], payment_id))
        m = conn.execute("SELECT joining_date, due_date FROM members WHERE member_id = ?", (p["member_id"],)).fetchone()
        if m:
            joining, due = parse_date(m["joining_date"]), parse_date(m["due_date"])
            anchor = anchor_day(joining, due)
            if anchor and (due is None or due <= due_date_for_month(p["payment_month"], anchor)):
                new_due = due_date_for_month(next_month_key(p["payment_month"]), anchor)
                conn.execute("UPDATE members SET due_date = ? WHERE member_id = ?",
                             (new_due.isoformat(), p["member_id"]))
        return db.rows(conn, _SELECT + " WHERE p.payment_id = ?", (payment_id,))[0]


def summary() -> dict:
    with db.read() as conn:
        months = db.rows(conn, """
            SELECT payment_month AS month,
                   COALESCE(SUM(CASE WHEN payment_status = 'Paid' THEN amount END), 0) AS collected,
                   COALESCE(SUM(CASE WHEN payment_status = 'Pending' THEN amount END), 0) AS pending,
                   SUM(payment_status = 'Paid') AS paid_count,
                   SUM(payment_status = 'Pending') AS pending_count
            FROM payments GROUP BY payment_month ORDER BY payment_month DESC""")
    return {"total_collected": sum(m["collected"] for m in months),
            "pending_amount": sum(m["pending"] for m in months), "months": months}