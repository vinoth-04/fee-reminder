"""Payments are tracked per member and per billing month (YYYY-MM)."""
from datetime import date

from app.errors import AppError
from app.services import excel_service as xs
from app.services.due_date_service import (anchor_day, due_date_for_month, month_key,
                                           next_month_key, parse_date, split_month)
from app.services.validators import PAYMENT_MODES, parse_fee


def _public(p: dict, names: dict) -> dict:
    out = dict(p)
    out["amount"] = parse_fee(p["amount"]) or 0
    out["member_name"] = names.get(p["member_id"], "")
    return out


def list_payments(status: str = "", month: str = "", member_id: str = "") -> list[dict]:
    wb = xs.read_all()
    names = {m["member_id"]: m["name"] for m in xs.records(wb["Members"])}
    rows = xs.records(wb["Payments"])
    if status:
        rows = [p for p in rows if p["payment_status"].lower() == status.lower()]
    if month:
        rows = [p for p in rows if p["payment_month"] == month]
    if member_id:
        rows = [p for p in rows if p["member_id"] == member_id]
    rows.sort(key=lambda p: (p["payment_month"], p["payment_id"]), reverse=True)
    return [_public(p, names) for p in rows]


def generate_billing(month: str, dry_run: bool = False, today: date | None = None) -> dict:
    """Create a Pending payment for every active member for one billing month.

    This is the explicit step that makes a month 'generated'. Existing records
    are never duplicated or changed.
    """
    try:
        split_month(month)
    except ValueError as e:
        raise AppError(422, str(e))
    result = {"month": month, "created": 0, "already_exists": 0,
              "not_started": 0, "no_due_info": 0, "inactive": 0}
    with xs.transaction(backup_reason=None if dry_run else "billing") as wb:
        members = xs.records(wb["Members"])
        existing = {(p["member_id"], p["payment_month"]) for p in xs.records(wb["Payments"])}
        new_rows = []
        for m in members:
            if m["status"] != "Active":
                result["inactive"] += 1
                continue
            joining, due = parse_date(m["joining_date"]), parse_date(m["due_date"])
            anchor = anchor_day(joining, due)
            if anchor is None:
                result["no_due_info"] += 1
                continue
            if joining and due_date_for_month(month, anchor) < joining:
                result["not_started"] += 1
                continue
            if (m["member_id"], month) in existing:
                result["already_exists"] += 1
                continue
            new_rows.append({"member_id": m["member_id"], "payment_month": month,
                             "amount": m["monthly_fee"], "payment_status": "Pending"})
        result["created"] = len(new_rows)
        if not dry_run:
            for r in new_rows:
                r["payment_id"] = xs.next_id(wb["Payments"], "payment_id", "P", 6)
                xs.append_row(wb["Payments"], r)
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
    with xs.transaction(backup_reason="markpaid") as wb:
        payments = wb["Payments"]
        idx = payments.index[payments["payment_id"] == payment_id]
        if len(idx) == 0:
            raise AppError(404, f"Payment {payment_id} not found.")
        i = idx[0]
        if payments.at[i, "payment_status"] == "Paid":
            raise AppError(409, "This payment is already marked as paid.")
        payments.at[i, "payment_status"] = "Paid"
        payments.at[i, "payment_date"] = paid_on.isoformat()
        payments.at[i, "payment_mode"] = mode
        if fee is not None:
            payments.at[i, "amount"] = str(fee)
        month, member_id = payments.at[i, "payment_month"], payments.at[i, "member_id"]
        members = wb["Members"]
        mi = members.index[members["member_id"] == member_id]
        if len(mi):
            j = mi[0]
            joining, due = parse_date(members.at[j, "joining_date"]), parse_date(members.at[j, "due_date"])
            anchor = anchor_day(joining, due)
            if anchor:
                if due is None or due <= due_date_for_month(month, anchor):
                    members.at[j, "due_date"] = due_date_for_month(next_month_key(month), anchor).isoformat()
        names = {m["member_id"]: m["name"] for m in xs.records(members)}
        return _public(xs.records(payments)[i], names)


def summary() -> dict:
    wb = xs.read_all()
    months: dict[str, dict] = {}
    collected = pending = 0.0
    for p in xs.records(wb["Payments"]):
        amt = parse_fee(p["amount"]) or 0
        row = months.setdefault(p["payment_month"], {"month": p["payment_month"], "collected": 0,
                                                     "pending": 0, "paid_count": 0, "pending_count": 0})
        if p["payment_status"] == "Paid":
            collected += amt
            row["collected"] += amt
            row["paid_count"] += 1
        else:
            pending += amt
            row["pending"] += amt
            row["pending_count"] += 1
    return {"total_collected": collected, "pending_amount": pending,
            "months": sorted(months.values(), key=lambda r: r["month"], reverse=True)}
