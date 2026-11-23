"""Flexible Excel/CSV import: read, detect columns, validate, normalise, import safely."""
import io
import re
import time
import uuid
from datetime import date
from pathlib import Path

import pandas as pd

from app import config
from app.errors import AppError
from app.services import excel_service as xs
from app.services.column_detection_service import FIELDS, REQUIRED, detect_columns
from app.services.due_date_service import calculate_due_date, parse_date
from app.services.validators import (clean_id, clean_text, normalize_phone, normalize_status,
                                     parse_fee)

_TOKEN = re.compile(r"^[0-9a-f]{32}$")


# ---------- reading ----------
def _grid(filename: str, content: bytes) -> list[list[str]]:
    ext = Path(filename or "").suffix.lower()
    if ext not in {".xlsx", ".csv"}:
        raise AppError(400, "Unsupported file type. Upload an .xlsx or .csv file.")
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise AppError(413, f"File is larger than {config.MAX_UPLOAD_MB} MB.")
    try:
        if ext == ".xlsx":
            if not content.startswith(b"PK"):
                raise AppError(400, "This does not look like a valid .xlsx file.")
            raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str,
                                keep_default_na=False, engine="openpyxl")   # formulas are never run
        else:
            text = None
            for enc in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    text = content.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            raw = pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False,
                              sep=None, engine="python", on_bad_lines="skip")
    except AppError:
        raise
    except Exception as e:
        raise AppError(400, f"Could not read the file: {e}")
    return raw.astype(object).fillna("").map(lambda v: str(v).strip()).values.tolist()


def parse_sheet(filename: str, content: bytes) -> dict:
    grid = _grid(filename, content)
    counts = [sum(1 for c in r if c) for r in grid[:10]]
    if not counts or max(counts) < 2:
        raise AppError(400, "Could not find a header row with column names.")
    top = max(counts)
    h = next(i for i, n in enumerate(counts) if n >= max(2, 0.6 * top))
    width = max(len(r) for r in grid)
    header = list(grid[h]) + [""] * (width - len(grid[h]))
    data = [list(r) + [""] * (width - len(r)) for r in grid[h + 1:]]
    keep = [j for j in range(width) if header[j] or any(r[j] for r in data)]
    names, seen = [], {}
    for j in keep:
        name = header[j] or f"Column {j + 1}"
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    rows, numbers = [], []
    for k, r in enumerate(data):
        if any(r):
            rows.append(dict(zip(names, [r[j] for j in keep])))
            numbers.append(h + k + 2)          # 1-based spreadsheet row number
    if not rows:
        raise AppError(400, "The file has a header but no member rows.")
    if len(rows) > config.MAX_UPLOAD_ROWS:
        raise AppError(413, f"Too many rows. The limit is {config.MAX_UPLOAD_ROWS}.")
    return {"columns": names, "rows": rows, "row_numbers": numbers}


# ---------- upload storage ----------
def _cleanup():
    if config.UPLOAD_DIR.exists():
        for p in config.UPLOAD_DIR.iterdir():
            if time.time() - p.stat().st_mtime > 86400:
                p.unlink(missing_ok=True)


def preview(filename: str, content: bytes) -> dict:
    parsed = parse_sheet(filename, content)
    cc = config.load_settings()["default_country_code"]
    detected = detect_columns(parsed["columns"], parsed["rows"], cc)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup()
    token = uuid.uuid4().hex
    (config.UPLOAD_DIR / f"{token}{Path(filename).suffix.lower()}").write_bytes(content)
    return {"upload_id": token, "filename": filename, "columns": parsed["columns"],
            "preview_rows": parsed["rows"][:10], "total_rows": len(parsed["rows"]),
            "suggested_mapping": detected["mapping"], "confidence": detected["confidence"]}


def _load_upload(token: str):
    if not token or not _TOKEN.match(token):
        raise AppError(400, "Invalid upload reference.")
    matches = list(config.UPLOAD_DIR.glob(f"{token}.*")) if config.UPLOAD_DIR.exists() else []
    if not matches:
        raise AppError(404, "This upload has expired. Upload the file again.")
    return matches[0], parse_sheet(matches[0].name, matches[0].read_bytes())


# ---------- import ----------
def confirm_import(token: str, mapping: dict, due_date_confirmed: bool = False,
                   today: date | None = None) -> dict:
    today = today or date.today()
    mapping = {f: c for f, c in (mapping or {}).items() if f in FIELDS and c}
    path, parsed = _load_upload(token)
    unknown = [c for c in mapping.values() if c not in parsed["columns"]]
    if unknown:
        raise AppError(422, f"Column '{unknown[0]}' was not found in the file.")
    missing = [f for f in REQUIRED if f not in mapping]
    if missing:
        raise AppError(422, "Map these required fields first: " + ", ".join(missing) + ".")
    if "due_date" not in mapping and "joining_date" not in mapping:
        raise AppError(422, "Map a Due date or a Joining date column.")
    if len(set(mapping.values())) != len(mapping):
        raise AppError(422, "The same column is mapped to more than one field.")
    if "due_date" in mapping and not due_date_confirmed:
        raise AppError(422, "Confirm that the Due date column holds payment due dates, "
                            "not membership expiry dates.")

    cc = config.load_settings()["default_country_code"]
    rows, numbers = parsed["rows"], parsed["row_numbers"]
    file_ids = {clean_id(r.get(mapping["member_id"], "")) for r in rows} if "member_id" in mapping else set()
    file_ids.discard("")

    created = updated = unchanged = 0
    rejected: list[dict] = []
    first_seen: dict = {}

    with xs.transaction(backup_reason="pre_import") as wb:
        members = xs.records(wb["Members"])
        by_id = {m["member_id"]: m for m in members}
        by_key = {(m["name"].lower(), m["phone"]): m for m in members}
        reserved = set(by_id) | file_ids
        gen_df = wb["Members"]

        for row, rowno in zip(rows, numbers):
            def get(field):
                return row.get(mapping[field], "").strip() if field in mapping else ""

            reasons = []
            name = clean_text(get("name"))
            if not name:
                reasons.append("Name is missing")
            elif len(name) > 80:
                reasons.append("Name is longer than 80 characters")
            phone = normalize_phone(get("phone"), cc)
            if not phone:
                reasons.append(f"Invalid phone number '{get('phone')}'" if get("phone") else "Phone is missing")
            fee = parse_fee(get("monthly_fee"))
            if fee is None:
                reasons.append(f"Invalid monthly fee '{get('monthly_fee')}'" if get("monthly_fee") else "Monthly fee is missing")
            joining, due = parse_date(get("joining_date")), parse_date(get("due_date"))
            if not joining and not due:
                bad = [f"{l} '{get(k)}'" for k, l in (("joining_date", "joining date"), ("due_date", "due date")) if get(k)]
                reasons.append("No valid due date or joining date" + (f" (unreadable: {', '.join(bad)})" if bad else ""))
            status = normalize_status(get("status")) if "status" in mapping else None
            if "status" in mapping and status is None:
                reasons.append(f"Unrecognised status '{get('status')}'")
            member_id = clean_id(get("member_id"))

            if not reasons:
                keys = ([f"id:{member_id}"] if member_id else []) + [f"np:{name.lower()}|{phone}"]
                dup = next((k for k in keys if k in first_seen), None)
                if dup:
                    reasons.append(f"Duplicate of row {first_seen[dup]} in this file")
                else:
                    for k in keys:
                        first_seen[k] = rowno
            if reasons:
                rejected.append({"row": rowno, "name": name, "reason": "; ".join(reasons)})
                continue

            match = by_id.get(member_id) if member_id else None
            if match is None:
                other = by_key.get((name.lower(), phone))
                if other is not None and member_id and other["member_id"] != member_id:
                    rejected.append({"row": rowno, "name": name, "reason":
                                     f"Same name and phone already exist as member {other['member_id']}"})
                    continue
                match = other
            if match is None:
                mid = member_id or xs.next_id(gen_df, "member_id", "M", reserved=reserved)
                reserved.add(mid)
                new = {"member_id": mid, "name": name, "phone": phone, "monthly_fee": str(fee),
                       "joining_date": joining.isoformat() if joining else "",
                       "due_date": (due or calculate_due_date(joining, today)).isoformat(),
                       "status": status or "Active"}
                members.append(new)
                by_id[mid], by_key[(name.lower(), phone)] = new, new
                created += 1
            else:
                new = {**match, "name": name, "phone": phone, "monthly_fee": str(fee)}
                if joining:
                    new["joining_date"] = joining.isoformat()
                if due:                       # only an admin-confirmed due date overrides
                    new["due_date"] = due.isoformat()
                if status:
                    new["status"] = status
                if new == match:
                    unchanged += 1
                else:
                    match.update(new)
                    updated += 1

        wb["Members"] = pd.DataFrame(members, columns=xs.MEMBER_COLS, dtype=object)

    # Sync all members to SQLite so billing/reminders work immediately
    from app import db as _db
    _db.ensure_db()
    with _db.transaction() as conn:
        for m in members:
            conn.execute(
                """INSERT OR REPLACE INTO members
                   (member_id, name, phone, monthly_fee, joining_date, due_date, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (m["member_id"], m["name"], m["phone"], str(m.get("monthly_fee", "")),
                 m.get("joining_date", ""), m.get("due_date", ""), m.get("status", "Active")),
            )

    path.unlink(missing_ok=True)
    return {"imported": created + updated + unchanged, "created": created, "updated": updated,
            "unchanged": unchanged, "rejected": len(rejected), "rejected_records": rejected,
            "backup": wb.backup_file}
