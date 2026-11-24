"""SQLite storage: schema, connections, transactions and backups. No server needed."""
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime

from app import config
from app.errors import AppError

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    member_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    phone        TEXT NOT NULL,
    monthly_fee  NUMERIC NOT NULL CHECK (monthly_fee > 0),
    joining_date TEXT NOT NULL DEFAULT '',
    due_date     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Inactive')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_members_name_phone ON members (lower(name), phone);
CREATE INDEX IF NOT EXISTS ix_members_phone ON members (phone);

CREATE TABLE IF NOT EXISTS payments (
    payment_id     TEXT PRIMARY KEY,
    member_id      TEXT NOT NULL REFERENCES members (member_id),
    payment_month  TEXT NOT NULL CHECK (payment_month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    amount         NUMERIC NOT NULL CHECK (amount > 0),
    payment_date   TEXT NOT NULL DEFAULT '',
    payment_status TEXT NOT NULL DEFAULT 'Pending' CHECK (payment_status IN ('Pending', 'Paid')),
    payment_mode   TEXT NOT NULL DEFAULT '' CHECK (payment_mode IN ('', 'UPI', 'Cash', 'Bank Transfer', 'Other')),
    UNIQUE (member_id, payment_month)
);
CREATE INDEX IF NOT EXISTS ix_payments_status ON payments (payment_status, payment_month);

CREATE TABLE IF NOT EXISTS reminder_logs (
    reminder_id   TEXT PRIMARY KEY,
    member_id     TEXT NOT NULL REFERENCES members (member_id),
    payment_month TEXT NOT NULL,
    reminder_date TEXT NOT NULL,
    reminder_type TEXT NOT NULL CHECK (reminder_type IN ('Before Due', 'Due Date', 'Overdue')),
    message       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'Prepared' CHECK (status IN ('Prepared', 'Sent', 'Failed')),
    sent_at       TEXT NOT NULL DEFAULT '',
    UNIQUE (member_id, payment_month, reminder_type, reminder_date)
);
CREATE INDEX IF NOT EXISTS ix_logs_member_month ON reminder_logs (member_id, payment_month);

CREATE TABLE IF NOT EXISTS inbox_messages (
    message_id  TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL REFERENCES members (member_id),
    received_at TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL,
    seen        INTEGER NOT NULL DEFAULT 0,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS ix_inbox_member ON inbox_messages (member_id, seen);
"""

_BUSY = "The database is busy. Try again in a moment."


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def ensure_db() -> bool:
    """Create the schema if needed. Returns True if the database file is brand new."""
    is_new = not config.DB_PATH.exists()
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
    return is_new


@contextmanager
def read():
    ensure_db()
    with closing(connect()) as conn:
        yield conn


@contextmanager
def transaction():
    """One atomic write transaction. Any exception rolls everything back."""
    ensure_db()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower() or "busy" in str(e).lower():
            raise AppError(423, _BUSY)
        raise
    finally:
        conn.close()


def rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def next_id(conn, table: str, col: str, prefix: str, width: int = 4) -> str:
    nums = []
    for (v,) in conn.execute(f"SELECT {col} FROM {table} WHERE {col} GLOB ?", (prefix + "[0-9]*",)):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", v)
        if m:
            nums.append(int(m.group(1)))
    return f"{prefix}{(max(nums) + 1 if nums else 1):0{width}d}"


def backup(reason: str = "manual"):
    """Consistent copy of the live database into data/backups. Keeps the newest 30."""
    if not config.DB_PATH.exists():
        return None
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    reason = re.sub(r"[^a-z0-9]", "", reason.lower())
    target = config.BACKUP_DIR / f"gym_{stamp}_{reason}.db"
    n = 1
    while target.exists():
        target = config.BACKUP_DIR / f"gym_{stamp}_{reason}_{n}.db"
        n += 1
    with closing(connect()) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    old = sorted(config.BACKUP_DIR.glob("gym_*.db"), key=lambda p: p.stat().st_mtime)
    for p in old[:-config.KEEP_BACKUPS]:
        p.unlink(missing_ok=True)
    return target.name


def backup_daily():
    """At most one automatic backup per day."""
    today = datetime.now().strftime("%Y%m%d")
    if config.BACKUP_DIR.exists() and any(config.BACKUP_DIR.glob(f"gym_{today}_*_daily*.db")):
        return None
    return backup("daily")