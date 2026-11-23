import csv
import io
from datetime import date

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app import config
from app.scheduler import jobs
from app.services import excel_service as xs
from app.services import payment_service, reminder_service
from app.services.validators import parse_fee

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard/summary")
def dashboard_summary():
    wb = xs.read_all()
    members = xs.records(wb["Members"])
    pay = payment_service.summary()
    live = reminder_service.list_reminders()
    month_prefix = date.today().strftime("%Y-%m")
    this_month = sum(parse_fee(p["amount"]) or 0 for p in xs.records(wb["Payments"])
                     if p["payment_status"] == "Paid" and p["payment_date"].startswith(month_prefix))
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
    members = {m["member_id"]: m for m in xs.records(xs.read_all()["Members"])}
    for r in rows:
        r["phone"] = members.get(r["member_id"], {}).get("phone", "")
    return {"count": len(rows), "total": sum(r["amount"] for r in rows), "as_of": today, "rows": rows}


@router.get("/api/reports/reminders")
def report_reminders(days: int = 30):
    return reminder_service.activity_report(days)


@router.get("/api/reports/export/members")
def export_members_csv():
    wb = xs.read_all()
    records = xs.records(wb["Members"])
    output = io.StringIO()
    if records:
        writer = csv.DictWriter(output, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gym_members_{date.today().isoformat()}.csv"}
    )


@router.get("/api/reports/export/payments")
def export_payments_csv(status: str = "", month: str = ""):
    rows = payment_service.list_payments(status, month)
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gym_payments_{date.today().isoformat()}.csv"}
    )


class SettingsIn(BaseModel):
    gym_name: str | None = None
    default_country_code: str | None = None
    before_due_days: int | None = None
    overdue_days: int | None = None
    followup_days: int | None = None
    scheduler_time: str | None = None


@router.get("/api/settings")
def get_settings():
    return config.load_settings()


@router.put("/api/settings")
def put_settings(body: SettingsIn):
    settings = config.update_settings(body.model_dump(exclude_unset=True))
    jobs.reschedule()
    return settings
