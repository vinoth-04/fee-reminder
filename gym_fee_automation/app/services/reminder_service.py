"""Prepares reminders from pending payments. Messages are never sent automatically."""
from collections import Counter
from datetime import date, datetime, timedelta

from app import config, db as _db
from app.errors import AppError
from app.services import excel_service as xs
from app.services.due_date_service import anchor_day, due_date_for_month, parse_date
from app.services.validators import normalize_phone, parse_fee
from app.config import TEMPLATE_KEYS
from app.services import whatsapp_session
from app.services.whatsapp_service import build_link, build_message

KIND_TO_TYPE = {"due_soon": "Before Due", "due_today": "Due Date", "overdue": "Overdue"}
STATUSES = ["Prepared", "Sent", "Failed"]


def _pending_items(wb, today: date):
    """Pending payments of active members, each with its due date for that month."""
    with _db.read() as conn:
        rows = _db.rows(conn, """
            SELECT p.payment_id, p.member_id, p.payment_month, p.amount, p.payment_status,
                   m.name, m.phone, m.joining_date, m.due_date, m.status AS member_status
            FROM payments p JOIN members m ON m.member_id = p.member_id
            WHERE p.payment_status = 'Pending' AND m.status = 'Active'
        """)
    for r in rows:
        anchor = anchor_day(parse_date(r["joining_date"]), parse_date(r["due_date"]))
        if anchor is None:
            continue
        try:
            due = due_date_for_month(r["payment_month"], anchor)
        except ValueError:
            continue
        member = {"member_id": r["member_id"], "name": r["name"], "phone": r["phone"],
                  "joining_date": r["joining_date"], "due_date": r["due_date"],
                  "status": r["member_status"]}
        payment = {"payment_id": r["payment_id"], "member_id": r["member_id"],
                   "payment_month": r["payment_month"], "amount": r["amount"],
                   "payment_status": r["payment_status"]}
        yield {"payment": payment, "member": member, "due": due}


def _logs_by_payment(wb=None) -> dict:
    out: dict = {}
    with _db.read() as conn:
        logs = _db.rows(conn, "SELECT * FROM reminder_logs")
    for log in logs:
        out.setdefault((log["member_id"], log["payment_month"]), []).append(log)
    return out


def _kind(due: date, today: date, s: dict):
    delta = (today - due).days
    if delta == 0:
        return "due_today"
    if delta > 0:
        return "overdue"
    if -delta <= s["before_due_days"]:
        return "due_soon"
    return None


def _item(it: dict, kind: str, s: dict, logs: list, today: date) -> dict:
    m, p, due = it["member"], it["payment"], it["due"]
    rtype = KIND_TO_TYPE[kind]
    amount = parse_fee(p["amount"]) or 0
    message = build_message(rtype, m["name"], amount, due, s["gym_name"], s[TEMPLATE_KEYS[rtype]])
    phone = normalize_phone(m["phone"], s["default_country_code"])
    last = max(logs, key=lambda l: l["reminder_id"]) if logs else None
    return {
        "payment_id": p["payment_id"], "member_id": m["member_id"], "name": m["name"],
        "phone": phone or m["phone"], "phone_valid": bool(phone),
        "amount": amount, "payment_month": p["payment_month"], "due_date": due.isoformat(),
        "days_overdue": max(0, (today - due).days), "reminder_type": rtype,
        "message": message, "whatsapp_link": build_link(phone, message) if phone else None,
        "last_log": ({"reminder_id": last["reminder_id"], "reminder_type": last["reminder_type"],
                      "reminder_date": last["reminder_date"], "status": last["status"]} if last else None),
    }


def list_reminders(today: date | None = None) -> dict:
    """Live view for the admin: who is due soon, due today or overdue, with message previews."""
    today = today or date.today()
    s = config.load_settings()
    logs = _logs_by_payment()
    out = {"due_soon": [], "due_today": [], "overdue": []}
    for it in _pending_items(None, today):
        kind = _kind(it["due"], today, s)
        if kind:
            key = (it["member"]["member_id"], it["payment"]["payment_month"])
            out[kind].append(_item(it, kind, s, logs.get(key, []), today))
    out["due_soon"].sort(key=lambda r: r["due_date"])
    out["overdue"].sort(key=lambda r: r["due_date"])
    return out


def _scheduled_type(due: date, today: date, logs: list, s: dict):
    """Which reminder (if any) is owed today for this pending payment."""
    done = {l["reminder_type"] for l in logs}
    delta = (today - due).days
    if delta < 0 and -delta <= s["before_due_days"]:
        return "Before Due" if "Before Due" not in done else None
    if delta == 0:
        return "Due Date" if "Due Date" not in done else None
    if delta >= s["overdue_days"]:
        overdue = [parse_date(l["reminder_date"]) for l in logs if l["reminder_type"] == "Overdue"]
        overdue = [d for d in overdue if d]
        if not overdue:
            return "Overdue"
        return "Overdue" if (today - max(overdue)).days >= s["followup_days"] else None
    return None


def _new_log(wb, it, rtype, s, today):
    m, p = it["member"], it["payment"]
    log = {
        "reminder_id": xs.next_id(wb["Reminder Logs"], "reminder_id", "R", 6),
        "member_id": m["member_id"], "payment_month": p["payment_month"],
        "reminder_date": today.isoformat(), "reminder_type": rtype,
        "message": build_message(rtype, m["name"], parse_fee(p["amount"]) or 0, it["due"], s["gym_name"],
                                 s[TEMPLATE_KEYS[rtype]]),
        "status": "Prepared", "sent_at": "",
    }
    xs.append_row(wb["Reminder Logs"], log)
    return log


def prepare_reminders(today: date | None = None) -> dict:
    """Daily job: create 'Prepared' log rows for reminders owed today (no duplicates)."""
    today = today or date.today()
    s = config.load_settings()
    prepared, skipped = [], []
    with xs.transaction() as wb:
        logs = _logs_by_payment()
        for it in _pending_items(None, today):
            m = it["member"]
            key = (m["member_id"], it["payment"]["payment_month"])
            rtype = _scheduled_type(it["due"], today, logs.get(key, []), s)
            if not rtype:
                continue
            if not normalize_phone(m["phone"], s["default_country_code"]):
                skipped.append({"member_id": m["member_id"], "name": m["name"],
                                "reason": "Invalid phone number"})
                continue
            log = _new_log(wb, it, rtype, s, today)
            logs.setdefault(key, []).append(log)
            prepared.append({"reminder_id": log["reminder_id"], "member_id": m["member_id"],
                             "name": m["name"], "reminder_type": rtype,
                             "payment_month": it["payment"]["payment_month"]})
    return {"date": today.isoformat(), "prepared": prepared, "skipped": skipped}


def prepare_for_payment(payment_id: str, today: date | None = None) -> dict:
    """Admin clicked 'Open WhatsApp': make sure a Prepared log exists for this reminder."""
    today = today or date.today()
    s = config.load_settings()
    with xs.transaction() as wb:
        logs = _logs_by_payment()
        for it in _pending_items(None, today):
            if it["payment"]["payment_id"] != payment_id:
                continue
            kind = _kind(it["due"], today, s)
            if not kind:
                raise AppError(422, "This payment is not due yet, so no reminder is needed.")
            rtype = KIND_TO_TYPE[kind]
            key = (it["member"]["member_id"], it["payment"]["payment_month"])
            same_day = [l for l in logs.get(key, [])
                        if l["reminder_type"] == rtype and l["reminder_date"] == today.isoformat()]
            log = same_day[0] if same_day else _new_log(wb, it, rtype, s, today)
            return {"reminder_id": log["reminder_id"], "status": log["status"]}
    raise AppError(404, "No pending payment found for an active member with that ID.")


def mark_sent(payment_id: str, today: date | None = None) -> dict:
    """Admin pressed Send in WhatsApp: make sure today's reminder log exists and mark it Sent."""
    reminder_id = prepare_for_payment(payment_id, today)["reminder_id"]
    res = set_status(reminder_id, "Sent")
    return {"reminder_id": reminder_id, "status": "Sent", "success": True,
            "error": "", "sent_at": res.get("sent_at", "")}


def send_reminder(payment_id: str, today: date | None = None) -> dict:
    """Auto-send through the linked WhatsApp. Raises 409 if not linked (the UI then falls back
    to click-to-chat) and 429 once the daily safety cap is reached."""
    if not whatsapp_session.is_connected():
        raise AppError(409, "WhatsApp is not connected. Connect it, or use Open WhatsApp.")
    st = whatsapp_session.status()
    if st["sent_today"] >= st["daily_cap"]:
        raise AppError(429, f"Daily auto-send limit reached ({st['daily_cap']}). Use Open WhatsApp for the rest.")
    reminder_id = prepare_for_payment(payment_id, today)["reminder_id"]
    log = next((l for l in xs.records(xs.read_all()["Reminder Logs"]) if l["reminder_id"] == reminder_id), None)
    if not log:
        raise AppError(404, f"Reminder log {reminder_id} not found.")
    with _db.read() as conn:
        m = _db.rows(conn, "SELECT phone FROM members WHERE member_id = ?", (log["member_id"],))
    ok, error = whatsapp_session.send_to(m[0]["phone"] if m else "", log.get("message", ""))
    res = set_status(reminder_id, "Sent" if ok else "Failed")
    return {"reminder_id": reminder_id, "status": res["status"], "success": ok, "error": error,
            "sent_at": res.get("sent_at", "")}


def get_logs(limit: int = 100, status: str = "") -> list[dict]:
    s = config.load_settings()
    wb = xs.read_all()
    with _db.read() as conn:
        members = {m["member_id"]: m for m in _db.rows(conn, "SELECT member_id, name, phone FROM members")}
    rows = xs.records(wb["Reminder Logs"])
    if status:
        rows = [r for r in rows if r["status"].lower() == status.lower()]
    rows.sort(key=lambda r: r["reminder_id"], reverse=True)
    out = []
    for r in rows[:max(1, min(limit, 1000))]:
        m = members.get(r["member_id"], {})
        phone = normalize_phone(m.get("phone", ""), s["default_country_code"])
        out.append({**r, "name": m.get("name", ""), "phone_valid": bool(phone),
                    "whatsapp_link": build_link(phone, r["message"]) if phone else None})
    return out


def set_status(reminder_id: str, status: str) -> dict:
    status = next((x for x in STATUSES if x.lower() == str(status).strip().lower()), None)
    if status is None:
        raise AppError(422, "Status must be Prepared, Sent or Failed.")
    with xs.transaction() as wb:
        logs = wb["Reminder Logs"]
        idx = logs.index[logs["reminder_id"] == reminder_id]
        if len(idx) == 0:
            raise AppError(404, f"Reminder {reminder_id} not found.")
        i = idx[0]
        logs.at[i, "status"] = status
        logs.at[i, "sent_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "Sent" else ""
        return {"reminder_id": reminder_id, "status": status, "sent_at": logs.at[i, "sent_at"]}


def activity_report(days: int = 30, today: date | None = None) -> dict:
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    rows = [r for r in xs.records(xs.read_all()["Reminder Logs"]) if r["reminder_date"] >= since]
    by_day: dict = {}
    for r in rows:
        d = by_day.setdefault(r["reminder_date"], {"date": r["reminder_date"], "prepared": 0,
                                                   "sent": 0, "failed": 0, "total": 0})
        d[r["status"].lower()] = d.get(r["status"].lower(), 0) + 1
        d["total"] += 1
    return {"days": days, "total": len(rows),
            "by_type": dict(Counter(r["reminder_type"] for r in rows)),
            "by_day": sorted(by_day.values(), key=lambda d: d["date"], reverse=True)}
