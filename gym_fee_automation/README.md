# Gym Fee Reminder Automation

Manage gym members, track monthly fees and prepare personalised WhatsApp reminders.
FastAPI backend, plain HTML/CSS/JS dashboard, one Excel workbook as the database. Free to run, no paid APIs.

## Run it (Windows PowerShell, Python 3.11)

```powershell
cd gym_fee_automation
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python test_import.py                        # optional: 85 checks, uses a temp folder
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If PowerShell blocks the activate script, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Open:
- Dashboard: http://127.0.0.1:8000
- Excel import: http://127.0.0.1:8000/import
- API docs (Swagger): http://127.0.0.1:8000/docs

`data/gym_members.xlsx` is created on first start. Close it in Excel before using the app, because Excel locks the file. The app tells you if it is locked.

## Daily use

1. **Import** members from any Excel/CSV file. Columns are auto-detected. You confirm or fix the mapping, tick the due-date confirmation, and import.
2. **Payments > Generate billing** once a month. This creates a Pending payment per active member. Nothing counts as pending until you generate it.
3. **Reminders** shows Overdue, Due today and Due soon. Click *Open WhatsApp*, check the message, press Send in WhatsApp, then *Mark sent*.
   - **Optional auto-send:** on the Reminders page click *Connect WhatsApp* and scan the QR (WhatsApp > Linked devices). Then use *Send now* per row or *Auto-send all*. Needs `pip install playwright` and Google Chrome (or `playwright install chromium`). It is unofficial and can get a number banned, so there is a daily limit (default 40, `WHATSAPP_DAILY_CAP`) and a 5-15 s pause between messages. Click-to-chat always works without it.
4. When a member pays, **Payments > Mark paid**. Reminders for that month stop and the member's next due date moves forward a month.

The scheduler runs daily at the time set in Settings (default 09:00) and once at startup, so a PC that was off still catches up. It only prepares reminders; it never sends.

## Reminder schedule (editable in Settings)

| Reminder | When |
|---|---|
| Before Due | once, within 3 days before the due date |
| Due Date | on the due date |
| Overdue | 3 days after the due date |
| Follow-up | every 7 days while still unpaid |

A reminder is skipped if the member is inactive, the payment is paid, the same reminder was already prepared, or the phone number is invalid.

## Import rules

- Required: Name, Phone, Monthly fee, and either Due date or Joining date.
- Missing due date is calculated from the joining day (31 Jan becomes 28 Feb, then 31 Mar). A row with no usable date is rejected, never guessed.
- A Due date column is only accepted after you confirm it is a payment due date, not a membership expiry.
- Indian numbers become `91XXXXXXXXXX`. Invalid phones and fees are rejected with the reason.
- Re-importing the same file creates no duplicates and keeps member IDs. Existing members are updated. Payments and reminder logs are never touched.
- A backup goes to `data/backups/` before every import, billing run and mark-paid. The newest 30 are kept.
- Only `.xlsx` and `.csv`, max 10 MB. Formulas and macros in uploads are never executed.

## Layout

```
app/main.py                      app, error handling, pages
app/routes/                      member, payment, reminder, upload, dashboard (reports + settings)
app/services/excel_service.py    workbook read/write, locking, atomic save, backups
app/services/excel_upload_service.py, column_detection_service.py, due_date_service.py
app/services/member_service.py, payment_service.py, reminder_service.py, whatsapp_service.py (click-to-chat links), invoice_service.py, validators.py
app/scheduler/jobs.py            APScheduler daily job
templates/ static/               dashboard and import pages
test_import.py                   end-to-end tests
```

## Before putting it online

This version has no login and is meant for localhost only. Before cloud hosting: add admin authentication, serve over HTTPS, and move from Excel to SQLite or PostgreSQL (the service layer is the only code that touches the workbook). Keep secrets in environment variables, never in code.
