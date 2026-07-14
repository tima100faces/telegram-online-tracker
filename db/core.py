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
            CREATE TABLE IF NOT EXISTS whitelist (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS access_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT,
                count        INTEGER DEFAULT 1,
                last_attempt TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key          TEXT PRIMARY KEY,
                value        TEXT
            );
        """)
        # Migration: add columns if they don't exist
        for col, typ in [
            ("display_name", "TEXT"),
            ("notify_mode", "TEXT DEFAULT 'online'"),
            ("mute_until", "TIMESTAMP"),
        ]:
            try:
                conn.execute(f"ALTER TABLE tracked_users ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass
        # Migration: v6 multi-user — add tracked_by column
        try:
            conn.execute("ALTER TABLE tracked_users ADD COLUMN tracked_by INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE online_sessions ADD COLUMN tracked_by INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Assign existing tracked users to the current owner
        owner_id = int(os.getenv("OWNER_ID", "0"))
        conn.execute(
            "UPDATE tracked_users SET tracked_by = ? WHERE tracked_by = 0 OR tracked_by IS NULL",
            (owner_id,),
        )
        conn.execute(
            "UPDATE online_sessions SET tracked_by = (SELECT tracked_by FROM tracked_users WHERE tracked_users.user_id = online_sessions.user_id) WHERE tracked_by = 0"
        )

        # Create composite indexes for fast per-user lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_by ON tracked_users(tracked_by)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_tracked ON online_sessions(tracked_by)")

        # Auto-cleanup: keep only last 90 days of sessions
        conn.execute("DELETE FROM online_sessions WHERE date(went_online) < date('now', '-90 days')")


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


def add_user(user_id: int, username: str, first_name: str, tracked_by: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tracked_users(user_id, username, first_name, active, tracked_by)"
            " VALUES (?, ?, ?, 1, ?)",
            (user_id, username, first_name, tracked_by),
        )


def remove_user(user_id: int, tracked_by: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET active=0 WHERE user_id=? AND tracked_by=?",
            (user_id, tracked_by),
        )


def get_active_users(tracked_by: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tracked_users WHERE active=1 AND tracked_by=? ORDER BY username",
            (tracked_by,),
        ).fetchall()


def get_user(user_id: int, tracked_by: int | None = None):
    with get_conn() as conn:
        if tracked_by is not None:
            return conn.execute(
                "SELECT * FROM tracked_users WHERE user_id=? AND tracked_by=?",
                (user_id, tracked_by),
            ).fetchone()
        return conn.execute(
            "SELECT * FROM tracked_users WHERE user_id=?",
            (user_id,),
        ).fetchone()


def get_user_by_username(username: str, tracked_by: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tracked_users WHERE lower(username)=? AND active=1 AND tracked_by=?",
            (username.lower(), tracked_by),
        ).fetchone()


def is_online_now(user_id: int, tracked_by: int | None = None) -> bool:
    with get_conn() as conn:
        sql = "SELECT 1 FROM online_sessions WHERE user_id=? AND went_offline IS NULL"
        params = [user_id]
        if tracked_by is not None:
            sql += " AND tracked_by=?"
            params.append(tracked_by)
        return conn.execute(sql + " LIMIT 1", params).fetchone() is not None


def get_last_seen(user_id: int, tracked_by: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(went_offline) as ls FROM online_sessions WHERE user_id=? AND tracked_by=? AND went_offline IS NOT NULL",
            (user_id, tracked_by),
        ).fetchone()
        return row["ls"] if row else None


def start_session(user_id: int, tracked_by: int):
    """Start a new online session."""
    with get_conn() as conn:
        # Close any open session first
        conn.execute(
            "UPDATE online_sessions SET went_offline=datetime('now') WHERE user_id=? AND tracked_by=? AND went_offline IS NULL",
            (user_id, tracked_by),
        )
        conn.execute(
            "INSERT INTO online_sessions(user_id, went_online, tracked_by) VALUES (?, datetime('now'), ?)",
            (user_id, tracked_by),
        )


def end_session(user_id: int, tracked_by: int):
    """End the latest open session."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE online_sessions SET went_offline=datetime('now') WHERE user_id=? AND tracked_by=? AND went_offline IS NULL",
            (user_id, tracked_by),
        )


def get_daily_log(user_id: int, date: str, page: int = 0, tracked_by: int | None = None) -> list:
    limit, offset = 5, page * 5
    with get_conn() as conn:
        sql = (
            "SELECT * FROM online_sessions WHERE user_id=? AND date(went_online)=?"
        )
        params = [user_id, date]
        if tracked_by is not None:
            sql += " AND tracked_by=?"
            params.append(tracked_by)
        sql += " ORDER BY went_online DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM online_sessions WHERE user_id=? AND date(went_online)=?",
            (user_id, date),
        ).fetchone()[0]
        has_more = (page + 1) * 5 < total
        return list(rows), has_more, page


def get_prev_session(user_id: int, tracked_by: int) -> dict | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM online_sessions WHERE user_id=? AND tracked_by=? AND went_offline IS NOT NULL ORDER BY went_online DESC LIMIT 1",
            (user_id, tracked_by),
        ).fetchone()


def get_export_data(user_id: int, days: int = 365, tracked_by: int | None = None):
    with get_conn() as conn:
        if tracked_by is not None:
            return conn.execute(
                "SELECT user_id, went_online, went_offline FROM online_sessions WHERE user_id=? AND tracked_by=? AND went_online >= date('now', ?) ORDER BY went_online",
                (user_id, tracked_by, f"-{days} days"),
            ).fetchall()
        return conn.execute(
            "SELECT user_id, went_online, went_offline FROM online_sessions WHERE user_id=? AND went_online >= date('now', ?) ORDER BY went_online",
            (user_id, f"-{days} days"),
        ).fetchall()


def get_notify_mode(user_id: int, tracked_by: int) -> str:
    row = get_user(user_id, tracked_by)
    return row["notify_mode"] if row else "online"


def set_notify_mode(user_id: int, mode: str, tracked_by: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET notify_mode=? WHERE user_id=? AND tracked_by=?",
            (mode, user_id, tracked_by),
        )


def is_muted(user_id: int, tracked_by: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT mute_until FROM tracked_users WHERE user_id=? AND tracked_by=?",
            (user_id, tracked_by),
        ).fetchone()
        if not row or not row["mute_until"]:
            return False
        return row["mute_until"] > datetime.now().isoformat()


def mute_user(user_id: int, hours: int, tracked_by: int):
    from datetime import timedelta
    until = (datetime.now() + timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET mute_until=? WHERE user_id=? AND tracked_by=?",
            (until, user_id, tracked_by),
        )


def unmute_user(user_id: int, tracked_by: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET mute_until=NULL WHERE user_id=? AND tracked_by=?",
            (user_id, tracked_by),
        )


def rename_user(user_id: int, name: str, tracked_by: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_users SET display_name=? WHERE user_id=? AND tracked_by=?",
            (name, user_id, tracked_by),
        )


def get_db_stats(tracked_by: int | None = None) -> dict:
    import os as _os
    size = _os.path.getsize(DB_PATH) / (1024 * 1024)
    with get_conn() as conn:
        sessions_sql = "SELECT COUNT(*) FROM online_sessions"
        users_sql = "SELECT COUNT(*) FROM tracked_users WHERE active=1"
        params_s = []
        params_u = []
        if tracked_by is not None:
            sessions_sql += " WHERE tracked_by=?"
            users_sql += " AND tracked_by=?"
            params_s.append(tracked_by)
            params_u.append(tracked_by)
        sessions = conn.execute(sessions_sql, params_s).fetchone()[0]
        users = conn.execute(users_sql, params_u).fetchone()[0]
    return {"size_mb": round(size, 2), "sessions": sessions, "users": users}


def cleanup_old_sessions(days: int, tracked_by: int | None = None):
    with get_conn() as conn:
        sql = f"DELETE FROM online_sessions WHERE date(went_online) < date('now', '-{days} days')"
        params = []
        if tracked_by is not None:
            sql += " AND tracked_by=?"
            params.append(tracked_by)
        conn.execute(sql, params)


def vacuum_db():
    with get_conn() as conn:
        conn.execute("VACUUM")


def get_user_stats(user_id: int, tracked_by: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as sessions,
                COALESCE(SUM(julianday(went_offline) - julianday(went_online)) * 24, 0) as total_h,
                COALESCE(AVG(julianday(went_offline) - julianday(went_online)) * 24 * 60, 0) as avg_min,
                COALESCE(MAX(julianday(went_offline) - julianday(went_online)) * 24 * 60, 0) as longest_min
            FROM online_sessions
            WHERE user_id=? AND tracked_by=? AND went_offline IS NOT NULL""",
            (user_id, tracked_by),
        ).fetchone()

        streak = conn.execute(
            """WITH days AS (
                SELECT DISTINCT date(went_online) as d FROM online_sessions
                WHERE user_id=? AND tracked_by=?
                ORDER BY d DESC
            )
            SELECT COUNT(*) FROM days d1
            WHERE julianday((SELECT MAX(d) FROM days)) - julianday(d1.d) + 1 = (
                SELECT COUNT(*) FROM days d2 WHERE d2.d >= d1.d
            )""",
            (user_id, tracked_by),
        ).fetchone()

        return {
            "sessions": int(row["sessions"]),
            "total_h": round(row["total_h"], 1),
            "avg_min": round(row["avg_min"], 1),
            "longest_min": round(row["longest_min"], 1),
            "streak_days": int(streak[0]) if streak else 0,
        }


def get_hourly_activity(user_id: int, days: int, tracked_by: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT CAST(strftime('%H', went_online) AS INTEGER) as h, COUNT(*) as cnt
            FROM online_sessions
            WHERE user_id=? AND tracked_by=? AND went_online >= date('now', ?)
            GROUP BY h ORDER BY h""",
            (user_id, tracked_by, f"-{days} days"),
        ).fetchall()
    result = [(h, 0) for h in range(24)]
    for r in rows:
        result[r["h"]] = (r["h"], r["cnt"])
    return result


def get_overall_stats(tracked_by: int) -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as s, COALESCE(SUM(julianday(went_offline) - julianday(went_online)) * 24, 0) as h FROM online_sessions WHERE tracked_by=?",
            (tracked_by,),
        ).fetchone()
        users = conn.execute(
            """SELECT u.user_id, u.username, u.display_name,
                COUNT(s.id) as sessions,
                COALESCE(SUM(julianday(s.went_offline) - julianday(s.went_online)) * 24, 0) as total_h
            FROM tracked_users u
            LEFT JOIN online_sessions s ON u.user_id = s.user_id AND s.tracked_by = u.tracked_by
            WHERE u.active=1 AND u.tracked_by=?
            GROUP BY u.user_id
            ORDER BY total_h DESC""",
            (tracked_by,),
        ).fetchall()

        user_list = []
        for u in users:
            name = u["display_name"] or u["username"] or str(u["user_id"])
            user_list.append({
                "name": name,
                "sessions": u["sessions"],
                "total_h": round(u["total_h"], 1),
            })

        return {
            "total_sessions": int(total["s"]),
            "total_h": round(total["h"], 1),
            "users": user_list,
        }
