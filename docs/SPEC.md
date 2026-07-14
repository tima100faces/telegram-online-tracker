# Specification — TG Online Tracker v2

## Objective

Track exact Telegram online/offline timestamps for specified users. Private bot with whitelist access control and i18n support.

## Core Principles

- **Event-driven, not polling.** Listens for `UpdateUserStatus` from MTProto — no periodic requests, no flood risks.
- **Exact timestamps.** `was_online` captured from `UserStatusOffline` event, not "recently" approximations.
- **Push notifications.** DM when a tracked contact changes status (configurable).
- **Whitelist-only.** Only authorized users can interact. Owner always bypasses.

## Features

### v1 (Implemented)
- [x] Event-driven online/offline detection
- [x] SQLite session storage
- [x] Inline-menu bot
- [x] Add/remove tracked users
- [x] Last seen view
- [x] Daily session log
- [x] systemd auto-restart

### v2 (Implemented)
- [x] Settings page (⚙️)
  - Language toggle (RU ↔ EN)
  - Notification toggle (on/off)
  - Whitelist management (add/remove)
- [x] Whitelist access control
  - 13 rude rejection messages per language
  - Random selection via `random.choice()`
- [x] i18n module — all UI strings externalized
- [x] `/getall` — all contacts status at a glance
- [x] Date selector — log for today, yesterday, or custom date
- [x] Push notifications on status change
- [x] Modular code: `db/core.py`, `db/settings.py`, `i18n.py`

### Planned (v3)
- [ ] Weekly/monthly statistics (sessions per day, avg session length, heatmap)
- [ ] Custom display names for tracked contacts
- [ ] Online streak counter
- [ ] Export data (JSON/CSV)
- [ ] Mute specific user (stop notifications for one contact)
- [ ] `/stats @user 7d` — full weekly report

## Technical Constraints

- **No GPU required.** Runs on CPU-only VPS.
- **Single process.** Telethon + python-telegram-bot share one asyncio event loop (same MTProto session).
- **WAL-mode SQLite.** Fast concurrent reads, no lock contention.
- **Python 3.11+, systemd.**

## Access Control Logic

```
User interacts with bot
    │
    ▼
guard(update)
    │
    ├── effective_user.id == OWNER_ID → allow, lang = settings.get_lang()
    ├── effective_user.id in whitelist → allow, lang = settings.get_lang()
    └── otherwise → reject: random rude message, no functionality
```

## Rude Messages

13 variants per language. Tone: rude, witty, humorous — but not insulting or profane. Examples:

**EN:**
- "Private party. You weren't invited."
- "The bot looked at you and looked away. Nothing personal."
- "Sorry, you didn't pass the vibe check. The bot has standards."

**RU:**
- "Сорян, частная вечеринка. У тебя приглашения нет."
- "Бот посмотрел на тебя и отвернулся. Ничего личного."
- "Извини, ты не проходишь фейсконтроль. У бота свои стандарты."
