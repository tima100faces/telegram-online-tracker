"""Database layer — whitelist and settings on top of db.py."""
import sqlite3
from contextlib import contextmanager
from . import core as _db


# ── Settings ──────────────────────────────────────────────────────────


def _ensure_settings_table():
    with _db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


def get_setting(key: str, default: str = "") -> str:
    _ensure_settings_table()
    with _db.get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    _ensure_settings_table()
    with _db.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            (key, value),
        )


def get_lang() -> str:
    return get_setting("lang", "en")


def set_lang(lang: str):
    set_setting("lang", lang)


def get_notifications_enabled() -> bool:
    return get_setting("notifications", "1") == "1"


def set_notifications_enabled(enabled: bool):
    set_setting("notifications", "1" if enabled else "0")


# ── Open Beta mode ────────────────────────────────────────────────────


def is_open_beta() -> bool:
    return get_setting("open_beta", "0") == "1"


def set_open_beta(enabled: bool):
    set_setting("open_beta", "1" if enabled else "0")


# ── Whitelist ─────────────────────────────────────────────────────────


def _ensure_whitelist_table():
    with _db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whitelist (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                added_by   INTEGER,
                added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def is_whitelisted(user_id: int) -> bool:
    """Check if user_id is in the whitelist."""
    _ensure_whitelist_table()
    with _db.get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM whitelist WHERE user_id=?", (user_id,)
        ).fetchone()
        return row is not None


def add_to_whitelist(user_id: int, username: str = "", added_by: int = 0):
    _ensure_whitelist_table()
    with _db.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO whitelist(user_id, username, added_by)"
            " VALUES (?, ?, ?)",
            (user_id, username, added_by),
        )


def remove_from_whitelist(user_id: int):
    _ensure_whitelist_table()
    with _db.get_conn() as conn:
        conn.execute("DELETE FROM whitelist WHERE user_id=?", (user_id,))


def get_whitelist():
    _ensure_whitelist_table()
    with _db.get_conn() as conn:
        return conn.execute(
            "SELECT * FROM whitelist ORDER BY username"
        ).fetchall()


# ── Access Log ────────────────────────────────────────────────────────

MAX_ATTEMPTS = 5


def _ensure_access_log_table():
    with _db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_log (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                attempt_count INTEGER DEFAULT 0,
                last_attempt  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                blocked       INTEGER DEFAULT 0
            )
        """)


def log_access(user_id: int, username: str, first_name: str) -> bool:
    """Record an unauthorized access attempt.
    Returns True if this attempt crossed the block threshold (just_blocked).
    """
    _ensure_access_log_table()
    with _db.get_conn() as conn:
        conn.execute("""
            INSERT INTO access_log(user_id, username, first_name, attempt_count, last_attempt)
            VALUES (?, ?, ?, 1, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                attempt_count = attempt_count + 1,
                last_attempt = datetime('now'),
                username = COALESCE(NULLIF(excluded.username, ''), username),
                first_name = COALESCE(NULLIF(excluded.first_name, ''), first_name)
        """, (user_id, username, first_name))
        row = conn.execute(
            "SELECT attempt_count, blocked FROM access_log WHERE user_id=?", (user_id,)
        ).fetchone()
        just_blocked = row["attempt_count"] >= MAX_ATTEMPTS and not row["blocked"]
        if just_blocked:
            conn.execute(
                "UPDATE access_log SET blocked=1 WHERE user_id=?", (user_id,)
            )
        return just_blocked


def is_blocked(user_id: int) -> bool:
    _ensure_access_log_table()
    with _db.get_conn() as conn:
        row = conn.execute(
            "SELECT blocked FROM access_log WHERE user_id=?", (user_id,)
        ).fetchone()
        return bool(row and row["blocked"])


def unblock_user(user_id: int):
    _ensure_access_log_table()
    with _db.get_conn() as conn:
        conn.execute(
            "UPDATE access_log SET blocked=0 WHERE user_id=?", (user_id,)
        )


def get_access_log():
    _ensure_access_log_table()
    with _db.get_conn() as conn:
        return conn.execute(
            "SELECT * FROM access_log ORDER BY last_attempt DESC"
        ).fetchall()


def clear_access_log():
    _ensure_access_log_table()
    with _db.get_conn() as conn:
        conn.execute("DELETE FROM access_log")
