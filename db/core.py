"""SQLite database layer for TG Online Tracker."""
import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tracker.db"))


def init_db():
    """Create tables and indexes if not exist, migrate schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tracked_users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active      INTEGER DEFAULT 1,
                display_name TEXT,
                notify_mode TEXT DEFAULT 'online',
                mute_until  TIMESTAMP
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
        for col, typ in [
            ("display_name", "TEXT"),
            ("notify_mode", "TEXT DEFAULT 'online'"),
            ("mute_until", "TIMESTAMP"),
        ]:
            try:
                conn.execute(f"ALTER TABLE tracked_users ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass


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
            "SELECT * FROM tracked_users WHERE lower(username)=? AND active=1",
            (username.lower(),),
        ).fetchone()


def start_session(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO online_sessions(user_id, went_online) VALUES (?, datetime('now'))",
            (user_id,),
        )


def end_session(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE online_sessions SET went_offline=datetime('now')"
            " WHERE user_id=? AND went_offline IS NULL"
            " ORDER BY went_online DESC LIMIT 1",
            (user_id,),
        )


def get_last_seen(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT went_offline FROM online_sessions"
            " WHERE user_id=? AND went_offline IS NOT NULL"
            " ORDER BY went_offline DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row:
            return row["went_offline"]
        row = conn.execute(
            "SELECT went_online FROM online_sessions"
            " WHERE user_id=? AND went_offline IS NULL"
            " ORDER BY went_online DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["went_online"] if row else None


def get_daily_log(user_id: int, date_str: str = None):
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


# ── v3: Display name, notify mode, mute, context ────────────────


def set_display_name(user_id: int, name: str | None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET display_name=? WHERE user_id=?",
            (name, user_id),
        )


def get_display_name(user_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT display_name FROM tracked_users WHERE user_id=?", (user_id,)
        ).fetchone()
        return row and row["display_name"]


def set_notify_mode(user_id: int, mode: str):
    """mode: 'online', 'offline', 'both', 'none'"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET notify_mode=? WHERE user_id=?",
            (mode, user_id),
        )


def get_notify_mode(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT notify_mode FROM tracked_users WHERE user_id=?", (user_id,)
        ).fetchone()
        return row["notify_mode"] if row else "online"


def set_mute(user_id: int, until_iso: str | None):
    """Set mute_until timestamp (ISO string) or None to unmute."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET mute_until=? WHERE user_id=?",
            (until_iso, user_id),
        )


def is_muted(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT mute_until FROM tracked_users WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row or not row["mute_until"]:
            return False
        return datetime.utcnow().isoformat() < row["mute_until"]


def get_prev_session(user_id: int):
    """Get the most recent completed session (for context calculation)."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT went_online, went_offline FROM online_sessions"
            " WHERE user_id=? AND went_offline IS NOT NULL"
            " ORDER BY went_offline DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def get_export_data(user_id: int = None, days: int = 365):
    """Get all sessions for CSV export."""
    with get_conn() as conn:
        if user_id:
            return conn.execute(
                "SELECT u.username, u.display_name, s.went_online, s.went_offline"
                " FROM online_sessions s JOIN tracked_users u ON s.user_id=u.user_id"
                " WHERE s.user_id=? AND date(s.went_online) >= date('now', ?)"
                " ORDER BY s.went_online",
                (user_id, f"-{days} days"),
            ).fetchall()
        return conn.execute(
            "SELECT u.username, u.display_name, s.went_online, s.went_offline"
            " FROM online_sessions s JOIN tracked_users u ON s.user_id=u.user_id"
            " WHERE date(s.went_online) >= date('now', ?)"
            " ORDER BY s.went_online",
            (f"-{days} days",),
        ).fetchall()
