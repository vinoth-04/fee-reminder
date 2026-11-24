"""Member replies inbox. Best-effort: reads incoming messages from the linked WhatsApp Web, only for
members who got a reminder recently, only when the admin clicks 'Check for replies'."""
import hashlib
import os
import re
import threading
from datetime import date, datetime, timedelta

from app import db
from app.errors import AppError
from app.services import excel_service as xs
from app.services import whatsapp_session

LOOKBACK_DAYS = 14
MAX_CHATS = int(os.environ.get("WHATSAPP_INBOX_MAX_CHATS", "25"))
PER_CHAT = 5

_FORMATS = ("%I:%M %p, %d/%m/%Y", "%H:%M, %d/%m/%Y", "%I:%M %p, %d.%m.%Y", "%H:%M, %d.%m.%Y",
            "%I:%M %p, %m/%d/%Y", "%H:%M, %m/%d/%Y")
_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "new": 0, "skipped": 0, "error": "", "finished_at": ""}


def _stamp(meta: str) -> str:
    """'[10:30 am, 24/11/2026] Arun: ' -> '2026-11-24 10:30' (or the raw text if it can't be parsed)."""
    m = re.search(r"\[(.+?)\]", meta or "")
    raw = (m.group(1) if m else "").replace("\u202f", " ").strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return raw


def _targets() -> list[dict]:
    """Active members with a Sent reminder in the last 14 days, most recent first."""
    since = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    last: dict[str, str] = {}
    for r in xs.records(xs.read_all()["Reminder Logs"]):
        if r["status"] == "Sent" and r["reminder_date"] >= since:
            last[r["member_id"]] = max(last.get(r["member_id"], ""), r["sent_at"] or r["reminder_date"])
    with db.read() as conn:
        members = {m["member_id"]: m for m in db.rows(
            conn, "SELECT member_id, name, phone FROM members WHERE status = 'Active'")}
    ordered = sorted((mid for mid in last if mid in members), key=lambda mid: last[mid], reverse=True)
    return [members[mid] for mid in ordered[:MAX_CHATS]]


def _run(targets: list[dict]) -> None:
    error = ""
    try:
        for t in targets:
            ok, err, items = whatsapp_session.read_replies_for(t["phone"], PER_CHAT)
            if not ok:
                if "no longer linked" in err or "not connected" in err or "not running" in err:
                    error = err
                    break
                with _lock:
                    _state["skipped"] += 1
                    _state["done"] += 1
                continue
            fresh = 0
            with db.transaction() as conn:
                for it in items:
                    body = (it.get("text") or "").strip()
                    if not body:
                        continue
                    stamp = _stamp(it.get("meta", ""))
                    mid = hashlib.sha1(f"{t['member_id']}|{stamp}|{body}".encode("utf-8")).hexdigest()[:16]
                    fresh += conn.execute(
                        "INSERT OR IGNORE INTO inbox_messages (message_id, member_id, received_at, body) "
                        "VALUES (?, ?, ?, ?)", (mid, t["member_id"], stamp, body[:2000])).rowcount
            with _lock:
                _state["new"] += fresh
                _state["done"] += 1
    except Exception as e:                                   # never leave the status stuck on 'running'
        error = str(e)
    finally:
        with _lock:
            _state.update(running=False, error=error, finished_at=datetime.now().strftime("%H:%M:%S"))


def start_sync() -> dict:
    if not whatsapp_session.is_connected():
        raise AppError(409, "WhatsApp is not connected. Connect it on the Reminders page first.")
    with _lock:
        if _state["running"]:
            return dict(_state)
        targets = _targets()
        _state.update(running=bool(targets), done=0, total=len(targets), new=0, skipped=0, error="",
                      finished_at="" if targets else datetime.now().strftime("%H:%M:%S"))
        if not targets:
            return dict(_state)
    threading.Thread(target=_run, args=(targets,), daemon=True, name="inbox-sync").start()
    return sync_status()


def sync_status() -> dict:
    with _lock:
        return dict(_state)


def list_inbox() -> list[dict]:
    with db.read() as conn:
        rows = db.rows(conn, """
            SELECT i.message_id, i.member_id, i.received_at, i.body, i.seen, i.fetched_at,
                   m.name, m.phone
            FROM inbox_messages i JOIN members m ON m.member_id = i.member_id
            ORDER BY i.fetched_at DESC, i.received_at DESC""")
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["member_id"], {"member_id": r["member_id"], "name": r["name"],
                                               "phone": r["phone"], "unseen": 0, "messages": []})
        g["messages"].append({k: r[k] for k in ("message_id", "received_at", "body", "seen")})
        g["unseen"] += 0 if r["seen"] else 1
    return sorted(groups.values(), key=lambda g: g["unseen"], reverse=True)


def mark_seen(member_id: str) -> dict:
    with db.transaction() as conn:
        n = conn.execute("UPDATE inbox_messages SET seen = 1 WHERE member_id = ? AND seen = 0",
                         (member_id,)).rowcount
    return {"member_id": member_id, "marked": n}
