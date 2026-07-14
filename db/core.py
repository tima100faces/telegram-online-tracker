"""SQLite database layer for TG Online Tracker."""
import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tracker.db"))


def init_db():
    """Create tables and indexes if not exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tracked_users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active      INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS online_sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER REFERENCES tracked_users(user_id),
                went_online  TIMESTAMP NOT NULL,
                went_offline TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user_time
                ON online_sessions(user_id, went_online);
        """)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_user(user_id: int, username: str, first_name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tracked_users(user_id, username, first_name, active)"
            " VALUES (?, ?, ?, 1)",
            (user_id, username, first_name),
        )


def remove_user(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE tracked_users SET active=0 WHERE user_id=?", (user_id,))


def get_active_users():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tracked_users WHERE active=1 ORDER BY username"
        ).fetchall()


def get_user(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tracked_users WHERE user_id=?", (user_id,)
        ).fetchone()


def get_user_by_username(username: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tracked_users WHERE username=? AND active=1",
            (username.lstrip("@"),),
        ).fetchone()


def start_session(user_id: int, went_online: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO online_sessions(user_id, went_online) VALUES (?, ?)",
            (user_id, went_online),
        )


def end_session(user_id: int, went_offline: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE online_sessions SET went_offline=?"
            " WHERE user_id=? AND went_offline IS NULL"
            " ORDER BY went_online DESC LIMIT 1",
            (went_offline, user_id),
        )


def get_last_seen(user_id: int):
    """Return the most recent went_offline timestamp, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT went_offline FROM online_sessions"
            " WHERE user_id=? AND went_offline IS NOT NULL"
            " ORDER BY went_offline DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["went_offline"] if row else None


def get_daily_log(user_id: int, date_str: str = None):
    """Return all sessions for a date (YYYY-MM-DD). Default: today."""
    if date_str is None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
    with get_conn() as conn:
        return conn.execute(
            "SELECT went_online, went_offline FROM online_sessions"
            " WHERE user_id=? AND date(went_online)=?"
            " ORDER BY went_online",
            (user_id, date_str),
        ).fetchall()


def is_online_now(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM online_sessions"
            " WHERE user_id=? AND went_offline IS NULL LIMIT 1",
            (user_id,),
        ).fetchone()
        return row is not None
