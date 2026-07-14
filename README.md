# Telegram Online Tracker

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-2CA5E0)](https://core.telegram.org/bots)

> A privacy-respecting Telegram bot for tracking when your friends and contacts come online and go offline — with exact timestamps, not vague "last seen recently" guesses.

No polling. No scraping. No bans. Just clean, event-driven MTProto magic that catches Telegram's own `UpdateUserStatus` push events.

<p align="center">
  <img src="https://img.shields.io/badge/status-active-success" alt="Status: Active">
  <img src="https://img.shields.io/badge/Telethon-event--driven-5682a3" alt="Telethon event-driven">
  <img src="https://img.shields.io/badge/SQLite-local-orange" alt="SQLite local storage">
</p>

---

## Why this exists

Let's be real — Telegram's "last seen recently" is useless when you actually want to know *when* someone was online. Was it 5 minutes ago or 3 hours? Who knows.

This bot tells you the **exact timestamp**. Not approximations. It works by listening to the same status updates a normal Telegram client receives — completely within ToS, indistinguishable from you just having the app open.

I built it because I wanted to track online patterns of people I care about without:
- Getting rate-limited into oblivion with polling loops
- Getting banned for "automated data collection"
- Dealing with vague "was online recently" nonsense

---

## What it does

- 🟢 **Catches exact online/offline timestamps** via MTProto `UpdateUserStatus` events
- 🔔 **Push notifications** — DM when a tracked contact comes online or goes offline
- 📊 **Daily session log** — see every online block for any day, paginated (5 per page)
- 📅 **Date picker** — today, yesterday, or any custom YYYY-MM-DD date
- 📡 **`/getall`** — one-tap overview of all tracked contacts
- 🛡️ **Whitelist access control** — only people you authorize can use the bot. Strangers get roasted with 13 different rude rejection messages (English, witty, not offensive)
- 🔒 **Access log** — tracks every unauthorized attempt with username, count, and timestamp. Auto-bans after 5 attempts
- 🌐 **i18n** — English and Russian interface, switchable from settings
- ⚙️ **Inline settings menu** — language, notifications, whitelist, access log — all in one place

---

## How it works (no polling, I promise)

```
You add @friend to tracking
        │
        ▼
Telethon daemon listens for UpdateUserStatus events (MTProto)
        │
        ├── UserStatusOnline  → write "went online" to SQLite + send notification
        │
        └── UserStatusOffline → write "went offline" with EXACT was_online timestamp
```

This is fundamentally different from every "online tracker" that polls with `/setdelay 60`. Those hammer Telegram's API every N seconds and get `FloodWait` errors (or worse). This bot just... listens. Like a normal client.

---

## Tech stack

| Layer | Tech | Why |
|-------|------|-----|
| **MTProto client** | [Telethon](https://github.com/LonamiWebs/Telethon) | Direct Telegram protocol access, no Bot API limitations |
| **Bot interface** | [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) | Async, battle-tested, inline keyboard support |
| **Database** | SQLite (WAL mode) | Zero-config, fast enough for personal use, single file |
| **Runtime** | Python 3.11+, systemd | Reliable, restart on crash, auto-start on boot |

Everything runs in a **single process** — Telethon and the bot share one `asyncio` event loop, so there's no session file conflicts or IPC overhead.

---

## Quick start

### Requirements

- Python 3.11 or newer
- A Telegram account (not a bot account — you need MTProto access)
- Telegram API credentials ([get them here](https://my.telegram.org/apps))
- A bot token from [@BotFather](https://t.me/BotFather)

### Setup

```bash
git clone https://github.com/tima100faces/telegram-online-tracker.git
cd telegram-online-tracker
pip install -r requirements.txt
```

Create a `.env` file:

```env
BOT_TOKEN=123456:ABCdef...
TG_API_ID=12345678
TG_API_HASH=abc123def456...
TG_PHONE_PART1=+1
TG_PHONE_PART2=5551234567
DB_PATH=./data/tracker.db
OWNER_ID=123456789
```

### Run

```bash
python bot.py
```

On first run, Telethon will ask for the auth code sent to your Telegram. After that, the session is saved and reused.

For production, use the included systemd service file or run it under `screen`/`tmux`.

### Docker

```bash
# Coming soon
```

---

## Project structure

```
telegram-online-tracker/
├── bot.py              # Main process: Telethon daemon + Telegram bot
├── i18n.py             # EN/RU string tables + 13 rude rejection messages
├── db/
│   ├── __init__.py
│   ├── core.py         # Users, sessions, daily log
│   └── settings.py     # Whitelist, access log, config
├── docs/
│   ├── ARCHITECTURE.md # Data flow, components, security model
│   └── SPEC.md         # Feature spec with planned work
├── requirements.txt
└── .env.example        # Template (copy to .env, never commit real one)
```

---

## FAQ

### How do I find my Telegram user ID?

You need this for the `OWNER_ID` in `.env`. It's a number, not your @username.

**The easiest way** (takes 10 seconds):
1. Open Telegram → search for **@userinfobot**
2. Click **Start** (or send `/start`)
3. It replies with your ID. Copy the number after `Id:`

That's it. Paste that number as `OWNER_ID` in your `.env` file.

> 💡 To whitelist other users or add them to tracking — the bot resolves @usernames automatically. You just type `@their_name`.

### Is this against Telegram's ToS?

No. This bot listens to the same `UpdateUserStatus` events any official client receives. It's indistinguishable from a normal user having Telegram open. Section 1.4 of the ToS prohibits "automated data collection" via scraping/parsing — we're not scraping anything, we're a legitimate MTProto client.

### Why not just use polling?

Polling (`getEntity status → wait → repeat`) is rate-limited and will get your account `FloodWait`-ed or banned. Event-driven listening is both legal and infinite — Telegram itself pushes the status changes to us.

### Can I track someone who has "last seen" hidden?

Yes, partially. When someone with hidden "last seen" goes offline, Telegram still sends `UserStatusOffline` with the `was_online` timestamp to connected clients. You'll get exact offline times. For online times — those only fire when the privacy setting allows it.

### What happens if a stranger messages the bot?

They get one of 13 randomly-selected rude English phrases (stuff like "Private party. You weren't invited." and "The bot finds your presence... unnecessary."). After 5 attempts they get permanently blocked with a cold "You've been blocked. Curiosity satisfied?" message. All attempts are logged.

---

## License

[GNU General Public License v3.0](LICENSE) — free software, copyleft. Use it, modify it, share it — just keep it open.

---

<p align="center">
  <sub>Built by <a href="https://github.com/tima100faces">@tima100faces</a> · Telegram: <a href="https://t.me/tgonlinetrackbot">@tgonlinetrackbot</a></sub>
</p>
