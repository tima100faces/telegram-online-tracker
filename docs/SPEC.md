# Specification — TG Online Tracker v6

## Objective

Track exact Telegram online/offline timestamps for specified users. Multi-user bot with per-user workspace isolation and REST API.

## Core Principles

- **Event-driven, not polling.** Listens for `UpdateUserStatus` from MTProto — no periodic requests, no flood risks.
- **Exact timestamps.** `was_online` captured from `UserStatusOffline` event, not "recently" approximations.
- **Per-user isolation.** Each whitelisted user sees only their own contacts, stats, and gets only their own notifications.
- **Push notifications.** DM when a tracked contact changes status (configurable per-user).
- **Whitelist-only.** Only authorized users can interact. Owner always bypasses.

## Features

### v1 — Core
- [x] Event-driven online/offline detection via Telethon
- [x] SQLite session storage
- [x] Inline-menu bot
- [x] Add/remove tracked users
- [x] Last seen view
- [x] Daily session log with date picker
- [x] systemd auto-restart

### v2 — UI & Access Control
- [x] Settings page (⚙️): language toggle, notification toggle, whitelist
- [x] Whitelist access control with 13 rude rejection messages (EN)
- [x] i18n — all UI strings externalized (EN, RU)
- [x] /getall — all contacts status at a glance
- [x] Push notifications on status change

### v3 — UX & DB
- [x] Paginated daily log (5 sessions/page, «More →» button)
- [x] Access log — tracks unauthorized attempts, auto-blocks after 5
- [x] Whitelist management from settings
- [x] i18n expanded to 100+ keys

### v4 — Per-User Controls
- [x] Per-contact notification modes (online/offline/both/none)
- [x] Per-contact mute (1h/4h/24h with expiry)
- [x] Custom display names / aliases (✏️ Rename)
- [x] Notification context: "🟢 Dex online (was offline 3h 12m)"
- [x] CSV export — per-user session download
- [x] Per-user action submenu (log, last seen, rename, notify, mute, export, remove)
- [x] Auto-cleanup (90 days)
- [x] Self-restart from settings
- [x] Owner removal guard

### v5 — Analytics & API
- [x] Statistics: overall + per-user (total time, avg session, streak)
- [x] Hourly activity chart — 24h emoji heatmap (⬜🟨🟧🟥🟩)
- [x] REST API: `/health`, `/getall`, `/stats`, `/daily/<date>`
- [x] API auth via Bearer token or `?token=` param
- [x] Zero external deps (stdlib `http.server`)

### v6 — Multi-User Isolation
- [x] Each whitelisted user has their own workspace
- [x] `tracked_by` column for data ownership
- [x] Per-user: contacts, stats, logs filtered by who added them
- [x] Notifications go only to the user who added the contact
- [x] Admin-only settings: whitelist, access log, DB stats, restart
- [x] Child accounts: language + notification toggle only

### Planned (v7+)
- [ ] Owner super-admin panel: view all users, manage access
- [ ] Per-user notification preferences (not global)
- [ ] Web dashboard for stats
- [ ] Daily summary (configurable time)

## Technical Constraints

- **No GPU required.** Runs on CPU-only VPS.
- **Single process.** Telethon + python-telegram-bot share one asyncio event loop.
- **WAL-mode SQLite.** Fast concurrent reads, no lock contention.
- **Python 3.11+, systemd.**
- **No external REST API deps.** Pure stdlib `http.server`.

## Access Control

```
User interacts with bot
    │
    ▼
guard(update)
    │
    ├── effective_user.id == OWNER_ID → allow (admin UI)
    ├── effective_user.id in whitelist → allow (user UI, only own data)
    └── otherwise → reject: random rude message
```

## Data Ownership

Each tracked contact is owned by the whitelisted user who added it (`tracked_by` column). Sessions inherit ownership. Owner's Telethon client tracks everyone, but data is partitioned.

## Limitations

- Can only track users whose exact "last seen" time is visible in Telegram
- "last seen recently" = hidden status = Telegram doesn't send events
- Cannot track the Telethon account itself (self-status events not emitted)
