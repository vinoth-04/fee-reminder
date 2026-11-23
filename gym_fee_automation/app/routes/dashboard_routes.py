from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from app import config, db as _db
from app.errors import AppError
from app.scheduler import jobs
from app.services import excel_service as xs
from app.services import payment_service, reminder_service
from app.services.validators import parse_fee

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard/summary")
def dashboard_summary():
    with _db.read() as conn:
        members = _db.rows(conn, "SELECT member_id, status FROM members")
        month_prefix = date.today().strftime("%Y-%m")
        this_month = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments "
            "WHERE payment_status='Paid' AND payment_date LIKE ?",
            (month_prefix + "%",)
        ).fetchone()[0] or 0
    pay = payment_service.summary()
    live = reminder_service.list_reminders()
    return {
        "total_members": len(members),
        "active_members": sum(1 for m in members if m["status"] == "Active"),
        "inactive_members": sum(1 for m in members if m["status"] != "Active"),
        "total_collected": pay["total_collected"],
        "collected_this_month": this_month,
        "pending_amount": pay["pending_amount"],
        "due_today_count": len(live["due_today"]),
        "due_today_amount": sum(r["amount"] for r in live["due_today"]),
        "overdue_count": len(live["overdue"]),
        "overdue_amount": sum(r["amount"] for r in live["overdue"]),
    }


@router.get("/api/reports/monthly")
def report_monthly():
    return payment_service.summary()["months"]


@router.get("/api/reports/pending")
def report_pending():
    rows = payment_service.list_payments("Pending")
    today = date.today().isoformat()
    with _db.read() as conn:
        members = {m["member_id"]: m for m in _db.rows(conn, "SELECT member_id, phone FROM members")}
    for r in rows:
        r["phone"] = members.get(r["member_id"], {}).get("phone", "")
    return {"count": len(rows), "total": sum(r["amount"] for r in rows), "as_of": today, "rows": rows}


@router.get("/api/reports/reminders")
def report_reminders(days: int = 30):
    return reminder_service.activity_report(days)


class SettingsIn(BaseModel):
    gym_name: str | None = None
    default_country_code: str | None = None
    before_due_days: int | None = None
    overdue_days: int | None = None
    followup_days: int | None = None
    scheduler_time: str | None = None
    default_monthly_fee: float | None = None
    monthly_fee_options: str | None = None


@router.get("/api/settings")
def get_settings():
    return config.load_settings()


@router.put("/api/settings")
def put_settings(body: SettingsIn):
    settings = config.update_settings(body.model_dump(exclude_unset=True))
    jobs.reschedule()
    return settings
