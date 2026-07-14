# Architecture

## Overview

TG Online Tracker runs as a single process combining three asyncio components:

```
┌─────────────────────────────────────────────────────┐
│                  Telegram Servers                   │
│    ┌──────────┐          ┌──────────┐              │
│    │  MTProto │          │  Bot API │              │
│    └────┬─────┘          └────┬─────┘              │
└─────────┼─────────────────────┼────────────────────┘
          │                     │
    ┌─────▼─────────────────────▼────────────────────┐
    │           bot.py (single process)               │
    │  ┌──────────┐  ┌───────────┐  ┌──────────────┐ │
    │  │ Telethon  │  │ ptb Bot   │  │ REST API     │ │
    │  │ (events)  │  │ (inlines) │  │ (stdlib)     │ │
    │  └─────┬─────┘  └─────┬─────┘  └──────┬───────┘ │
    │        │              │               │         │
    │        ▼              ▼               ▼         │
    │  ┌──────────────────────────────────────────┐   │
    │  │            SQLite (WAL)                  │   │
    │  │  tracked_users  online_sessions  settings│   │
    │  │  whitelist      access_log                │   │
    │  └──────────────────────────────────────────┘   │
    └────────────────────────────────────────────────┘
```

## Components

### 1. Telethon Listener

- Connects to MTProto with user account session
- Listens for `events.UserUpdate` (push, not polling)
- On `UserStatusOnline`: iterates all tracking users, writes `start_session(user_id, tracked_by)` per tracker
- On `UserStatusOffline`: closes sessions per tracker, sends notifications with session duration
- **Multi-user aware:** one event → N sessions (one per tracking bot user)

### 2. Telegram Bot (python-telegram-bot)

- Inline keyboard interface with conversation handlers
- Handlers: `/start`, callback queries, rename/add/date input
- `guard(update)` on every interaction — whitelist + owner check
- All DB calls parameterized with `tracked_by = effective_user.id`
- Admin-only UI elements (whitelist, access log, DB stats, restart) hidden for non-owners

### 3. REST API (stdlib `http.server`)

- Runs on `127.0.0.1:8091`
- Auth: `Authorization: Bearer <API_TOKEN>` header (exact match); unset → 401
- Endpoints: `/health` (no auth), `/getall`, `/stats/<id>`, `/stats`, `/daily/<date>`
- Zero external dependencies

### 4. Database (SQLite, WAL mode)

**Tables:**

`tracked_users` — contacts being monitored:
- `user_id` (PK), `username`, `first_name`, `added_at`, `active`
- `display_name` — custom alias set via Rename
- `notify_mode` — `online` / `offline` / `both` / `none`
- `mute_until` — timestamp, auto-expires
- `tracked_by` — which bot user added this contact (v6 multi-user)

`online_sessions` — detected online periods:
- `id` (PK), `user_id`, `went_online`, `went_offline` (nullable if still online)
- `tracked_by` — which bot user's tracking generated this session

`settings` — global key-value config:
- `key` (PK), `value` — stores `lang` (global fallback), `lang:<user_id>` (per-user), `notifications`, `open_mode`

`whitelist` — authorized bot users:
- `user_id` (PK), `username`, `added_by`, `added_at`

`access_log` — unauthorized attempt tracking:
- `user_id` (PK), `username`, `first_name`, `attempt_count`, `last_attempt`, `blocked`

### 5. i18n

`i18n.py` contains dictionaries (`ru`, `en`) with 118 UI strings, plus 13 rude rejection messages. Language is per-user via `lang:<user_id>` keys, falling back to a global `lang` key then `"en"`.

## Data Flow

```
User comes online
        │
        ▼
Telegram pushes UpdateUserStatus
        │
        ▼
Telethon catches event
        │
        ├──► Get all trackers: SELECT tracked_by FROM tracked_users WHERE user_id=?
        │
        ├──► For each tracker: start_session(user_id, tracked_by)
        │
        └──► For each tracker: send notification if mode matches + not muted
```

## Multi-User Isolation (v6)

```
Bot user A (whitelisted)            Bot user B (whitelisted)
    │                                      │
    ├─ Adds @friend1                       ├─ Adds @friend2
    │  (tracked_by=A)                       │  (tracked_by=B)
    │                                      │
    ├─ Sees: @friend1 only                ├─ Sees: @friend2 only
    ├─ Gets: @friend1 notifications       ├─ Gets: @friend2 notifications
    └─ Stats: @friend1 data only          └─ Stats: @friend2 data only

Telethon (owner's account) tracks ALL contacts
Sessions stored per tracked_by
Notifications routed to tracking user
```

## Security

- Every handler calls `guard(update)` — checks `effective_user.id` against whitelist + OWNER_ID
- Owner always bypasses, gets admin UI
- Unauthorized users get random rude message, logged, auto-blocked after 5 attempts
- Bot token and MTProto credentials in `.env` (not committed)
- API bound to localhost only, requires token auth
