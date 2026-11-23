# GymFlow | Gym Fee & WhatsApp Reminder Automation

> Professional, local-first gym management platform. Track monthly member fees, automate recurring billing cycles, auto-detect spreadsheet columns, and prepare 1-click personalized WhatsApp reminders with zero API costs.

---

## ⚡ Quickstart (Windows PowerShell)

```powershell
# Navigate to this directory
cd gym_fee_automation

# Setup environment & dependencies
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run the test suite (85 checks)
python test_import.py

# Start the web server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open:
- **Dashboard:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Excel Import:** [http://127.0.0.1:8000/import](http://127.0.0.1:8000/import)
- **API Documentation:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 🚀 Key Features

- **Modern SaaS Dashboard:** Clean, responsive design with dark/light mode toggle, KPI metric cards, collection rate tracker, and quick action shortcuts.
- **Intelligent Excel / CSV Import:** Heuristic column detection automatically maps fields. Deduplicates on re-import without touching historical payment logs.
- **Defensive Excel Database:** Full atomic writing via `.tmp.xlsx`, automatic Excel lock detection, formula injection prevention, and rolling backup retention (newest 30).
- **One-Click WhatsApp Reminders:** Creates custom `wa.me` links with member names, due dates, and amounts in ₹ INR. Zero setup, zero third-party messaging costs.
- **Flexible Reminder Engine:** Configurable timing for Before Due, Due Date, Overdue, and recurring follow-up reminders.
- **Export Capabilities:** One-click CSV export for members and payments directly from the dashboard.

---

## 📂 Architecture & Directory Layout

```
app/
├── config.py                     Settings management and storage paths
├── errors.py                     Custom application error definitions
├── main.py                       FastAPI app initialization, lifespan, routes
├── routes/
│   ├── dashboard_routes.py       Summary metrics, reports, CSV exports & settings
│   ├── member_routes.py          Member CRUD operations
│   ├── payment_routes.py         Recurring billing generation & mark-as-paid
│   ├── reminder_routes.py        Reminder generation & dispatch tracking
│   └── upload_routes.py          Excel preview and import confirmation
├── scheduler/
│   └── jobs.py                   APScheduler daily reminder preparation job
└── services/
    ├── column_detection_service.py Heuristic header detection
    ├── due_date_service.py       Date arithmetic & anchor calculations
    ├── excel_service.py          Atomic workbook read/writes with RLock
    ├── excel_upload_service.py   File processing & validation
    ├── member_service.py         Member business logic
    ├── payment_service.py        Billing cycle logic
    ├── reminder_service.py       Reminder schedule state engine
    ├── validators.py             Phone normalization and fee parsing
    └── whatsapp_service.py       Personalized WhatsApp message formatting

static/
├── css/
│   ├── app.css                   Modern design system with dark/light themes
│   └── import.css                Importer wizard styling
└── js/
    ├── app.js                    Interactive dashboard client (vanilla JS)
    └── import.js                 Interactive spreadsheet import client

templates/
├── index.html                    Main application dashboard
└── import.html                   Member import wizard

test_import.py                    Exhaustive end-to-end test suite
```

---

## 🧪 Testing

Run all 85 unit and integration tests:
```powershell
python test_import.py
```
