# Changelog

All notable changes to Telegram Online Tracker.

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
