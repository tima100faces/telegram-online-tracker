#!/usr/bin/env python3
"""Telethon daemon — listens for UpdateUserStatus and logs to SQLite."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from telethon import TelegramClient, events
from telethon.tl.types import UserStatusOnline, UserStatusOffline
import db

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
PHONE = os.environ["TG_PHONE_PART1"] + os.environ["TG_PHONE_PART2"]
SESSION = Path(__file__).parent / "tg-online.session"

db.init_db()


def reload_tracked_ids() -> set[int]:
    """Reload active user IDs from DB."""
    return {u["user_id"] for u in db.get_active_users()}


async def main():
    client = TelegramClient(str(SESSION), API_ID, API_HASH)
    await client.start(phone=PHONE)

    tracked_ids = reload_tracked_ids()
    print(f"[daemon] Tracking {len(tracked_ids)} user(s)")

    @client.on(events.UserUpdate)
    async def on_status(event):
        nonlocal tracked_ids

        user_id = event.user_id
        status = event.status

        # Reload tracked list on each event (cheap — SQLite in-memory after first load)
        # Only needed when user adds/removes via bot
        if user_id not in tracked_ids:
            tracked_ids = reload_tracked_ids()
            if user_id not in tracked_ids:
                return

        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

        if isinstance(status, UserStatusOnline):
            db.start_session(user_id, now_str)
            print(f"[{now_str}] 🟢 user_id={user_id} → online")
        elif isinstance(status, UserStatusOffline):
            was_str = status.was_online.strftime("%Y-%m-%d %H:%M:%S")
            db.end_session(user_id, was_str)
            print(f"[{now_str}] ⚫ user_id={user_id} → offline (was {was_str})")

    print("[daemon] Listening for UpdateUserStatus events...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
