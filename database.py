import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "subscribers.db"))


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_ts():
    return int(time.time())


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_email(email):
    return (email or "").strip().lower()


def init_db():
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                email TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                telegram_chat_id INTEGER UNIQUE,
                link_code TEXT UNIQUE,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_subscribers_expires ON subscribers(expires_at)"
        )


def _row(row):
    return dict(row) if row else None


def get_subscriber(email):
    email = normalize_email(email)
    with _conn() as conn:
        row = conn.execute("SELECT * FROM subscribers WHERE email = ?", (email,)).fetchone()
    return _row(row)


def list_subscribers(query=""):
    query = (query or "").strip().lower()
    with _conn() as conn:
        if query:
            rows = conn.execute(
                "SELECT * FROM subscribers WHERE email LIKE ? OR note LIKE ? "
                "ORDER BY expires_at ASC",
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM subscribers ORDER BY expires_at ASC").fetchall()
    return [dict(r) for r in rows]


def upsert_subscriber(email, expires_at, note=None):
    email = normalize_email(email)
    stamp = now_iso()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO subscribers (email, expires_at, status, note, created_at, updated_at)
            VALUES (?, ?, 'ACTIVE', ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                expires_at = excluded.expires_at,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (email, int(expires_at), note, stamp, stamp),
        )


def set_expiry(email, expires_at):
    email = normalize_email(email)
    with _conn() as conn:
        conn.execute(
            "UPDATE subscribers SET expires_at = ?, updated_at = ? WHERE email = ?",
            (int(expires_at), now_iso(), email),
        )


def set_status(email, status):
    email = normalize_email(email)
    status = "BLOCKED" if str(status).upper() == "BLOCKED" else "ACTIVE"
    with _conn() as conn:
        conn.execute(
            "UPDATE subscribers SET status = ?, updated_at = ? WHERE email = ?",
            (status, now_iso(), email),
        )


def delete_subscriber(email):
    email = normalize_email(email)
    with _conn() as conn:
        conn.execute("DELETE FROM subscribers WHERE email = ?", (email,))


def set_telegram_chat(email, chat_id):
    email = normalize_email(email)
    with _conn() as conn:
        conn.execute(
            "UPDATE subscribers SET telegram_chat_id = ?, updated_at = ? WHERE email = ?",
            (int(chat_id) if chat_id else None, now_iso(), email),
        )


def find_by_chat(chat_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE telegram_chat_id = ?", (int(chat_id),)
        ).fetchone()
    return _row(row)


def new_link_code(email):
    email = normalize_email(email)
    with _conn() as conn:
        for _ in range(10):
            code = secrets.token_hex(4).upper()
            try:
                conn.execute(
                    "UPDATE subscribers SET link_code = ?, updated_at = ? WHERE email = ?",
                    (code, now_iso(), email),
                )
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("No se pudo generar un codigo de vinculacion unico")


def find_by_link_code(code):
    code = (code or "").strip().upper()
    if not code:
        return None
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscribers WHERE link_code = ?", (code,)
        ).fetchone()
    return _row(row)


def clear_link_code(email):
    email = normalize_email(email)
    with _conn() as conn:
        conn.execute(
            "UPDATE subscribers SET link_code = NULL, updated_at = ? WHERE email = ?",
            (now_iso(), email),
        )


def subscription_state(subscriber):
    if not subscriber:
        return "not_subscribed"
    if subscriber.get("status") != "ACTIVE":
        return "blocked"
    if int(subscriber.get("expires_at") or 0) <= now_ts():
        return "expired"
    return "active"
