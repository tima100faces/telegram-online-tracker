# Reddit post — r/Python (technical deep-dive)

---

**Title:** How I built a Telegram online tracker using MTProto events instead of polling (Telethon + asyncio + stdlib API)

---

**Body:**

Most Telegram "online trackers" poll `getEntity` every N seconds. This is slow, rate-limited, and gets your account FloodWait-ed or banned. I wanted to know the **exact timestamps** my contacts come online — not "last seen recently" guesses.

**The key insight:** Telegram clients receive `UpdateUserStatus` push events via MTProto. You don't need to ask — Telegram tells you when a contact changes status. This is exactly how the official client works.

## Architecture

Single Python process, single asyncio event loop:

```
Telethon (MTProto) ──→ UpdateUserStatus events ──→ SQLite session log
                                                      │
python-telegram-bot (Bot API) ←── inline keyboard UI ─┘
                                                      │
http.server (stdlib)          ←── REST API: /stats   ─┘
```

No message queues, no workers, no external deps for the API. Just `asyncio.gather()` with three coroutines sharing one SQLite connection (WAL mode, no lock contention).

## Why MTProto events beat polling

```python
# Polling (bad):
while True:
    status = await client.get_entity(user)  # API call
    if status.changed:
        log(status)
    await asyncio.sleep(60)  # blind wait, misses changes

# Event-driven (good):
@client.on(events.UserUpdate)
async def handler(event):
    if isinstance(event.status, UserStatusOnline):
        db.start_session(event.user_id)     # exact timestamp
    elif isinstance(event.status, UserStatusOffline):
        db.end_session(event.user_id)       # includes was_online
```

Zero API calls. Zero rate limits. Telegram pushes the data to us.

## Multi-user isolation

Each whitelisted user has their own workspace — they see only contacts THEY added, get only THEIR notifications. The Telethon client (one account) tracks everyone, but SQLite partitions data by `tracked_by`:

```python
# DB schema
tracked_users: user_id, tracked_by, display_name, notify_mode, mute_until
online_sessions: user_id, tracked_by, went_online, went_offline

# Handler — iterate all tracking users per status event
trackers = {u["tracked_by"] for u in get_active_users() if u["user_id"] == event.user_id}
for tu in trackers:
    start_session(user_id, tu)   # one session row per tracker
    await bot.send_message(tu, notification)  # notify only the relevant user
```

## REST API — zero dependencies

The API is pure `http.server` from stdlib. Token auth via Bearer header or `?token=` query param. Binding to localhost only:

```python
class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if token != API_TOKEN:
            self.send_error(403)
            return
        # Route: /stats/<user_id>, /daily/<date>, /health
```

No Flask, no FastAPI, no aiohttp. The entire API handler is ~80 lines.

## Stats engine

Per-user stats are computed from raw session rows in SQLite:
- Total sessions, total online time, average session, longest session
- Streak: consecutive days with at least one session
- Hourly activity: 24-bar heatmap with emoji scale (⬜🟨🟧🟥🟩)

```python
def get_hourly_activity(user_id, days=7):
    rows = conn.execute("""
        SELECT CAST(strftime('%H', went_online) AS INT) AS h, COUNT(*) AS c
        FROM online_sessions
        WHERE user_id=? AND went_online >= date('now', ?)
        GROUP BY h
    """, (user_id, f'-{days} days')).fetchall()
    return [(h, c) for h, c in rows]
```

## Limitations (honest)

- Can only track users whose exact "last seen" time is visible (hidden status = no MTProto events)
- Cannot track the account the Telethon client is logged into (no self-status events)
- No web UI — inline keyboard only

**Repo:** https://github.com/tima100faces/telegram-online-tracker

**Stack:** Python 3.11, Telethon, python-telegram-bot, SQLite (WAL), stdlib http.server

---

Curious: has anyone else built tools on top of MTProto events? What pitfalls did you hit?

---

## Posting instructions:

1. Go to https://www.reddit.com/r/Python/submit
2. Paste title and body
3. Flair: "Discussion" or "Showcase"
4. Optional: link to repo in a comment
5. Do NOT post screenshots — r/Python prefers code blocks over images
