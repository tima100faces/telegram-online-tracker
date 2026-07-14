#!/usr/bin/env python3
"""Lightweight REST API for Telegram Online Tracker.

Zero dependencies — pure Python stdlib http.server.
Auth via API_TOKEN in .env or BOT_TOKEN as fallback.
Binds to localhost only.

Endpoints:
  GET /health              — bot status (no auth)
  GET /getall              — all tracked users with online status
  GET /stats/<user_id>     — stats for one user
  GET /stats               — overall stats
  GET /daily/<date>        — daily log for date (YYYY-MM-DD)

All data queries run in a thread-safe wrapper via sqlite3 WAL mode.
"""
import json
import os
import re
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse


# ── Config ─────────────────────────────────────────────────────────
HOST = os.getenv("API_HOST", "127.0.0.1")
PORT = int(os.getenv("API_PORT", "8091"))
TOKEN = os.getenv("API_TOKEN") or os.getenv("BOT_TOKEN") or "changeme"


# ── Helpers ────────────────────────────────────────────────────────
def load_db():
    """Lazy import to avoid circular deps during bot startup."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import db.core as _db
    return _db


def json_response(handler, data, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())


def check_auth(handler) -> bool:
    header = handler.headers.get("Authorization", "")
    if f"Bearer {TOKEN}" in header:
        return True
    # Also accept ?token=XXX in URL
    from urllib.parse import parse_qs, urlparse
    params = parse_qs(urlparse(handler.path).query)
    return params.get("token", [None])[0] == TOKEN


# ── Handlers ───────────────────────────────────────────────────────
class APIHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Health — no auth
        if path == "/health":
            db = load_db()
            stats = db.get_db_stats()
            return json_response(self, {
                "status": "ok",
                "uptime": "running",
                "db_size_mb": stats["size_mb"],
                "users": stats["users"],
                "sessions": stats["sessions"],
            })

        # Auth check for all other endpoints
        if not check_auth(self):
            return json_response(self, {"error": "unauthorized"}, 401)

        db = load_db()

        # ── /getall ──
        if path == "/getall":
            users = db.get_active_users()
            result = []
            for u in users:
                uid = u["user_id"]
                online = db.is_online_now(uid)
                last = db.get_last_seen(uid)
                name = u["display_name"] or u["username"] or str(uid)
                result.append({
                    "user_id": uid,
                    "username": u["username"],
                    "display_name": u["display_name"],
                    "name": name,
                    "online": online,
                    "last_seen": last,
                    "notify_mode": u["notify_mode"] if "notify_mode" in u.keys() else "online",
                })
            return json_response(self, {"users": result, "count": len(result)})

        # ── /stats/<user_id> ──
        m = re.match(r"^/stats/(\d+)$", path)
        if m:
            user_id = int(m.group(1))
            user = db.get_user(user_id)
            if not user:
                return json_response(self, {"error": "user not found"}, 404)

            # Aggregate stats
            with db.get_conn() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) as cnt,"
                    " SUM(CAST((julianday(COALESCE(went_offline, datetime('now')))"
                    "           - julianday(went_online)) * 86400 AS INTEGER)) as total_sec"
                    " FROM online_sessions WHERE user_id=?",
                    (user_id,),
                ).fetchone()
                avg = conn.execute(
                    "SELECT AVG(CAST((julianday(COALESCE(went_offline, datetime('now')))"
                    "           - julianday(went_online)) * 86400 AS INTEGER)) as avg_sec"
                    " FROM online_sessions WHERE user_id=? AND went_offline IS NOT NULL",
                    (user_id,),
                ).fetchone()
                # Streak: consecutive days with activity
                streak_row = conn.execute("""
                    WITH days AS (
                        SELECT DISTINCT date(went_online) as d
                        FROM online_sessions WHERE user_id=?
                        ORDER BY d DESC
                    )
                    SELECT COUNT(*) FROM days
                    WHERE julianday(d) >= julianday(
                        (SELECT d FROM days LIMIT 1), '-'
                    ) - (SELECT COUNT(*) FROM days)
                """, (user_id,)).fetchone()

            secs = total["total_sec"] or 0
            avg_secs = int(avg["avg_sec"] or 0)
            h, m_mod = divmod(secs, 3600)
            ah, am = divmod(avg_secs, 60)
            return json_response(self, {
                "user_id": user_id,
                "username": user["username"],
                "display_name": user["display_name"],
                "total_sessions": total["cnt"],
                "total_time_h": round(h + m_mod / 60, 1),
                "avg_session_min": ah,
                "streak_days": streak_row[0] if streak_row else 0,
            })

        # ── /stats ──
        if path == "/stats":
            users = db.get_active_users()
            result = []
            with db.get_conn() as conn:
                for u in users:
                    uid = u["user_id"]
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt,"
                        " SUM(CAST((julianday(COALESCE(went_offline, datetime('now')))"
                        "           - julianday(went_online)) * 86400 AS INTEGER)) as total_sec"
                        " FROM online_sessions WHERE user_id=?",
                        (uid,),
                    ).fetchone()
                    secs = row["total_sec"] or 0
                    h, m_mod = divmod(secs, 3600)
                    result.append({
                        "user_id": uid,
                        "username": u["username"],
                        "display_name": u["display_name"],
                        "sessions": row["cnt"],
                        "total_time_h": round(h + m_mod / 60, 1),
                    })
            return json_response(self, {"users": result, "count": len(result)})

        # ── /daily/<date> ──
        m = re.match(r"^/daily/(\d{4}-\d{2}-\d{2})$", path)
        if m:
            date_str = m.group(1)
            users = db.get_active_users()
            result = []
            for u in users:
                sessions = db.get_daily_log(u["user_id"], date_str)
                if sessions:
                    result.append({
                        "user_id": u["user_id"],
                        "username": u["username"],
                        "display_name": u["display_name"],
                        "sessions": [
                            {"online": s["went_online"], "offline": s["went_offline"]}
                            for s in sessions
                        ],
                    })
            return json_response(self, {"date": date_str, "users": result})

        return json_response(self, {"error": "not found"}, 404)


def run_api():
    """Start API server in a background thread."""
    server = HTTPServer((HOST, PORT), APIHandler)
    server.timeout = 1
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[api] listening on http://{HOST}:{PORT}")
    return server
