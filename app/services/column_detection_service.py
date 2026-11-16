"""Suggest which spreadsheet column matches each internal field."""
import re
from difflib import SequenceMatcher

from app.services.validators import normalize_phone

FIELDS = ["member_id", "name", "phone", "monthly_fee", "joining_date", "due_date", "status"]
REQUIRED = ["name", "phone", "monthly_fee"]

_SYNONYMS = {
    "member_id": ["id", "memberid", "memberno", "membernumber", "customerid", "clientid",
                  "custid", "regno", "registrationno", "registrationnumber"],
    "name": ["name", "fullname", "customername", "membername", "clientname", "member", "customer"],
    "phone": ["phone", "phoneno", "phonenumber", "mobile", "mobileno", "mobilenumber", "contact",
              "contactno", "contactnumber", "whatsapp", "whatsappno", "whatsappnumber", "cell"],
    "monthly_fee": ["fee", "fees", "amount", "monthlyfee", "monthlyfees", "monthlyamount",
                    "membershipfee", "charges", "monthlycharges", "subscription"],
    "joining_date": ["joindate", "joiningdate", "dateofjoining", "startdate", "joinedon", "doj",
                     "admissiondate", "registrationdate", "membershipstart"],
    "due_date": ["duedate", "paymentdue", "nextdue", "nextduedate", "paymentduedate", "feedue",
                 "feeduedate", "nextpaymentdate"],
    "status": ["status", "membershipstatus", "memberstatus", "activestatus"],
}
_BLOCK = {
    "monthly_fee": ["balance", "pending", "paid", "total", "due"],
    "status": ["payment", "fee"],
    "name": ["father", "emergency", "trainer", "file"],
    "phone": ["emergency", "alternate", "alt"],
    "joining_date": ["end", "expiry", "expire", "due"],
    "member_id": ["aadhaar", "aadhar", "pan"],
}
THRESHOLD = 0.7


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _score(field: str, header: str) -> float:
    h = _norm(header)
    if not h:
        return 0.0
    syns = _SYNONYMS[field]
    if h in syns:
        return 1.0
    best = 0.0
    for s in syns:
        if len(s) >= 4 and (s in h or (len(h) >= 4 and h in s)):
            best = max(best, 0.75)
        best = max(best, SequenceMatcher(None, h, s).ratio() * 0.9 if len(h) > 3 else 0)
    if best < 0.7:
        return 0.0
    if any(b in h for b in _BLOCK.get(field, [])):
        best *= 0.5
    return round(best, 2)


def detect_columns(columns: list[str], rows: list[dict], default_cc: str = "91") -> dict:
    """Return {'mapping': {field: column or ''}, 'confidence': {field: 0..1}}."""
    candidates = sorted(
        ((_score(f, c), f, c) for f in FIELDS for c in columns), key=lambda t: -t[0])
    mapping = {f: "" for f in FIELDS}
    confidence = {f: 0.0 for f in FIELDS}
    used = set()
    for score, field, col in candidates:
        if score < THRESHOLD or mapping[field] or col in used:
            continue
        mapping[field], confidence[field] = col, score
        used.add(col)
    if not mapping["phone"]:  # fall back to looking at the values
        for col in columns:
            if col in used:
                continue
            values = [r.get(col, "") for r in rows[:30] if r.get(col, "")]
            if len(values) >= 3 and sum(1 for v in values if normalize_phone(v, default_cc)) / len(values) >= 0.7:
                mapping["phone"], confidence["phone"] = col, 0.6
                break
    return {"mapping": mapping, "confidence": confidence}
