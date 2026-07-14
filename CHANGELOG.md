# Changelog

All notable changes to Telegram Online Tracker.

## [v8] — 2026-07-14

### Fixed — Integration bugs (Round 1)
- **Mute/Unmute crash**: `db.set_mute()` → `db.mute_user()` / `db.unmute_user()` — signatures matched
- **Timezone mismatch**: mute logic used local `datetime.now()` while DB stores UTC; now `timezone.utc` everywhere
- **/getall TypeError**: `get_last_seen()` required `tracked_by` but callers omitted it; made it optional with `= None`
- **CSV export crash**: `get_export_data()` returned `user_id`/`went_online`/`went_offline` but `send_csv()` wrote `username`/`display_name`; SQL now JOINs `tracked_users`
- **Daily log pagination broken**: `get_daily_log()` applied `LIMIT 5 OFFSET` in SQL AND caller sliced again — pages after the first were empty. Removed SQL-side pagination, kept it in `fmt_daily_log_for_user()`
- **Custom date NameError**: `current_uid` undefined in `receive_date()` — added missing assignment
- **daemon.py deleted**: dead file with outdated signatures, conflicted with bot.py over session file
- **Notifications toggle did nothing**: `settings.get_notifications_enabled()` was toggled in UI but never checked before sending; now `on_status()` skips sends when off
- **Display name precedence bug**: operator precedence in `contacts_list()` ignored `display_name` when `username` was empty — added parentheses

### Fixed — Security hardening (Round 1)
- `OWNER_ID` in bot.py: `os.getenv(..., "123456789")` → `os.environ["OWNER_ID"]` (fail fast if unset)
- API auth: `if f"Bearer {TOKEN}" in header` → exact comparison `header == f"Bearer {TOKEN}"`
- Removed `?token=` query-param auth path (tokens leak into server logs)
- Removed `BOT_TOKEN` fallback for API auth; `API_TOKEN` unset → all endpoints return 401
- Removed `Access-Control-Allow-Origin: *` header

### Fixed — Tests (Round 1)
- Always-true assertions replaced with real checks: `get_last_seen` both arg variants, CSV column names, mute round-trip, daily log pagination
- `OWNER_ID` in test.py: hardcoded `84295013` → `int(os.getenv("OWNER_ID", "0"))`
- Systemd checks skip gracefully when unavailable instead of crashing

### Fixed — Follow-up (Round 2)
- **Notification context silently broken**: session timestamps from SQLite are naive UTC strings, `datetime.fromisoformat()` returns naive datetime, subtracting from aware `now_utc` raised `TypeError` — caught by bare `except`. Now attaches `tzinfo=timezone.utc` after parsing
- **Per-user language**: `get_lang()`/`set_lang()` were global; now per-user via `lang:<user_id>` keys with fallback global→en
- **test.py crash without .env**: `import bot` required `BOT_TOKEN` etc.; added `os.environ.setdefault()` fallbacks before import
- **API docstring**: removed stale «or BOT_TOKEN as fallback» mention

### Changed — Cleanup (Round 3)
- Module docstring: «daemon + bot» → «single-process bot»
- Removed dead `import random`
- Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)` (+ `.replace(tzinfo=None)` for naive arithmetic)
- Notification send failures now logged (`print`) instead of silently swallowed
- `/health` uptime: `"uptime": "running"` → `"uptime_seconds": <real seconds>`

## [v7] — 2026-07-14

### Added
- **Open Beta mode** — toggle in Settings (admin only). When ON:
  - Whitelist bypassed — anyone can `/start` the bot
  - New users auto-whitelisted on first interaction
  - Max 10 contacts per user
  - Onboarding welcome message on `/start`
  - "Open Beta: ON/OFF" button in admin settings

## [v6] — 2026-07-14

### Added
- **Multi-user isolation** — each whitelisted user has their own workspace
- `tracked_by` column in `tracked_users` and `online_sessions`
- Per-user views: contacts, stats, logs — filtered by who added them
- **Notifications go only to the user who added the contact** (not to owner)
- Telethon handler creates sessions per tracking user

### Changed
- All DB functions accept optional `tracked_by` parameter
- `get_active_users()` — polymorphic: with arg = filtered, without = all
- Helper functions (`contacts_list`, `user_picker`, etc.) pass through tracked_by

### Fixed in v6
- `fmt_daily_log_for_user` TypeError — `get_daily_log` returns 3-value pagination tuple, caller didn't unpack
- `receive_username` — `add_user` missing `tracked_by=effective_user.id`
- `notifymode_` handler — `get/set_notify_mode` missing `current_uid`
- `receive_rename` — called non-existent `set_display_name`, now uses `rename_user(user_id, name, current_uid)`
- Stats no-data alert replaced with persistent message (popup was invisible)
- Admin buttons hidden from non-owner settings menu

## [v5] — 2026-07-14

### Added
- **📊 Statistics** — overall stats (total sessions/hours, top users ranking) + per-user drill-down
- **Hourly activity chart** — 24h emoji heatmap (⬜🟨🟧🟥🟩) with markers every 3 hours
- **Per-user metrics** — sessions, total time, avg session, longest session, streak days
- **REST API** — pure stdlib `http.server`, zero dependencies. Endpoints: `/health`, `/getall`, `/stats`, `/daily/<date>`
- **Auth**: Bearer token or `?token=` query param. Binds to `127.0.0.1:8091`
- **/stats command flow** — overall → pick user → full breakdown + activity chart
- **Auto-cleanup (90 days)**: sessions older than 90 days deleted on `init_db()`

### Changed
- **Display names**: contacts list, stats, notifications — all show custom aliases
- **Contacts UX**: click → user submenu (log, last seen, rename, notify, mute, CSV, remove)
- **CSV export**: per-user session export (`📥 Export`) with 365-day window

### Fixed
- `display()` NameError — missing `db.get_user()` call (broke all log flows)
- Settings buttons lost dynamic counts (whitelist size, notification state)
- Hourly chart label alignment: markers every 3h instead of cluttered all-24
- **Owner could be removed from contacts** — `remove_` handler lacked OWNER_ID guard
- **Undefined `user` variable** in `make_status_handler` — NameError on notification send
- **OWNER_ID missing from `.env`** — defaulted to placeholder `123456789`, owner lost access

## [v4] — 2026-07-14

### Added
- **Per-user notification modes**: online / offline / both / none (via user submenu 🔔)
- **Per-user mute**: 1h / 4h / 24h mute with expiry (🔇 button)
- **Display names / aliases**: custom names for contacts (✏️ Rename)
- **Context in notifications**: "🟢 Dex online (was offline 3h 12m)" / "⚫ Dex offline (session 47 min)"
- **CSV export** — per-user `.csv` with all sessions (📥 button)
- **Quick actions** in user submenu: log, last seen, rename, notify, mute, export, remove
- **Default notification mode**: online-only (no more offline spam)

### Changed
- Contacts list → navigates to per-user action submenu instead of instant remove
- DB schema: `notify_mode`, `mute_until`, `display_name` columns added
- i18n expanded to ~101 keys per language

## [v3] — 2026-07-13

### Added
- Pagination in daily log: "📄 More →" button (5 sessions per page)
- Access log with blocking: tracks unauthorized attempts, auto-blocks after 5
- Whitelist management from settings menu
- i18n: English + Russian with 60+ keys
- Settings menu with language toggle, notifications toggle

### Changed
- License: MIT → GPL-3.0
- Bot username: fixed to @tgonlinetrackbot

## [v2] — 2026-07-12

### Added
- Event-driven online/offline tracking via Telethon
- SQLite database for sessions and users
- `/add` command with ConversationHandler
- `/getall` — all contacts with status
- `/lastseen` — last seen per user
- Daily log with date picker
- Push notifications to owner

## [v1] — 2026-07-11

### Added
- Initial prototype: tracking via polling (later replaced with events)
- Telegram bot scaffold with python-telegram-bot
- Telethon MTProto client
