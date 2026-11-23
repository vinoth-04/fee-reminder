"""Paths and admin-editable settings. No secrets live here."""
import json
import os
import re
from pathlib import Path

from app.errors import AppError

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("GYM_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "gym.db"
WORKBOOK_PATH = DATA_DIR / "gym_members.xlsx"   # legacy Excel file: migrated once, then only for export
BACKUP_DIR = DATA_DIR / "backups"
UPLOAD_DIR = DATA_DIR / "uploads"
SETTINGS_PATH = DATA_DIR / "settings.json"

MAX_UPLOAD_MB = 10
MAX_UPLOAD_ROWS = 20000
KEEP_BACKUPS = 30

DEFAULT_SETTINGS = {
    "gym_name": "",
    "default_country_code": "91",
    "before_due_days": 3,    # first reminder, days before the due date
    "overdue_days": 3,       # overdue reminder, days after the due date
    "followup_days": 7,      # repeat every N days while unpaid
    "scheduler_time": "09:00",
    "default_monthly_fee": 1500,
    "monthly_fee_options": "500, 800, 1000, 1200, 1500, 2000, 2500, 3000, 5000",
}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_PATH.exists():
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return settings


def update_settings(patch: dict) -> dict:
    settings = load_settings()
    errors = []
    for key, value in patch.items():
        if key not in DEFAULT_SETTINGS or value is None:
            continue
        if key == "gym_name":
            value = str(value).strip()
            if len(value) > 60:
                errors.append("Gym name must be 60 characters or fewer.")
        elif key == "default_country_code":
            value = str(value).strip().lstrip("+")
            if not re.fullmatch(r"\d{1,3}", value):
                errors.append("Country code must be 1 to 3 digits, for example 91.")
        elif key == "scheduler_time":
            value = str(value).strip()
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
                errors.append("Scheduler time must look like 09:00.")
        elif key == "default_monthly_fee":
            try:
                fee_val = float(value)
                if fee_val <= 0:
                    errors.append("Default monthly fee must be greater than 0.")
                else:
                    settings[key] = int(fee_val) if fee_val.is_integer() else round(fee_val, 2)
            except (TypeError, ValueError):
                errors.append("Default monthly fee must be a number greater than 0.")
        elif key == "monthly_fee_options":
            raw_opts = str(value or "").strip()
            parts = [p.strip() for p in raw_opts.split(",") if p.strip()]
            valid_opts = []
            for p in parts:
                try:
                    p_val = float(p)
                    if p_val > 0:
                        valid_opts.append(str(int(p_val) if p_val.is_integer() else round(p_val, 2)))
                except ValueError:
                    continue
            if not valid_opts:
                errors.append("Monthly fee options must contain at least one valid number.")
            else:
                settings[key] = ", ".join(valid_opts)
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                errors.append(f"{key} must be a whole number.")
                continue
            low = 0 if key == "before_due_days" else 1
            if not low <= value <= 60:
                errors.append(f"{key} must be between {low} and 60.")
        settings[key] = value
    if errors:
        raise AppError(422, " ".join(errors))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)
    return settings