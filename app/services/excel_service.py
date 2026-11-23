"""Master workbook storage: three sheets, safe writes, backups and locking."""
import math
import os
import re
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime

import pandas as pd
from openpyxl.utils import get_column_letter

from app import config
from app.errors import AppError

MEMBER_COLS = ["member_id", "name", "phone", "monthly_fee", "joining_date", "due_date", "status"]
PAYMENT_COLS = ["payment_id", "member_id", "payment_month", "amount", "payment_date",
                "payment_status", "payment_mode"]
REMINDER_COLS = ["reminder_id", "member_id", "payment_month", "reminder_date",
                 "reminder_type", "message", "status", "sent_at"]
SHEETS = {"Members": MEMBER_COLS, "Payments": PAYMENT_COLS, "Reminder Logs": REMINDER_COLS}
_NUMERIC = {"monthly_fee", "amount"}

LOCK = threading.RLock()
_LOCKED_MSG = ("The workbook is open in another program (probably Excel). "
               "Close it and try again.")


class Workbook(dict):
    """The three sheets as DataFrames, keyed by sheet name."""
    backup_file = None


def _num(value):
    s = str(value).strip()
    if s == "":
        return ""
    try:
        f = float(s)
    except ValueError:
        return s
    if not math.isfinite(f):
        return s
    return int(f) if f == int(f) else round(f, 2)


def _write(dfs, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.xlsx")
    with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
        for sheet, cols in SHEETS.items():
            out = dfs[sheet][cols].copy()
            for c in cols:
                if c in _NUMERIC:
                    out[c] = out[c].map(_num)
            out.to_excel(xw, sheet_name=sheet, index=False)
            ws = xw.sheets[sheet]
            ws.freeze_panes = "A2"
            for i, c in enumerate(cols, 1):
                ws.column_dimensions[get_column_letter(i)].width = 60 if c == "message" else max(14, len(c) + 4)
            for row in ws.iter_rows():          # text that starts with "=" must stay text
                for cell in row:
                    if cell.data_type == "f":
                        cell.data_type = "s"
    try:
        os.replace(tmp, path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise AppError(423, _LOCKED_MSG)


def ensure_workbook():
    with LOCK:
        if not config.WORKBOOK_PATH.exists():
            _write({s: pd.DataFrame(columns=c, dtype=object) for s, c in SHEETS.items()},
                   config.WORKBOOK_PATH)


def load_all() -> Workbook:
    with LOCK:
        ensure_workbook()
        try:
            raw = pd.read_excel(config.WORKBOOK_PATH, sheet_name=None, dtype=str,
                                keep_default_na=False, engine="openpyxl")
        except PermissionError:
            raise AppError(423, _LOCKED_MSG)
        except Exception as e:
            raise AppError(500, f"Could not read the workbook: {e}")
        wb = Workbook()
        for sheet, cols in SHEETS.items():
            df = raw.get(sheet)
            if df is None:
                df = pd.DataFrame(columns=cols)
            for c in cols:
                if c not in df.columns:
                    df[c] = ""
            df = df[cols].astype(object).fillna("").map(lambda v: str(v).strip())
            wb[sheet] = df.reset_index(drop=True)
        return wb


def backup(reason: str = "manual"):
    """Copy the workbook into data/backups and keep only the newest backups."""
    with LOCK:
        if not config.WORKBOOK_PATH.exists():
            return None
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reason = re.sub(r"[^a-z0-9_]", "", reason.lower())
        target = config.BACKUP_DIR / f"gym_members_{stamp}_{reason}.xlsx"
        n = 1
        while target.exists():
            target = config.BACKUP_DIR / f"gym_members_{stamp}_{reason}_{n}.xlsx"
            n += 1
        try:
            shutil.copy2(config.WORKBOOK_PATH, target)
        except PermissionError:
            raise AppError(423, _LOCKED_MSG)
        old = sorted(config.BACKUP_DIR.glob("gym_members_*.xlsx"), key=lambda p: p.stat().st_mtime)
        for p in old[:-config.KEEP_BACKUPS]:
            p.unlink(missing_ok=True)
        return target.name


@contextmanager
def transaction(backup_reason: str | None = None):
    """Load, let the caller change the sheets, then save only if something changed.

    If the body raises, nothing is written. If backup_reason is given, a backup
    is taken right before an actual write.
    """
    with LOCK:
        wb = load_all()
        before = {k: v.copy() for k, v in wb.items()}
        yield wb
        changed = any(not wb[k].reset_index(drop=True).equals(before[k]) for k in SHEETS)
        if changed:
            if backup_reason:
                wb.backup_file = backup(backup_reason)
            _write(wb, config.WORKBOOK_PATH)


def read_all() -> Workbook:
    return load_all()


def records(df) -> list[dict]:
    return df.to_dict("records")


def append_row(df, row: dict):
    df.loc[len(df)] = [str(row.get(c, "")) for c in df.columns]
    return df


def next_id(df, col: str, prefix: str, width: int = 4, reserved=()) -> str:
    nums = []
    for v in list(df[col]) + list(reserved):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", str(v))
        if m:
            nums.append(int(m.group(1)))
    return f"{prefix}{(max(nums) + 1 if nums else 1):0{width}d}"
