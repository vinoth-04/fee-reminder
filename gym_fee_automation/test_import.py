"""End-to-end checks. Run from the project root:  python test_import.py
Uses a temporary data folder, so your real workbook is never touched."""
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ["GYM_DATA_DIR"] = tempfile.mkdtemp(prefix="gymtest_")

import pandas as pd                      # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config                  # noqa: E402
from app.main import app                 # noqa: E402
from app.services import due_date_service as dd  # noqa: E402
from app.services import excel_service as xs     # noqa: E402
from app.services import reminder_service as rs  # noqa: E402
from app.services.validators import format_inr, normalize_phone, parse_fee  # noqa: E402

client = TestClient(app)
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


print("Date maths")
check("31 Jan + 1 month = 28 Feb", dd.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28))
check("anchor keeps 31 for March", dd.add_months(date(2026, 1, 31), 2) == date(2026, 3, 31))
check("leap year Feb 29", dd.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29))
check("due from joining (Feb)", dd.calculate_due_date(date(2026, 1, 31), date(2026, 2, 10)) == date(2026, 2, 28))
check("due from joining (Mar)", dd.calculate_due_date(date(2026, 1, 31), date(2026, 3, 1)) == date(2026, 3, 31))
check("future joiner owes on joining date", dd.calculate_due_date(date(2026, 12, 5), date(2026, 11, 16)) == date(2026, 12, 5))
check("parse dd/mm/yyyy", dd.parse_date("03/04/2026") == date(2026, 4, 3))
check("parse '16 Nov 2026'", dd.parse_date("16 Nov 2026") == date(2026, 11, 16))
check("garbage date -> None", dd.parse_date("soon") is None)
check("clamped anchor -> joining day", dd.anchor_day(date(2026, 1, 31), date(2026, 2, 28)) == 31)
check("custom due day kept", dd.anchor_day(date(2026, 1, 5), date(2026, 2, 10)) == 10)

print("Validators")
check("phone 10 digits", normalize_phone("9876543210") == "919876543210")
check("phone +91 spaced", normalize_phone("+91 98765 43211") == "919876543211")
check("phone excel float", normalize_phone("9876543210.0") == "919876543210")
check("phone too short", normalize_phone("12345") is None)
check("fee with rupee/commas", parse_fee("₹1,200") == 1200)
check("fee zero rejected", parse_fee("0") is None)
check("inr grouping", format_inr(100000) == "₹1,00,000" and format_inr(1000) == "₹1,000")

print("Import preview")
src = Path(os.environ["GYM_DATA_DIR"]) / "members_in.xlsx"
pd.DataFrame([
    ["C-1", "Arun Kumar", "9876543210", "₹1,000", "31-01-2026", "", "Active"],
    ["C-2", "Bala", "+91 98765 43211", "1200", "15/03/2026", "20/11/2026", "Active"],
    ["C-3", "No Phone", "", "1000", "01-01-2026", "", ""],
    ["C-4", "Bad Fee", "9876543212", "abc", "01-01-2026", "", ""],
    ["C-5", "No Dates", "9876543213", "1000", "", "", ""],
    ["C-6", "Arun Kumar", "9876543210", "1000", "31-01-2026", "", ""],
    ["C-7", "Short Phone", "12345", "1000", "01-01-2026", "", ""],
    ["C-8", "Old Member", "9876543214", "900", "10-05-2025", "", "Left"],
], columns=["Customer ID", "Full Name", "Mobile", "Fee", "Join Date", "Payment Due", "Membership Status"]
).to_excel(src, index=False)
r = client.post("/api/import/preview", files={"file": ("members_in.xlsx", src.read_bytes())})
check("preview 200", r.status_code == 200, r.text)
pv = r.json()
m = pv["suggested_mapping"]
check("detects all 7 fields", all(m[k] for k in ["member_id", "name", "phone", "monthly_fee", "joining_date", "due_date", "status"]), m)
check("name -> Full Name", m["name"] == "Full Name")
check("due_date -> Payment Due", m["due_date"] == "Payment Due")
check("total rows 8", pv["total_rows"] == 8)
check("macro/other file rejected", client.post("/api/import/preview", files={"file": ("x.exe", b"MZ")}).status_code == 400)

print("Import confirm")
body = {"upload_id": pv["upload_id"], "mapping": m, "due_date_confirmed": False}
check("blocked without due-date confirmation", client.post("/api/import/confirm", json=body).status_code == 422)
bad = dict(body, mapping={**m, "phone": ""}, due_date_confirmed=True)
check("blocked when phone unmapped", client.post("/api/import/confirm", json=bad).status_code == 422)
body["due_date_confirmed"] = True
r = client.post("/api/import/confirm", json=body)
res = r.json()
check("confirm 200", r.status_code == 200, r.text)
check("3 imported (Arun, Bala, Old Member)", res["created"] == 3 and res["imported"] == 3, res)
check("5 rejected", res["rejected"] == 5, res)
reasons = " | ".join(x["reason"] for x in res["rejected_records"])
check("reasons reported", all(k in reasons for k in ["Phone is missing", "Invalid monthly fee", "No valid due date", "Duplicate of row", "Invalid phone"]), reasons)
check("backup created", bool(res["backup"]) and (config.BACKUP_DIR / res["backup"]).exists())
members = client.get("/api/members").json()
by = {x["name"]: x for x in members}
check("exactly 3 members from file", sorted(x["member_id"] for x in members) == ["C-1", "C-2", "C-8"])
check("supplied id preserved", by["Arun Kumar"]["member_id"] == "C-1")
check("phone stored with country code", by["Arun Kumar"]["phone"] == "919876543210")
check("fee stored as number", by["Arun Kumar"]["monthly_fee"] == 1000)
check("missing due computed from joining day 31", by["Arun Kumar"]["due_date"][-2:] in ("28", "29", "30", "31"))
check("supplied due kept", by["Bala"]["due_date"] == "2026-11-20")
check("status 'Left' -> Inactive", by["Old Member"]["status"] == "Inactive")
check("upload consumed", not list(config.UPLOAD_DIR.glob(pv["upload_id"] + ".*")))

print("Members API")
r = client.post("/api/members", json={"name": "Chitra", "phone": "9000000001", "monthly_fee": 1500, "joining_date": "2026-11-10"})
check("add member", r.status_code == 201, r.text)
check("add without any date refused", client.post("/api/members", json={"name": "X", "phone": "9000000002", "monthly_fee": 1}).status_code == 422)
check("duplicate refused", client.post("/api/members", json={"name": "Chitra", "phone": "9000000001", "monthly_fee": 1500, "joining_date": "2026-11-10"}).status_code == 409)
cid = r.json()["member_id"]
check("search by phone", len(client.get("/api/members", params={"q": "90000"}).json()) == 1)
check("edit member", client.put(f"/api/members/{cid}", json={"monthly_fee": 1600}).json()["monthly_fee"] == 1600)
check("deactivate keeps record", client.put(f"/api/members/{cid}", json={"status": "Inactive"}).json()["status"] == "Inactive")
client.put(f"/api/members/{cid}", json={"status": "Active"})

print("Payments")
r = client.post("/api/payments/generate", json={"month": "2026-11", "dry_run": True})
check("dry run creates nothing", r.json()["created"] >= 2 and client.get("/api/payments").json() == [])
g = client.post("/api/payments/generate", json={"month": "2026-11"}).json()
check("generate creates for active members only", g["created"] == 3 and g["inactive"] == 1, g)
g2 = client.post("/api/payments/generate", json={"month": "2026-11"}).json()
check("generate twice makes no duplicates", g2["created"] == 0 and g2["already_exists"] == 3, g2)
check("bad month rejected", client.post("/api/payments/generate", json={"month": "2026-13"}).status_code == 422)
pend = client.get("/api/payments/pending").json()
check("3 pending", len(pend) == 3)
pid = next(p["payment_id"] for p in pend if p["member_name"] == "Bala")
check("future paid date refused", client.put(f"/api/payments/{pid}/paid", json={"payment_date": "2099-01-01"}).status_code == 422)
check("bad mode refused", client.put(f"/api/payments/{pid}/paid", json={"payment_mode": "Bitcoin"}).status_code == 422)
r = client.put(f"/api/payments/{pid}/paid", json={"payment_date": date.today().isoformat(), "payment_mode": "upi"})
check("mark paid", r.status_code == 200 and r.json()["payment_status"] == "Paid" and r.json()["payment_mode"] == "UPI", r.text)
check("paid twice refused", client.put(f"/api/payments/{pid}/paid", json={}).status_code == 409)
check("member due date advanced to Dec", client.get("/api/members/C-2").json()["due_date"] == "2026-12-20")
s = client.get("/api/payments/summary").json()
check("collected = Bala's 1200", s["total_collected"] == 1200, s)
check("pending = Arun 1000 + Chitra 1600", s["pending_amount"] == 2600, s)

print("Re-import safety")
n_pay = len(client.get("/api/payments").json())
pv2 = client.post("/api/import/preview", files={"file": ("members_in.xlsx", src.read_bytes())}).json()
r2 = client.post("/api/import/confirm", json={"upload_id": pv2["upload_id"], "mapping": pv2["suggested_mapping"], "due_date_confirmed": True}).json()
check("re-import creates no new members", r2["created"] == 0, r2)
check("member count unchanged (4)", len(client.get("/api/members").json()) == 4)
check("payments preserved", len(client.get("/api/payments").json()) == n_pay)
check("paid status preserved", client.get("/api/payments/paid").json()[0]["payment_id"] == pid)
# re-import carries the OLD due date for Bala (20/11/2026) as a confirmed due date: that is the admin's call.

print("Reminders")
s = config.load_settings()
# Set Arun's due date to a known day by re-reading what the workbook computed
due_arun = date.fromisoformat(client.get("/api/members/C-1").json()["due_date"])
arun_pid = next(p["payment_id"] for p in client.get("/api/payments/pending").json() if p["member_id"] == "C-1")
ym = client.get("/api/payments/pending").json()[0]["payment_month"]
arun_due_nov = dd.due_date_for_month("2026-11", 31)           # 30 Nov 2026
before = arun_due_nov - dd.timedelta(days=3)
out = rs.prepare_reminders(today=before - dd.timedelta(days=1))
check("nothing prepared 4 days before", not any(p["member_id"] == "C-1" for p in out["prepared"]))
out = rs.prepare_reminders(today=before)
check("Before Due prepared 3 days before", any(p["member_id"] == "C-1" and p["reminder_type"] == "Before Due" for p in out["prepared"]), out)
out = rs.prepare_reminders(today=before)
check("no duplicate on same day re-run", not any(p["member_id"] == "C-1" for p in out["prepared"]))
out = rs.prepare_reminders(today=before + dd.timedelta(days=1))
check("no second Before Due next day", not any(p["member_id"] == "C-1" for p in out["prepared"]))
out = rs.prepare_reminders(today=arun_due_nov)
check("Due Date reminder on due day", any(p["member_id"] == "C-1" and p["reminder_type"] == "Due Date" for p in out["prepared"]))
out = rs.prepare_reminders(today=arun_due_nov + dd.timedelta(days=3))
check("Overdue after 3 days", any(p["member_id"] == "C-1" and p["reminder_type"] == "Overdue" for p in out["prepared"]))
out = rs.prepare_reminders(today=arun_due_nov + dd.timedelta(days=6))
check("no follow-up before 7 days", not any(p["member_id"] == "C-1" for p in out["prepared"]))
out = rs.prepare_reminders(today=arun_due_nov + dd.timedelta(days=10))
check("follow-up after 7 days", any(p["member_id"] == "C-1" and p["reminder_type"] == "Overdue" for p in out["prepared"]))
check("paid member (Bala) never reminded", not any(l["member_id"] == "C-2" for l in rs.get_logs()))
check("inactive member never reminded", not any(l["member_id"] == "C-8" for l in rs.get_logs()))

live = rs.list_reminders(today=arun_due_nov)
row = next(x for x in live["due_today"] if x["member_id"] == "C-1")
check("message has first name + amount + today", "Hello Arun," in row["message"] and "₹1,000" in row["message"] and "due today" in row["message"], row["message"])
check("wa.me link built", row["whatsapp_link"].startswith("https://wa.me/919876543210?text=Hello%20Arun"))
bd = rs.build_message("Before Due", "Arun Kumar", 1000, date(2026, 11, 6)) if hasattr(rs, "build_message") else ""
check("before-due message shows long date", "6 November 2026" in bd, bd)

lg = [l for l in rs.get_logs() if l["member_id"] == "C-1"][0]
check("mark sent", client.put(f"/api/reminders/{lg['reminder_id']}/status", json={"status": "Sent"}).json()["sent_at"] != "")
# paying stops further reminders
client.put(f"/api/payments/{arun_pid}/paid", json={"payment_date": date.today().isoformat(), "payment_mode": "Cash"})
out = rs.prepare_reminders(today=arun_due_nov + dd.timedelta(days=30))
check("no reminders after payment confirmed", not any(p["member_id"] == "C-1" and p["payment_month"] == "2026-11" for p in out["prepared"]))

print("Dashboard, reports, settings")
d = client.get("/api/dashboard/summary").json()
check("dashboard counts", d["total_members"] == 4 and d["inactive_members"] == 1, d)
check("monthly report", client.get("/api/reports/monthly").json()[0]["month"] == "2026-11")
check("pending report", client.get("/api/reports/pending").status_code == 200)
check("reminder report", client.get("/api/reports/reminders").json()["total"] >= 4)
check("settings update", client.put("/api/settings", json={"gym_name": "Iron House", "before_due_days": 5}).json()["before_due_days"] == 5)
check("bad setting refused", client.put("/api/settings", json={"scheduler_time": "25:99"}).status_code == 422)

print("Workbook safety")
wb = xs.read_all()
check("three sheets present", set(wb) == {"Members", "Payments", "Reminder Logs"})
check("formula-looking name stays text", client.post("/api/members", json={"name": "=1+1", "phone": "9000000009", "monthly_fee": 500, "due_date": "2026-12-01"}).status_code == 201
      and [m for m in xs.records(xs.read_all()["Members"]) if m["phone"] == "919000000009"][0]["name"] == "=1+1")
check("pages served", client.get("/").status_code == 200 and client.get("/import").status_code == 200)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
