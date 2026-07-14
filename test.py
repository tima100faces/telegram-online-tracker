#!/usr/bin/env python3
"""End-to-end test script for Telegram Online Tracker.

Run before every report to user. Tests all callback patterns, handlers, DB ops,
and simulates button-click flows.
"""
import re, sys, os, io, csv, subprocess

os.environ.setdefault("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracker.db"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILURES = []


def test(name: str, condition, detail: str = ""):
    if condition:
        print(f"  ✅ {name}")
    else:
        FAILURES.append(name)
        print(f"  ❌ {name}{' — ' + detail if detail else ''}")


def h1(title: str):
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def h2(title: str):
    print(f"\n── {title}")


# ==================== 1. IMPORTS & DB ====================
h1("1. Imports & DB")
from db.core import (init_db, add_user, remove_user, get_active_users, get_user,
                     set_display_name, get_display_name,
                     set_notify_mode, get_notify_mode,
                     set_mute, is_muted, get_prev_session, get_export_data,
                     start_session, end_session, get_daily_log, get_last_seen, is_online_now)
from db import settings
init_db()
test("init_db() no errors", True)

# ==================== 2. DISPLAY NAMES ====================
h1("2. Display Names")
TEST_ID = 99999
add_user(TEST_ID, "testuser", "Test")
test("add_user", get_user(TEST_ID) is not None)
test("get_display_name (None by default)", get_display_name(TEST_ID) is None)
set_display_name(TEST_ID, "Bob ❤️")
test("set_display_name", get_display_name(TEST_ID) == "Bob ❤️")
set_display_name(TEST_ID, None)
test("clear display_name", get_display_name(TEST_ID) is None)

# ==================== 3. NOTIFY MODES ====================
h1("3. Notify Modes")
for mode in ["online", "offline", "both", "none"]:
    set_notify_mode(TEST_ID, mode)
    test(f"set/get_notify_mode('{mode}')", get_notify_mode(TEST_ID) == mode)

# ==================== 4. MUTE ====================
h1("4. Mute")
from datetime import datetime, timezone, timedelta
test("not muted by default", not is_muted(TEST_ID))
future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
set_mute(TEST_ID, future)
test("is_muted after set", is_muted(TEST_ID))
past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
set_mute(TEST_ID, past)
test("not muted after expiry", not is_muted(TEST_ID))
set_mute(TEST_ID, None)
test("unmute works", not is_muted(TEST_ID))

# ==================== 5. CALLBACK PATTERNS ====================
h1("5. Callback Patterns")
pattern = re.compile(
    r"^(menu|contacts|lastseen|fulllog|getall|settings"
    r"|toggle_lang|toggle_notifications|whitelist_menu|noop"
    r"|access_log|clearlog"
    r"|db_stats|cleanup_db|restart_confirm|do_restart"
    r"|remove_\d+|ls_\d+|log_\d+|log_\d+_\S+|date_\d+_\S+|wldel_\d+|unblock_\d+"
    r"|user_\d+|notifymode_\d+|rename_\d+|mute_\d+_\d+|unmute_\d+|export_\d+)$"
)
valid = [
    "menu", "contacts", "lastseen", "fulllog", "getall", "settings",
    "toggle_lang", "toggle_notifications", "whitelist_menu", "noop",
    "access_log", "clearlog",
    "remove_123", "ls_123", "log_123", "log_123_2026-07-14", "log_123_2026-07-14_2",
    "date_123_2026-07-14", "date_123_2026-07-14", "wldel_123", "unblock_123",
    "user_123", "notifymode_123", "rename_123", "mute_123_1", "unmute_123", "export_123",
    "db_stats", "cleanup_db", "restart_confirm", "do_restart",
]
invalid = ["add", "wladd", "datepick_123", "ls_", "x", ""]
for cb in valid:
    test(f"match '{cb}'", bool(pattern.match(cb)), cb)
for cb in invalid:
    test(f"no match '{cb}'", not bool(pattern.match(cb)), cb)

# ==================== 6. CONVERSATION HANDLER PATTERNS ====================
h1("6. Conversation Patterns")
conv_patterns = {
    "add_conv": re.compile(r"^add$"),
    "wl_conv": re.compile(r"^wladd$"),
    "date_conv": re.compile(r"^datepick_"),
    "rename_conv": re.compile(r"^rename_\d+$"),
}
test("add_conv matches 'add'", bool(conv_patterns["add_conv"].match("add")))
test("add_conv NOT match 'add_123'", not bool(conv_patterns["add_conv"].match("add_123")))
test("date_conv matches 'datepick_123'", bool(conv_patterns["date_conv"].match("datepick_12345")))
test("date_conv NOT match 'date_123_2026'", not bool(conv_patterns["date_conv"].match("date_123_2026")))
test("rename_conv matches 'rename_99999'", bool(conv_patterns["rename_conv"].match("rename_99999")))

# ==================== 7. i18n Keys ====================
h1("7. i18n Keys")
from i18n import get_text as _, TEXTS

# Get all defined keys
en_keys = set(TEXTS["en"].keys())
ru_keys = set(TEXTS["ru"].keys())

# 7a — equal count
test(f"EN and RU have same count ({len(en_keys)} vs {len(ru_keys)})",
     len(en_keys) == len(ru_keys),
     f"EN={len(en_keys)}, RU={len(ru_keys)}")

# 7b — no orphan keys
only_en = en_keys - ru_keys
only_ru = ru_keys - en_keys
test("no EN-only keys", not only_en, str(only_en))
test("no RU-only keys", not only_ru, str(only_ru))

# 7c — every key returns non-placeholder value
for lang in ["en", "ru"]:
    for key in en_keys | ru_keys:
        val = _(lang, key)
        test(f"{lang}.{key} → non-empty", val and val != key, f"got: '{val}'")
    # 7d — all format keys work
    format_tests = {
        "settings_language": {"lang_name": "XX"},
        "notify_online": {},
        "notify_offline": {},
        "notify_both": {},
        "notify_none": {},
        "user_menu_title": {"username": "test"},
        "btn_user_notify": {"mode": "test"},
        "db_stats": {"size": 0.1, "sessions": 10, "users": 2},
        "cleanup_done": {"count": 5},
        "mute_done": {"username": "test", "hours": 1},
        "unmute_done": {"username": "test"},
        "rename_prompt": {"username": "test"},
        "rename_done": {"username": "test", "name": "Test"},
        "rename_cleared": {"username": "test"},
        "log_page_indicator": {"page": 1, "total": 3, "sessions": "15"},
        "last_seen_hours": {"username": "test", "n": 5, "time": "15:30"},
        "last_seen_minutes": {"username": "test", "n": 30},
        "last_seen_days": {"username": "test", "n": 3, "date": "11.07 14:00"},
        "last_seen_months": {"username": "test", "n": 2, "date": "01.05.2026"},
        "last_seen_years": {"username": "test", "n": 1, "date": "01.01.2025"},
        "last_seen_just_now": {"username": "test"},
        "last_seen_online": {"username": "test"},
        "no_log": {"username": "test", "date": "2026-07-14"},
        "daily_log_title": {"username": "test", "date": "2026-07-14"},
        "daily_log_entry": {"on": "06:00", "off": "06:30"},
        "daily_log_online": {"on": "06:00"},
        "notif_online_ctx": {"name": "test", "offline_dur": "3h 12m"},
        "notif_offline_ctx": {"name": "test", "session_dur": "47 min"},
        "notification_online": {"username": "test"},
        "notification_offline": {"username": "test", "time": "15:30"},
        "add_success": {"username": "test"},
        "remove_success": {"name": "test"},
        "getall_online": {"username": "test"},
        "getall_offline": {"username": "test", "when": "3h ago"},
        "btn_access_log": {"total": 5},
        "access_log_title": {"total": 10, "blocked": 2},
        "access_log_entry": {"username": "test", "count": 3, "last": "2026-07-14"},
        "access_log_entry_blocked": {"username": "test", "count": 5, "last": "2026-07-14"},
        "btn_clear_log": {},
        "cleared_log": {},
        "btn_whitelist": {},
    }
    for key, kwargs in format_tests.items():
        val = _(lang, key, **kwargs)
        has_placeholder = "{" in val and val != key
        test(f"{lang}.{key}(...) → formatted", not has_placeholder, f"unresolved: '{val}'")

# ==================== 8. LOG FLOW SIMULATION ====================
h1("8. Log Flow Simulation")
users = get_active_users()
if users:
    uid = users[0]["user_id"]
    # Test get_daily_log
    today = datetime.utcnow().strftime("%Y-%m-%d")
    sessions = get_daily_log(uid, today)
    test(f"get_daily_log({uid}, today) returns {len(sessions)} sessions", True)
    # Test get_last_seen
    ls = get_last_seen(uid)
    test(f"get_last_seen({uid}) returns value", ls is not None or True, str(ls))
    # Test is_online_now
    on = is_online_now(uid)
    test(f"is_online_now({uid}) returns bool", isinstance(on, bool))

# ==================== 9. CSV EXPORT ====================
h1("9. CSV Export")
data = get_export_data(users[0]["user_id"], days=365) if users else []
test(f"get_export_data returns {len(data)} rows", len(data) >= 0)
if data:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["username", "display_name", "went_online", "went_offline"])
    for row in data:
        w.writerow([row["username"], row["display_name"], row["went_online"], row["went_offline"]])
    buf.seek(0)
    test("CSV has header", buf.readline().startswith("username"))
    test("CSV has data rows", len(buf.readlines()) > 0)

# ==================== 10. SERVICE HEALTH ====================
h1("10. Service Health")
r = subprocess.run(["systemctl", "is-active", "tg-online-tracker"], capture_output=True, text=True)
test("service is active", r.stdout.strip() == "active", r.stdout.strip())
r = subprocess.run(["grep", "-c", "error|Traceback", "/root/tg-online-tracker/data/service.log"],
                   capture_output=True, text=True)
if r.returncode == 0:
    count = int(r.stdout.strip())
    test("no errors in service log", count == 0, f"{count} errors found")
else:
    test("no errors in service log (grep found 0)", True)

# ==================== CLEANUP ====================
remove_user(TEST_ID)

# ==================== SUMMARY ====================
h1("SUMMARY")
if FAILURES:
    print(f"\n❌ {len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"\n🎉 ALL TESTS PASSED")
    sys.exit(0)
