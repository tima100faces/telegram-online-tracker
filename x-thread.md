# X / Twitter thread — dev community

---

**Tweet 1 (hook):**
Most Telegram "online trackers" poll every 60 seconds and get banned.
I built one that doesn't poll at all — it listens for MTProto push events instead.
Exact timestamps, zero rate limits.

Stack: Telethon + python-telegram-bot + SQLite
Repo ↓
🧵

**Tweet 2 (how it works):**
The trick: Telegram clients receive UpdateUserStatus events via MTProto.
The official app doesn't poll — Telegram pushes status changes.
Same data, zero API calls.

Online → timestamp → SQLite
Offline → close session + notification
🧵

**Tweet 3 (multi-user):**
Friends can use it too. Each whitelisted user has their own workspace:
— only THEIR contacts
— only THEIR stats
— only THEIR notifications

One Telethon account tracks everyone, SQLite partitions by tracked_by column.
🧵

**Tweet 4 (features):**
— Per-user stats with 24h activity heatmap
— Custom display names
— Mute per contact (1h/4h/24h)
— CSV export
— REST API (stdlib, zero deps)
— EN/RU i18n

[Screenshot: stats]
🧵

**Tweet 5 (repo):**
Open source, GPL-3.0
Runs on a $5 VPS, single process

github.com/tima100faces/telegram-online-tracker

[Screenshot: main menu]

#python #telegram #opensource #bot

---

## Posting instructions:

1. Open X/Twitter, start a thread
2. Tweet 1 = first tweet, then reply to yourself with each numbered tweet
3. Attach screenshots to tweets 4 and 5
4. Add link to repo in tweet 5

Character counts are under 280 — checked.
