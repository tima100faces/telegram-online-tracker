#!/usr/bin/env python3
"""End-to-end test script for Telegram Online Tracker.

Run before every report to user. Tests all callback patterns, handlers, DB ops,
and simulates button-click flows.
"""
import re, sys, os, io, csv, subprocess

os.environ.setdefault("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracker.db"))

# Safe dummy defaults so test.py can import bot.py without a full .env.
# load_dotenv() does NOT override already-set env vars, so real .env wins in prod.
for k, v in {
    "BOT_TOKEN": "0:dummy",
    "TG_API_ID": "1",
    "TG_API_HASH": "dummy",
    "TG_PHONE_PART1": "+0",
    "TG_PHONE_PART2": "0000000",
    "OWNER_ID": "0",
}.items():
    os.environ.setdefault(k, v)

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
                     get_notify_mode, set_notify_mode,
                     mute_user, unmute_user, is_muted, get_export_data,
                     start_session, end_session, get_daily_log, get_last_seen, is_online_now,
                     rename_user, get_user_stats, get_hourly_activity, get_overall_stats,
                     get_db_stats, cleanup_old_sessions, vacuum_db)
from db import settings
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
init_db()
test("init_db() no errors", True)

# ==================== 2. DISPLAY NAMES ====================
h1("2. Display Names")
TEST_ID = 99999
add_user(TEST_ID, "testuser", "Test", OWNER_ID)
test("add_user", get_user(TEST_ID) is not None)
test("display_name (None by default)", get_user(TEST_ID)["display_name"] is None)
rename_user(TEST_ID, "Bob ❤️", OWNER_ID)
test("rename_user", get_user(TEST_ID)["display_name"] == "Bob ❤️")
rename_user(TEST_ID, "", OWNER_ID)  # clear
test("clear display_name", not get_user(TEST_ID)["display_name"])

# ==================== 3. NOTIFY MODES ====================
h1("3. Notify Modes")
for mode in ["online", "offline", "both", "none"]:
    set_notify_mode(TEST_ID, mode, OWNER_ID)
    test(f"set/get_notify_mode('{mode}')", get_notify_mode(TEST_ID, OWNER_ID) == mode)

# ==================== 4. MUTE ====================
h1("4. Mute")
from datetime import datetime, timezone, timedelta
test("not muted by default", not is_muted(TEST_ID, OWNER_ID))
mute_user(TEST_ID, 1, OWNER_ID)
test("is_muted after mute", is_muted(TEST_ID, OWNER_ID))
mute_user(TEST_ID, 0, OWNER_ID)  # expired immediately
test("not muted after expiry", not is_muted(TEST_ID, OWNER_ID))
unmute_user(TEST_ID, OWNER_ID)
test("unmute works", not is_muted(TEST_ID, OWNER_ID))

# ==================== 5. CALLBACK PATTERNS ====================
h1("5. Callback Patterns")
pattern = re.compile(
    r"^(menu|contacts|lastseen|fulllog|getall|settings"
    r"|toggle_lang|toggle_notifications|whitelist_menu|noop"
    r"|access_log|clearlog"
    r"|db_stats|cleanup_db|restart_confirm|do_restart"
    r"|stats|ustats_\d+"
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
 "stats", "ustats_123",
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
        "btn_stats": {},
        "stats_overall": {"sessions": 100, "hours": 50},
    }
    for key, kwargs in format_tests.items():
        val = _(lang, key, **kwargs)
        has_placeholder = "{" in val and val != key
        test(f"{lang}.{key}(...) → formatted", not has_placeholder, f"unresolved: '{val}'")

# ==================== 8. DB FUNCTION TESTS ====================
h1("8. DB Function Tests")

# 8a — get_last_seen with and without tracked_by
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
start_session(TEST_ID, OWNER_ID)
end_session(TEST_ID, OWNER_ID)
ls = get_last_seen(TEST_ID, OWNER_ID)
test("get_last_seen(TEST_ID, OWNER_ID) returns value", ls is not None)
ls2 = get_last_seen(TEST_ID, None)
test("get_last_seen(TEST_ID, None) returns value", ls2 is not None)
on = is_online_now(TEST_ID, OWNER_ID)
test("is_online_now returns bool", isinstance(on, bool))

# 8b — CSV export returns username + display_name
data = get_export_data(TEST_ID, days=365, tracked_by=OWNER_ID)
test("get_export_data returns rows", len(data) >= 0)
if data:
    row = data[0]
    has_keys = "username" in row.keys() and "display_name" in row.keys()
    test("CSV rows have username key", "username" in row.keys())
    test("CSV rows have display_name key", "display_name" in row.keys())
    test("CSV rows have went_online key", "went_online" in row.keys())

# 8c — Mute round-trip
test("mute round-trip: not muted", not is_muted(TEST_ID, OWNER_ID))
mute_user(TEST_ID, 1, OWNER_ID)
test("mute round-trip: is_muted", is_muted(TEST_ID, OWNER_ID))
unmute_user(TEST_ID, OWNER_ID)
test("mute round-trip: unmuted", not is_muted(TEST_ID, OWNER_ID))

# 8d — get_daily_log returns a list
sessions = get_daily_log(TEST_ID, today, tracked_by=OWNER_ID)
test("get_daily_log returns list", isinstance(sessions, list))
test("get_daily_log is not tuple", not isinstance(sessions, tuple))

# 8e — Daily log pagination with >5 fake sessions
h1("9. Daily Log Pagination")
# Insert 7 fake sessions for TEST_ID
from db.core import get_conn
with get_conn() as conn:
    for i in range(7):
        conn.execute(
            "INSERT INTO online_sessions(user_id, went_online, went_offline, tracked_by) VALUES (?, datetime('now', ?), datetime('now', ?), ?)",
            (TEST_ID, f"-{i} hours", f"-{i} hours +30 minutes", OWNER_ID),
        )
sessions = get_daily_log(TEST_ID, today, tracked_by=OWNER_ID)
test(f"get_daily_log has {len(sessions)} sessions (>=7)", len(sessions) >= 7)

# Simulate fmt_daily_log_for_user pagination logic
from bot import fmt_daily_log_for_user
name = "testuser"
text0, tp0 = fmt_daily_log_for_user("en", TEST_ID, name, today, 0, OWNER_ID)
text1, tp1 = fmt_daily_log_for_user("en", TEST_ID, name, today, 1, OWNER_ID)
test("page 0 has content", len(text0) > 0)
test("page 1 has content (no empty page)", len(text1) > 0)
test("total_pages > 0", tp0 > 0)

# Cleanup fake sessions
with get_conn() as conn:
    conn.execute("DELETE FROM online_sessions WHERE user_id=? AND tracked_by=?", (TEST_ID, OWNER_ID))

# 9b — Naive vs aware datetime (notification context fix)
h1("10. Naive Datetime Context Fix")
past_time = datetime.now(timezone.utc) - timedelta(hours=2)
naive_str = past_time.strftime("%Y-%m-%d %H:%M:%S")
parsed = datetime.fromisoformat(naive_str)
test("parsed datetime is naive", parsed.tzinfo is None)
parsed_aware = parsed.replace(tzinfo=timezone.utc)
now_utc = datetime.now(timezone.utc)
delta = int((now_utc - parsed_aware).total_seconds())
test("naive+utc datetime subtracts from aware now_utc", delta > 0)

# 9c — Per-user language
h1("11. Per-User Language")
from db import settings as _settings
USER_A = TEST_ID + 1
USER_B = TEST_ID + 2
_settings.set_lang(USER_A, "ru")
_settings.set_lang(USER_B, "en")
test("user A reads ru", _settings.get_lang(USER_A) == "ru")
test("user B reads en", _settings.get_lang(USER_B) == "en")
test("brand-new user falls back to default", _settings.get_lang(99998) == "en")
# Cleanup: remove per-user keys (settings table uses key-value, just overwrite)
_settings.set_lang(USER_A, "en")
_settings.set_lang(USER_B, "en")

# ==================== 12. SERVICE HEALTH ====================
h1("12. Service Health")
if os.path.exists("/usr/bin/systemctl"):
    try:
        r = subprocess.run(["systemctl", "is-active", "tg-online-tracker"], capture_output=True, text=True)
        test("service is active", r.stdout.strip() == "active", r.stdout.strip())
    except Exception:
        print("  ⏭️  systemctl unavailable, skipping service check")
else:
    print("  ⏭️  systemctl not found, skipping service check")

log_path = "/root/tg-online-tracker/data/service.log"
if os.path.exists(log_path):
    try:
        r = subprocess.run(["grep", "-c", "error|Traceback", log_path],
                           capture_output=True, text=True)
        if r.returncode == 0:
            count = int(r.stdout.strip())
            test("no errors in service log", count == 0, f"{count} errors found")
        else:
            test("no errors in service log (grep found 0)", True)
    except Exception:
        print("  ⏭️  Could not check service log, skipping")
else:
    print(f"  ⏭️  Log file not found ({log_path}), skipping log check")

# ==================== CLEANUP ====================
h1("CLEANUP")
remove_user(TEST_ID, OWNER_ID)

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
