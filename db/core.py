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
        # Auto-cleanup: keep only last 90 days of sessions
        conn.execute(
            "DELETE FROM online_sessions WHERE date(went_online) < date('now', '-90 days')"
        )


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


def get_db_stats():
    """Return {size_bytes, sessions, users, whitelist, access_log}."""
    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    with get_conn() as conn:
        sessions = conn.execute("SELECT COUNT(*) FROM online_sessions").fetchone()[0]
        users_count = conn.execute("SELECT COUNT(*) FROM tracked_users WHERE active=1").fetchone()[0]
        return {
            "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 2),
            "sessions": sessions,
            "users": users_count,
        }


def cleanup_old_sessions(keep_days: int = 90) -> int:
    """Delete sessions older than keep_days. Returns deleted count."""
    with get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) FROM online_sessions").fetchone()[0]
        conn.execute("DELETE FROM online_sessions WHERE date(went_online) < date('now', ?)",
                     (f"-{keep_days} days",))
        after = conn.execute("SELECT COUNT(*) FROM online_sessions").fetchone()[0]
        return before - after


def vacuum_db():
    """Compact the database file."""
    with get_conn() as conn:
        conn.execute("VACUUM")


def get_user_stats(user_id: int):
    """Return per-user aggregated stats."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as sessions,"
            " SUM(CAST((julianday(COALESCE(went_offline, datetime('now')))"
            " - julianday(went_online)) * 86400 AS INTEGER)) as total_sec"
            " FROM online_sessions WHERE user_id=?",
            (user_id,),
        ).fetchone()
        avg = conn.execute(
            "SELECT CAST(AVG(CAST((julianday(went_offline) - julianday(went_online))"
            " * 86400 AS INTEGER)) AS INTEGER) as avg_sec"
            " FROM online_sessions WHERE user_id=? AND went_offline IS NOT NULL",
            (user_id,),
        ).fetchone()
        # Longest/shortest
        extremes = conn.execute(
            "SELECT"
            " MAX(CAST((julianday(went_offline) - julianday(went_online)) * 86400 AS INTEGER)) as longest,"
            " MIN(CAST((julianday(went_offline) - julianday(went_online)) * 86400 AS INTEGER)) as shortest"
            " FROM online_sessions WHERE user_id=? AND went_offline IS NOT NULL",
            (user_id,),
        ).fetchone()
        # Streak
        streak = conn.execute(
            "SELECT COUNT(DISTINCT date(went_online)) FROM online_sessions"
            " WHERE user_id=? AND date(went_online) >= date('now', '-30 days')",
            (user_id,),
        ).fetchone()[0]
        secs = total["total_sec"] or 0
        avg_sec = avg["avg_sec"] or 0
        return {
            "sessions": total["sessions"],
            "total_sec": secs,
            "total_h": round(secs / 3600, 1),
            "avg_min": round(avg_sec / 60, 1),
            "longest_min": round((extremes["longest"] or 0) / 60, 1),
            "shortest_sec": extremes["shortest"] or 0,
            "streak_days": streak,
        }


def get_hourly_activity(user_id: int, days: int = 7):
    """Return list of (hour, count) for 0-23."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT CAST(strftime('%H', went_online) AS INTEGER) as h, COUNT(*) as cnt"
            " FROM online_sessions WHERE user_id=? AND date(went_online) >= date('now', ?)"
            " GROUP BY h ORDER BY h",
            (user_id, f"-{days} days"),
        ).fetchall()
        lookup = {r["h"]: r["cnt"] for r in rows}
        return [(h, lookup.get(h, 0)) for h in range(24)]


def get_overall_stats():
    """Return global stats across all active users."""
    with get_conn() as conn:
        total_sessions = conn.execute("SELECT COUNT(*) FROM online_sessions").fetchone()[0]
        total_sec = conn.execute(
            "SELECT SUM(CAST((julianday(COALESCE(went_offline, datetime('now')))"
            " - julianday(went_online)) * 86400 AS INTEGER)) FROM online_sessions"
        ).fetchone()[0] or 0
        users = conn.execute(
            "SELECT t.user_id, t.username, t.display_name,"
            " COUNT(s.user_id) as sessions,"
            " SUM(CAST((julianday(COALESCE(s.went_offline, datetime('now')))"
            " - julianday(s.went_online)) * 86400 AS INTEGER)) as total_sec"
            " FROM tracked_users t LEFT JOIN online_sessions s ON t.user_id=s.user_id"
            " WHERE t.active=1 GROUP BY t.user_id ORDER BY total_sec DESC"
        ).fetchall()
        top = [
            {
                "user_id": u["user_id"],
                "name": u["display_name"] or u["username"] or str(u["user_id"]),
                "sessions": u["sessions"] or 0,
                "total_h": round((u["total_sec"] or 0) / 3600, 1),
            }
            for u in users
        ]
        return {
            "total_sessions": total_sessions,
            "total_h": round(total_sec / 3600, 1),
            "users": top,
        }
