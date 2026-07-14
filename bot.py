#!/usr/bin/env python3
"""TG Online Tracker v2 — daemon + bot with settings, whitelist, i18n, notifications."""
import asyncio
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from telethon import TelegramClient, events
from telethon.tl.types import UserStatusOnline, UserStatusOffline
from telethon.errors import FloodWaitError

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes,
)
import db
from db import settings
from i18n import get_text as _, get_rude_message

# ── Config ──────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
PHONE = os.environ["TG_PHONE_PART1"] + os.environ["TG_PHONE_PART2"]
SESSION = Path(__file__).parent / "tg-online.session"
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))

db.init_db()

# Add owner to whitelist on startup
settings.add_to_whitelist(OWNER_ID, "owner")

# ── Conversation states ─────────────────────────────────────────────
WAIT_USERNAME = 1
WAIT_WHITELIST = 2
WAIT_DATE = 3


# ── Access guard ─────────────────────────────────────────────────────


def guard(update: Update) -> str | None:
    """Check whitelist. Returns lang if allowed, None if blocked."""
    uid = update.effective_user.id
    if uid == OWNER_ID or settings.is_whitelisted(uid):
        return settings.get_lang()
    return None


async def reject(update: Update):
    """Log attempt, check block threshold, send rude message."""
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    fname = update.effective_user.first_name or ""

    # Log attempt — returns True if now blocked (just crossed threshold)
    just_blocked = settings.log_access(uid, uname, fname)
    blocked = settings.is_blocked(uid)

    if blocked and not just_blocked:
        msg = "🚫 You've been blocked. Curiosity satisfied?"
    else:
        msg = get_rude_message()

    if update.callback_query:
        await update.callback_query.answer(msg, show_alert=True)
    elif update.message:
        await update.message.reply_text(msg)


# ── Keyboards ────────────────────────────────────────────────────────


def main_menu(lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_(lang, "btn_contacts"), callback_data="contacts")],
        [
            InlineKeyboardButton(_(lang, "btn_add"), callback_data="add"),
            InlineKeyboardButton(_(lang, "btn_getall"), callback_data="getall"),
        ],
        [
            InlineKeyboardButton(_(lang, "btn_lastseen"), callback_data="lastseen"),
            InlineKeyboardButton(_(lang, "btn_log"), callback_data="fulllog"),
        ],
        [InlineKeyboardButton(_(lang, "btn_settings"), callback_data="settings")],
    ])


def contacts_list(lang: str):
    users = db.get_active_users()
    if not users:
        return None, _(lang, "no_contacts")
    buttons = []
    for u in users:
        label = f"@{u['username']}" if u["username"] else f"ID:{u['user_id']}"
        buttons.append([
            InlineKeyboardButton(f"❌ {label}", callback_data=f"remove_{u['user_id']}")
        ])
    buttons.append([InlineKeyboardButton(_(lang, "back"), callback_data="menu")])
    return InlineKeyboardMarkup(buttons), _(lang, "contacts_title") + f" ({len(users)}):"


def user_picker(lang: str, prefix: str):
    users = db.get_active_users()
    if not users:
        return None, _(lang, "no_contacts")
    buttons = []
    for u in users:
        label = f"@{u['username']}" if u["username"] else f"ID:{u['user_id']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"{prefix}_{u['user_id']}")])
    buttons.append([InlineKeyboardButton(_(lang, "back"), callback_data="menu")])
    return InlineKeyboardMarkup(buttons), _(lang, "select_contact")


def date_picker(lang: str, user_id: int):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_(lang, "date_today"), callback_data=f"date_{user_id}_{today}")],
        [InlineKeyboardButton(_(lang, "date_yesterday"), callback_data=f"date_{user_id}_{yesterday}")],
        [InlineKeyboardButton(_(lang, "date_custom"), callback_data=f"datepick_{user_id}")],
        [InlineKeyboardButton(_(lang, "back"), callback_data="fulllog")],
    ])


def settings_menu(lang: str):
    notif = _(lang, "notifications_on") if settings.get_notifications_enabled() else _(lang, "notifications_off")
    whitelist_count = len(settings.get_whitelist())
    access_log = settings.get_access_log()
    log_total = len(access_log)
    blocked = sum(1 for a in access_log if a["blocked"])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_(lang, "settings_language", lang_name="RU" if lang == "ru" else "EN"), callback_data="toggle_lang")],
        [InlineKeyboardButton(_(lang, "notification_settings", state=notif), callback_data="toggle_notifications")],
        [InlineKeyboardButton(_(lang, "settings_whitelist", count=whitelist_count), callback_data="whitelist_menu")],
        [InlineKeyboardButton(_(lang, "btn_access_log", total=log_total), callback_data="access_log")],
        [InlineKeyboardButton(_(lang, "back"), callback_data="menu")],
    ])


def whitelist_menu(lang: str):
    wl = settings.get_whitelist()
    buttons = []
    for w in wl:
        label = f"@{w['username']}" if w["username"] else f"ID:{w['user_id']}"
        if w["user_id"] != OWNER_ID:
            buttons.append([InlineKeyboardButton(f"❌ {label}", callback_data=f"wldel_{w['user_id']}")])
        else:
            buttons.append([InlineKeyboardButton(f"👑 {label}", callback_data="noop")])
    if not buttons:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(_(lang, "add"), callback_data="wladd")],
            [InlineKeyboardButton(_(lang, "back"), callback_data="settings")],
        ]), _(lang, "whitelist_empty")
    buttons.append([InlineKeyboardButton(_(lang, "settings_add_whitelist"), callback_data="wladd")])
    buttons.append([InlineKeyboardButton(_(lang, "back"), callback_data="settings")])
    return InlineKeyboardMarkup(buttons), _(lang, "settings_whitelist", count=len(wl))


# ── Format helpers ───────────────────────────────────────────────────


def fmt_last_seen(lang: str, username: str, ts: str | None) -> str:
    if ts is None:
        return _(lang, "no_data", username=username)
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    delta = datetime.utcnow() - dt
    if delta.days >= 365:
        return _(lang, "last_seen_years", username=username, n=delta.days // 365, date=dt.strftime("%d.%m.%Y"))
    elif delta.days >= 30:
        return _(lang, "last_seen_months", username=username, n=delta.days // 30, date=dt.strftime("%d.%m.%Y"))
    elif delta.days >= 1:
        return _(lang, "last_seen_days", username=username, n=delta.days, date=dt.strftime("%d.%m %H:%M"))
    elif delta.seconds >= 3600:
        return _(lang, "last_seen_hours", username=username, n=delta.seconds // 3600, time=dt.strftime("%H:%M"))
    elif delta.seconds >= 60:
        return _(lang, "last_seen_minutes", username=username, n=delta.seconds // 60)
    return _(lang, "last_seen_just_now", username=username)


def fmt_daily_log_for_user(lang: str, user_id: int, username: str, date_str: str, page: int = 0) -> tuple[str, int]:
    """Return (text, total_pages) for paginated daily log.
    page 0 = first 5 sessions, page 1 = next 5, etc.
    Sessions count is 5 per page. Returns total_pages = ceil(total / 5).
    """
    PAGE_SIZE = 5
    sessions = db.get_daily_log(user_id, date_str)
    total = len(sessions)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start = page * PAGE_SIZE
    chunk = sessions[start:start + PAGE_SIZE]

    if not chunk:
        return _(lang, "no_log", username=username, date=date_str), total_pages

    lines = [_(lang, "daily_log_title", username=username, date=date_str)]
    if total > PAGE_SIZE:
        lines.append(_(lang, "log_page_indicator", page=page + 1, total=total_pages, sessions=total))

    for s in chunk:
        on = s["went_online"][11:16]
        if s["went_offline"]:
            off = s["went_offline"][11:16]
            lines.append(_(lang, "daily_log_entry", on=on, off=off))
        else:
            lines.append(_(lang, "daily_log_online", on=on))

    return "\n".join(lines), total_pages


def fmt_getall(lang: str) -> str:
    users = db.get_active_users()
    if not users:
        return _(lang, "no_contacts")
    lines = [_(lang, "getall_title")]
    for u in users:
        name = u["username"] or str(u["user_id"])
        if db.is_online_now(u["user_id"]):
            lines.append(_(lang, "getall_online", username=name))
        else:
            ts = db.get_last_seen(u["user_id"])
            if ts:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                delta = datetime.utcnow() - dt
                if delta.days > 0:
                    when = f"{delta.days}d ago"
                elif delta.seconds >= 3600:
                    when = f"{delta.seconds // 3600}h ago"
                else:
                    when = f"{max(delta.seconds // 60, 1)}m ago"
                lines.append(_(lang, "getall_offline", username=name, when=when))
            else:
                lines.append(_(lang, "getall_no_data", username=name))
    return "\n".join(lines)


# ── Handlers ─────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = guard(update)
    if not lang:
        await reject(update)
        return
    await update.message.reply_text(_(lang, "menu_title"), reply_markup=main_menu(lang))


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = guard(update)
    if not lang:
        await reject(update)
        return
    await query.answer()
    data = query.data

    # ── Navigation ──
    if data == "menu":
        await query.edit_message_text(_(lang, "menu_title"), reply_markup=main_menu(lang))

    elif data == "contacts":
        kb, text = contacts_list(lang)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("remove_"):
        user_id = int(data.split("_")[1])
        user = db.get_user(user_id)
        db.remove_user(user_id)
        name = f"@{user['username']}" if user and user["username"] else f"ID:{user_id}"
        kb, __ = contacts_list(lang)
        text = _(lang, "remove_success", name=name)
        if not kb:
            text += "\n" + _(lang, "remove_empty", name=name)
        await query.edit_message_text(text, reply_markup=kb or main_menu(lang))

    # ── Last seen ──
    elif data == "lastseen":
        kb, text = user_picker(lang, "ls")
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("ls_"):
        user_id = int(data.split("_")[1])
        user = db.get_user(user_id)
        name = user["username"] if user else str(user_id)
        ts = db.get_last_seen(user_id)
        await query.edit_message_text(
            fmt_last_seen(lang, name, ts),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data="lastseen")]
            ]),
        )

    # ── Full log ──
    elif data == "fulllog":
        kb, text = user_picker(lang, "log")
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("log_"):
        parts = data.split("_")
        if len(parts) >= 3:
            # log_<user_id>_<date>[_<page>]
            user_id = int(parts[1])
            date_str = parts[2]
            page = int(parts[3]) if len(parts) >= 4 else 0
            user = db.get_user(user_id)
            name = user["username"] if user else str(user_id)
            text, total_pages = fmt_daily_log_for_user(lang, user_id, name, date_str, page)
            btns = [[InlineKeyboardButton(_(lang, "back"), callback_data=f"log_{user_id}")]]
            if page + 1 < total_pages:
                btns.insert(0, [InlineKeyboardButton(
                    _(lang, "btn_more"), callback_data=f"log_{user_id}_{date_str}_{page + 1}"
                )])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btns))
        else:
            # log_<user_id> — show date picker
            user_id = int(parts[1])
            await query.edit_message_text(
                _(lang, "date_select"),
                reply_markup=date_picker(lang, user_id),
            )

    elif data.startswith("date_"):
        # date_<user_id>_<date> — show page 0 for that date
        parts = data.split("_")
        user_id, date_str = int(parts[1]), parts[2]
        user = db.get_user(user_id)
        name = user["username"] if user else str(user_id)
        text, total_pages = fmt_daily_log_for_user(lang, user_id, name, date_str, 0)
        btns = [[InlineKeyboardButton(_(lang, "back"), callback_data=f"log_{user_id}")]]
        if total_pages > 1:
            btns.insert(0, [InlineKeyboardButton(
                _(lang, "btn_more"), callback_data=f"log_{user_id}_{date_str}_1"
            )])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("datepick_"):
        user_id = int(data.split("_")[1])
        context.user_data["datepick_for"] = user_id
        await query.edit_message_text(
            _(lang, "date_prompt"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "cancel"), callback_data="menu")]
            ]),
        )
        return WAIT_DATE

    # ── Getall ──
    elif data == "getall":
        await query.edit_message_text(
            fmt_getall(lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data="menu")]
            ]),
        )

    # ── Add user ──
    elif data == "add":
        await query.edit_message_text(
            _(lang, "add_prompt"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "cancel"), callback_data="menu")]
            ]),
        )
        return WAIT_USERNAME

    # ── Settings ──
    elif data == "settings":
        await query.edit_message_text(_(lang, "settings_title"), reply_markup=settings_menu(lang))

    elif data == "toggle_lang":
        new_lang = "en" if lang == "ru" else "ru"
        settings.set_lang(new_lang)
        old_msg = query.message
        lang = new_lang
        await query.edit_message_text(_(lang, "settings_title"), reply_markup=settings_menu(lang))

    elif data == "toggle_notifications":
        current = settings.get_notifications_enabled()
        settings.set_notifications_enabled(not current)
        await query.edit_message_text(_(lang, "settings_title"), reply_markup=settings_menu(lang))

    elif data == "whitelist_menu":
        kb, text = whitelist_menu(lang)
        await query.edit_message_text(text, reply_markup=kb)

    elif data == "wladd":
        await query.edit_message_text(
            _(lang, "whitelist_prompt"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "cancel"), callback_data="whitelist_menu")]
            ]),
        )
        return WAIT_WHITELIST

    elif data.startswith("wldel_"):
        user_id = int(data.split("_")[1])
        if user_id != OWNER_ID:
            settings.remove_from_whitelist(user_id)
        kb, text = whitelist_menu(lang)
        await query.edit_message_text(text, reply_markup=kb)

    elif data == "noop":
        await query.answer("👑 Owner cannot be removed", show_alert=True)

    # ── Access log ──
    elif data == "access_log":
        kb, text = access_log_view(lang)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("unblock_"):
        user_id = int(data.split("_")[1])
        settings.unblock_user(user_id)
        kb, text = access_log_view(lang)
        await query.edit_message_text(text, reply_markup=kb)

    elif data == "clearlog":
        settings.clear_access_log()
        await query.edit_message_text(
            _(lang, "cleared_log"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data="settings")]
            ]),
        )


def access_log_view(lang: str):
    """Build access log submenu."""
    entries = settings.get_access_log()
    if not entries:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(_(lang, "back"), callback_data="settings")]
        ]), _(lang, "access_log_empty")

    total = len(entries)
    blocked = sum(1 for e in entries if e["blocked"])
    lines = [_(lang, "access_log_title", total=total, blocked=blocked), ""]

    buttons = []
    for e in entries:
        username = e["username"] or str(e["user_id"])
        last_str = str(e["last_attempt"])
        last_short = last_str[5:16] if len(last_str) >= 16 else last_str[:16]
        if e["blocked"]:
            lines.append(_(lang, "access_log_entry_blocked", username=username, count=e["attempt_count"], last=last_short))
            buttons.append([InlineKeyboardButton(
                f"🔓 Unblock @{username}", callback_data=f"unblock_{e['user_id']}"
            )])
        else:
            lines.append(_(lang, "access_log_entry", username=username, count=e["attempt_count"], last=last_short))

    buttons.append([InlineKeyboardButton(_(lang, "btn_clear_log"), callback_data="clearlog")])
    buttons.append([InlineKeyboardButton(_(lang, "back"), callback_data="settings")])
    return InlineKeyboardMarkup(buttons), "\n".join(lines)


async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = guard(update)
    if not lang:
        return ConversationHandler.END

    username = update.message.text.strip().lstrip("@")
    client: TelegramClient = context.bot_data["telethon_client"]

    try:
        entity = await asyncio.wait_for(client.get_entity(username), timeout=10)
    except asyncio.TimeoutError:
        await update.message.reply_text(_(lang, "add_timeout", username=username),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_(lang, "back"), callback_data="menu")]]))
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(_(lang, "add_not_found", username=username),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_(lang, "back"), callback_data="menu")]]))
        return ConversationHandler.END
    except FloodWaitError as e:
        await update.message.reply_text(_(lang, "add_flood", seconds=e.seconds),
            reply_markup=main_menu(lang))
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(_(lang, "add_error", error=str(e)),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_(lang, "back"), callback_data="menu")]]))
        return ConversationHandler.END

    first = getattr(entity, "first_name", "") or ""
    db.add_user(entity.id, username, first)
    settings.unblock_user(entity.id)
    await update.message.reply_text(
        _(lang, "add_success", username=username),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(_(lang, "to_menu"), callback_data="menu")]
        ]),
    )
    return ConversationHandler.END


async def receive_whitelist_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = guard(update)
    if not lang:
        return ConversationHandler.END

    raw = update.message.text.strip().lstrip("@")
    client: TelegramClient = context.bot_data["telethon_client"]

    try:
        entity = await asyncio.wait_for(client.get_entity(raw), timeout=10)
        uid = entity.id
        uname = getattr(entity, "username", "") or raw
    except Exception:
        await update.message.reply_text(
            _(lang, "add_not_found", username=raw),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_(lang, "back"), callback_data="whitelist_menu")]]))
        return ConversationHandler.END

    settings.add_to_whitelist(uid, uname, added_by=update.effective_user.id)
    settings.unblock_user(uid)
    kb, text = whitelist_menu(lang)
    await update.message.reply_text(text, reply_markup=kb)
    return ConversationHandler.END


async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = guard(update)
    if not lang:
        return ConversationHandler.END

    date_str = update.message.text.strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(_(lang, "date_invalid"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_(lang, "back"), callback_data="menu")]]))
        return ConversationHandler.END

    user_id = context.user_data.get("datepick_for")
    if user_id:
        user = db.get_user(user_id)
        name = user["username"] if user else str(user_id)
        text, total_pages = fmt_daily_log_for_user(lang, user_id, name, date_str, 0)
        btns = [[InlineKeyboardButton(_(lang, "back"), callback_data=f"log_{user_id}")]]
        if total_pages > 1:
            btns.insert(0, [InlineKeyboardButton(
                _(lang, "btn_more"), callback_data=f"log_{user_id}_{date_str}_1"
            )])
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(btns))
    return ConversationHandler.END


# ── Telethon event handler ───────────────────────────────────────────


def make_status_handler(bot_app):
    """Event handler that logs sessions and sends notifications."""
    tracked_ids = {u["user_id"] for u in db.get_active_users()}

    async def on_status(event):
        nonlocal tracked_ids
        user_id = event.user_id
        status = event.status

        if user_id not in tracked_ids:
            tracked_ids = {u["user_id"] for u in db.get_active_users()}
            if user_id not in tracked_ids:
                return

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if isinstance(status, UserStatusOnline):
            db.start_session(user_id, now_str)
            print(f"[{now_str}] 🟢 user_id={user_id} → online")
            await _notify(bot_app, user_id, "online", now_str)
        elif isinstance(status, UserStatusOffline):
            was_str = status.was_online.strftime("%Y-%m-%d %H:%M:%S")
            db.end_session(user_id, was_str)
            print(f"[{now_str}] ⚫ user_id={user_id} → offline (was {was_str})")
            await _notify(bot_app, user_id, "offline", was_str)

    return on_status


async def _notify(app, user_id: int, event_type: str, ts: str):
    """Send notification to all whitelisted users."""
    if not settings.get_notifications_enabled():
        return

    user = db.get_user(user_id)
    name = user["username"] if user else str(user_id)

    whitelisted = settings.get_whitelist()
    for w in whitelisted:
        lang = settings.get_lang()
        if event_type == "online":
            text = _(lang, "notification_online", username=name)
        else:
            text = _(lang, "notification_offline", username=name, time=ts[11:16])
        try:
            await app.bot.send_message(w["user_id"], text)
        except Exception:
            pass  # user might have blocked the bot


# ── Main ─────────────────────────────────────────────────────────────


async def main():
    # Start Telethon
    telethon = TelegramClient(str(SESSION), API_ID, API_HASH)
    await telethon.connect()
    if not await telethon.is_user_authorized():
        print("[main] Session invalid, requesting code...")
        result = await telethon.send_code_request(phone=PHONE)
        code = os.getenv("TG_AUTH_CODE", "")
        if not code:
            raise RuntimeError("Session expired. Set TG_AUTH_CODE in .env and restart.")
        await telethon.sign_in(phone=PHONE, code=code, phone_code_hash=result.phone_code_hash)
        print("[main] Re-authenticated.")

    # Build bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["telethon_client"] = telethon

    telethon.add_event_handler(make_status_handler(app), events.UserUpdate)
    print("[main] Telethon connected, listening...")

    # Conversation handlers
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^add$")],
        states={WAIT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)]},
        fallbacks=[CallbackQueryHandler(menu_callback, pattern="^menu$")],
    )
    wl_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^wladd$")],
        states={WAIT_WHITELIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_whitelist_user)]},
        fallbacks=[CallbackQueryHandler(menu_callback, pattern="^whitelist_menu$")],
    )
    date_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^datepick_")],
        states={WAIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date)]},
        fallbacks=[CallbackQueryHandler(menu_callback, pattern="^menu$")],
    )

    default_pattern = (
        "^(menu|contacts|lastseen|fulllog|getall|settings"
        "|toggle_lang|toggle_notifications|whitelist_menu|noop"
        "|access_log|clearlog"
        "|remove_\\d+|ls_\\d+|log_\\d+|log_\\d+_\\S+|date_\\d+_\\S+|wldel_\\d+|unblock_\\d+)$"
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=default_pattern))
    app.add_handler(add_conv)
    app.add_handler(wl_conv)
    app.add_handler(date_conv)

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print(f"[main] Bot polling started. @{app.bot.username}")

    try:
        await telethon.run_until_disconnected()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
