# Architecture

## Overview

TG Online Tracker runs as a single process combining two asyncio components:

```
┌─────────────────────────────────────────────┐
│              Telegram Servers               │
│    ┌──────────┐          ┌──────────┐       │
│    │  MTProto │          │  Bot API │       │
│    └────┬─────┘          └────┬─────┘       │
└─────────┼─────────────────────┼─────────────┘
          │                     │
    ┌─────▼─────────────────────▼─────────────┐
    │           bot.py (single process)        │
    │  ┌──────────────┐  ┌───────────────┐    │
    │  │   Telethon    │  │ python-tg-bot │    │
    │  │   (events)    │  │   (inlines)   │    │
    │  └──────┬────────┘  └───────┬───────┘    │
    │         │                   │            │
    │         ▼                   ▼            │
    │  ┌──────────────────────────────────┐    │
    │  │            SQLite (WAL)          │    │
    │  │  ┌────────────┐ ┌─────────────┐  │    │
    │  │  │  sessions   │ │  settings   │  │    │
    │  │  └────────────┘ └─────────────┘  │    │
    │  └──────────────────────────────────┘    │
    └──────────────────────────────────────────┘
```

## Components

### 1. Telethon Daemon

- Connects to MTProto with user account session
- Listens for `events.UserUpdate` (push, not polling)
- On `UserStatusOnline`: writes `start_session` to DB, sends notification
- On `UserStatusOffline`: writes `end_session` with exact `was_online` timestamp, sends notification

### 2. Telegram Bot (python-telegram-bot)

- Inline keyboard interface
- Handlers: `/start`, callback queries, conversation states
- Whitelist guard on every interaction

### 3. Database (SQLite, WAL mode)

**Tables:**

`tracked_users` — users being monitored:
- `user_id` (PK), `username`, `first_name`, `added_at`, `active`

`online_sessions` — detected online periods:
- `user_id` → `tracked_users`, `went_online`, `went_offline` (nullable if still online)

`settings` — key-value config:
- `key` (PK), `value` — stores `lang`, `notifications`

`whitelist` — authorized bot users:
- `user_id` (PK), `username`, `added_by`, `added_at`

### 4. i18n

`i18n.py` contains two dictionaries (`ru`, `en`) with all UI strings, plus rude rejection message pools (13 messages each language). Language is per-whitelist-user, stored in `settings` table.

## Data Flow

```
User opens Telegram
        │
        ▼
Telegram pushes UpdateUserStatus
        │
        ▼
Telethon catches event
        │
        ├──► db.start_session(user_id, timestamp)
        │
        └──► bot.send_message(whitelist_users, notification)
```

## Security

- Every handler calls `guard(update)` — checks `effective_user.id` against whitelist
- Owner ID always bypasses whitelist
- Unauthorized users get a random rude message and no functionality
- Bot token and MTProto credentials in `.env` (not committed)
