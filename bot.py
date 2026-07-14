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
WAIT_RENAME = 4


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
            InlineKeyboardButton(_(lang, "btn_stats"), callback_data="stats"),
        ],
        [InlineKeyboardButton(_(lang, "btn_settings"), callback_data="settings")],
    ])


def contacts_list(lang: str, tracked_by: int):
    users = db.get_active_users(tracked_by)
    if not users:
        return None, _(lang, "no_contacts")
    buttons = []
    for u in users:
        label = u["display_name"] or f"@{u['username']}" if u["username"] else f"ID:{u['user_id']}"
        buttons.append([
            InlineKeyboardButton(f"👤 {label}", callback_data=f"user_{u['user_id']}")
        ])
    buttons.append([InlineKeyboardButton(_(lang, "back"), callback_data="menu")])
    return InlineKeyboardMarkup(buttons), _(lang, "contacts_title") + f" ({len(users)}):"


def user_picker(lang: str, prefix: str, tracked_by: int):
    users = db.get_active_users(tracked_by)
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


def settings_menu(lang: str, current_uid: int = 0):
    notif = _(lang, "notifications_on") if settings.get_notifications_enabled() else _(lang, "notifications_off")
    kb = [
        [InlineKeyboardButton(_(lang, "settings_language", lang_name="RU" if lang == "ru" else "EN"), callback_data="toggle_lang")],
        [InlineKeyboardButton(_(lang, "notification_settings", state=notif), callback_data="toggle_notifications")],
    ]
    # Admin-only: whitelist, access log, DB stats, restart
    if current_uid == OWNER_ID:
        wl_count = len(settings.get_whitelist())
        al_count = len(settings.get_access_log())
        kb.append([InlineKeyboardButton(_(lang, "settings_whitelist", count=wl_count), callback_data="whitelist_menu")])
        kb.append([InlineKeyboardButton(_(lang, "btn_access_log", total=al_count), callback_data="access_log")])
        kb.append([InlineKeyboardButton(_(lang, "db_stats_title"), callback_data="db_stats")])
        kb.append([InlineKeyboardButton(_(lang, "btn_restart"), callback_data="restart_confirm")])
    kb.append([InlineKeyboardButton(_(lang, "back"), callback_data="menu")])
    return InlineKeyboardMarkup(kb)


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


def display(user_id: int, tracked_by: int | None = None) -> str:
    """Resolve best display name: custom > username > user_id."""
    user = db.get_user(user_id, tracked_by)
    if not user:
        return str(user_id)
    return user["display_name"] or user["username"] or str(user_id)


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


def fmt_daily_log_for_user(lang: str, user_id: int, username: str, date_str: str, page: int = 0, tracked_by: int | None = None) -> tuple[str, int]:
    """Return (text, total_pages) for paginated daily log.
    page 0 = first 5 sessions, page 1 = next 5, etc.
    Sessions count is 5 per page. Returns total_pages = ceil(total / 5).
    """
    PAGE_SIZE = 5
    sessions = db.get_daily_log(user_id, date_str, tracked_by=tracked_by)
    if isinstance(sessions, tuple):
        sessions = sessions[0]
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


def fmt_getall(lang: str, tracked_by: int) -> str:
    users = db.get_active_users(tracked_by)
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


def user_menu_view(lang: str, user_id: int, tracked_by: int) -> tuple[InlineKeyboardMarkup, str]:
    """Build the per-user action submenu."""
    user = db.get_user(user_id, tracked_by)
    if not user:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(_(lang, "back"), callback_data="contacts")]
        ]), "User not found."
    name = display(user_id)
    mode = db.get_notify_mode(user_id, tracked_by)
    mode_name = _(lang, f"notify_{mode}")
    muted = db.is_muted(user_id, tracked_by)
    text = _(lang, "user_menu_title", username=name)
    kb = [
        [InlineKeyboardButton(_(lang, "btn_user_log"), callback_data=f"log_{user_id}")],
        [InlineKeyboardButton(_(lang, "btn_user_lastseen"), callback_data=f"ls_{user_id}")],
        [InlineKeyboardButton(_(lang, "btn_user_rename"), callback_data=f"rename_{user_id}")],
        [InlineKeyboardButton(_(lang, "btn_user_notify", mode=mode_name), callback_data=f"notifymode_{user_id}")],
    ]
    if muted:
        kb.append([InlineKeyboardButton(_(lang, "unmute_done").replace("🔈 ", "🔈 Unmute "), callback_data=f"unmute_{user_id}")])
    else:
        kb.append([
            InlineKeyboardButton(_(lang, "mute_1h"), callback_data=f"mute_{user_id}_1"),
            InlineKeyboardButton(_(lang, "mute_4h"), callback_data=f"mute_{user_id}_4"),
            InlineKeyboardButton(_(lang, "mute_24h"), callback_data=f"mute_{user_id}_24"),
        ])
    kb.append([InlineKeyboardButton(_(lang, "btn_user_export"), callback_data=f"export_{user_id}")])
    if user_id != OWNER_ID:
        kb.append([InlineKeyboardButton(_(lang, "btn_user_remove"), callback_data=f"remove_{user_id}")])
    kb.append([InlineKeyboardButton(_(lang, "back"), callback_data="contacts")])
    return InlineKeyboardMarkup(kb), text


async def send_csv(update: Update, user_id: int, days: int = 365, tracked_by: int | None = None):
    """Generate CSV and send as document."""
    import csv, io
    data = db.get_export_data(user_id, days, tracked_by)
    if not data:
        await update.effective_message.reply_text("No data to export.")
        return
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["username", "display_name", "went_online", "went_offline"])
    for row in data:
        w.writerow([row["username"], row["display_name"], row["went_online"], row["went_offline"]])
    buf.seek(0)
    user = db.get_user(user_id)
    name = (user["display_name"] or user["username"] or str(user_id)) if user else str(user_id)
    await update.effective_message.reply_document(
        document=buf.getvalue().encode("utf-8"),
        filename=f"tg_sessions_{name}_{days}d.csv",
        caption=f"📥 {name} — {len(data)} sessions ({days} days)",
    )


# ── Handlers ─────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = guard(update)
    if not lang:
        await reject(update)
        return
    await update.message.reply_text(_(lang, "menu_title"), reply_markup=main_menu(lang))


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        return await _menu_callback(update, context)
    except Exception:
        import traceback
        traceback.print_exc()
        if update.callback_query:
            await update.callback_query.answer("⚠️ Error. Try /start.")
        return


async def _menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = guard(update)
    if not lang:
        await reject(update)
        return
    current_uid = update.effective_user.id
    await query.answer()
    data = query.data

    # ── Navigation ──
    if data == "menu":
        await query.edit_message_text(_(lang, "menu_title"), reply_markup=main_menu(lang))

    elif data == "contacts":
        kb, text = contacts_list(lang, current_uid)
        await query.edit_message_text(text, reply_markup=kb)

    # ── Last seen ──
    elif data == "lastseen":
        kb, text = user_picker(lang, "ls", current_uid)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("ls_"):
        user_id = int(data.split("_")[1])
        name = display(user_id)
        ts = db.get_last_seen(user_id, current_uid)
        await query.edit_message_text(
            fmt_last_seen(lang, name, ts),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data="lastseen")]
            ]),
        )

    # ── Full log ──
    elif data == "fulllog":
        kb, text = user_picker(lang, "log", current_uid)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("log_"):
        parts = data.split("_")
        if len(parts) >= 3:
            # log_<user_id>_<date>[_<page>]
            user_id = int(parts[1])
            date_str = parts[2]
            page = int(parts[3]) if len(parts) >= 4 else 0
            name = display(user_id)
            text, total_pages = fmt_daily_log_for_user(lang, user_id, name, date_str, page, current_uid)
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
        name = display(user_id)
        text, total_pages = fmt_daily_log_for_user(lang, user_id, name, date_str, 0, current_uid)
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
            fmt_getall(lang, current_uid),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data="menu")]
            ]),
        )

    # ── v5: Stats ──────────────────────────────────────────────────
    elif data == "stats":
        s = db.get_overall_stats(current_uid)
        if not s["total_sessions"]:
            await query.edit_message_text(
                _(lang, "stats_no_data"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(_(lang, "back"), callback_data="menu")]
                ]),
            )
            return

        lines = [
            _(lang, "stats_title"),
            "",
            _(lang, "stats_overall", sessions=s["total_sessions"], hours=s["total_h"]),
            "",
            _(lang, "stats_top"),
        ]
        for u in s["users"]:
            lines.append(_(lang, "stats_user_row", name=u["name"], sessions=u["sessions"], hours=u["total_h"]))

        users = db.get_active_users(current_uid)
        btns = []
        for u in users:
            name = u["display_name"] or u["username"] or str(u["user_id"])
            btns.append([InlineKeyboardButton(name, callback_data=f"ustats_{u['user_id']}")])
        btns.append([InlineKeyboardButton(_(lang, "back"), callback_data="menu")])

        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("ustats_"):
        user_id = int(data.split("_")[1])
        name = display(user_id)
        s = db.get_user_stats(user_id, current_uid)
        hourly = db.get_hourly_activity(user_id, 7, current_uid)

        if not s["sessions"]:
            await query.edit_message_text(
                _(lang, "stats_no_data"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(_(lang, "back"), callback_data="stats")]
                ]),
            )
            return

        lines = [
            _(lang, "stats_user_title", name=name),
            "",
            _(lang, "stats_sessions", sessions=s["sessions"]),
            _(lang, "stats_total_time", hours=s["total_h"]),
            _(lang, "stats_avg_session", avg=s["avg_min"]),
            _(lang, "stats_longest", longest=s["longest_min"]),
        ]
        if s["streak_days"]:
            lines.append(_(lang, "stats_streak", streak=s["streak_days"]))

        # Hourly activity bar — compact bars + markers every 3h
        max_count = max(c for _, c in hourly) or 1
        bar_chars = ["⬜", "🟨", "🟧", "🟥", "🟩"]
        row_bar = ""
        row_label = ""
        for h, cnt in hourly:
            idx = 0
            if cnt > 0:
                idx = min(4, max(1, int(cnt / max_count * 4)))
            row_bar += bar_chars[idx]
            # Show label every 3 hours
            if h % 3 == 0:
                row_label += f"{h:02d} "
            else:
                row_label += "   "
        lines.append("")
        lines.append(_(lang, "stats_hourly"))
        lines.append(row_bar)
        lines.append(row_label.rstrip())

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data="stats")]
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
        await query.edit_message_text(_(lang, "settings_title"), reply_markup=settings_menu(lang, current_uid))

    elif data == "toggle_lang":
        new_lang = "en" if lang == "ru" else "ru"
        settings.set_lang(new_lang)
        old_msg = query.message
        lang = new_lang
        await query.edit_message_text(_(lang, "settings_title"), reply_markup=settings_menu(lang, current_uid))

    elif data == "toggle_notifications":
        current = settings.get_notifications_enabled()
        settings.set_notifications_enabled(not current)
        await query.edit_message_text(_(lang, "settings_title"), reply_markup=settings_menu(lang, current_uid))

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

    # ── v4: DB stats + restart ───────────────────────────────────
    elif data == "db_stats":
        s = db.get_db_stats(current_uid)
        text = _(lang, "db_stats", size=s["size_mb"], sessions=s["sessions"], users=s["users"])
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "btn_cleanup"), callback_data="cleanup_db")],
                [InlineKeyboardButton(_(lang, "back"), callback_data="settings")],
            ]),
        )

    elif data == "cleanup_db":
        deleted = db.cleanup_old_sessions(90)
        db.vacuum_db()
        if deleted:
            await query.answer(_(lang, "cleanup_done", count=deleted), show_alert=True)
        else:
            await query.answer(_(lang, "cleanup_none"), show_alert=True)
        s = db.get_db_stats(current_uid)
        text = _(lang, "db_stats", size=s["size_mb"], sessions=s["sessions"], users=s["users"])
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data="settings")]
            ]),
        )

    elif data == "restart_confirm":
        await query.edit_message_text(
            _(lang, "restart_confirm"),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, restart", callback_data="do_restart"),
                    InlineKeyboardButton(_(lang, "cancel"), callback_data="settings"),
                ]
            ]),
        )

    elif data == "do_restart":
        await query.edit_message_text(_(lang, "restarting"))
        import os as _os
        _os.system("systemctl restart tg-online-tracker &")

    # ── v3: User submenu ──────────────────────────────────────────
    elif data.startswith("user_"):
        user_id = int(data.split("_")[1])
        kb, text = user_menu_view(lang, user_id, current_uid)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("notifymode_"):
        user_id = int(data.split("_")[1])
        modes = ["online", "offline", "both", "none"]
        cur = db.get_notify_mode(user_id, current_uid)
        nxt = modes[(modes.index(cur) + 1) % len(modes)]
        db.set_notify_mode(user_id, nxt, current_uid)
        kb, text = user_menu_view(lang, user_id, current_uid)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("rename_"):
        user_id = int(data.split("_")[1])
        name = display(user_id)
        context.user_data["rename_user"] = user_id
        await query.edit_message_text(
            _(lang, "rename_prompt", username=name),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back"), callback_data=f"user_{user_id}")]
            ]),
        )
        return WAIT_RENAME

    elif data.startswith("mute_"):
        parts = data.split("_")
        user_id, hours = int(parts[1]), int(parts[2])
        until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
        db.set_mute(user_id, until)
        name = display(user_id)
        await query.answer(_(lang, "mute_done", username=name, hours=hours), show_alert=True)
        kb, text = user_menu_view(lang, user_id, current_uid)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("unmute_"):
        user_id = int(data.split("_")[1])
        db.set_mute(user_id, None)
        name = display(user_id)
        await query.answer(_(lang, "unmute_done", username=name), show_alert=True)
        kb, text = user_menu_view(lang, user_id, current_uid)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("export_"):
        user_id = int(data.split("_")[1])
        await send_csv(update, user_id, tracked_by=current_uid)

    elif data.startswith("remove_"):
        user_id = int(data.split("_")[1])
        if user_id == OWNER_ID:
            await query.answer("👑 Cannot remove the owner", show_alert=True)
            return
        name = display(user_id)
        db.remove_user(user_id, current_uid)
        await query.answer(_(lang, "remove_success", name=name), show_alert=True)
        kb, text = contacts_list(lang, current_uid)
        if not kb:
            await query.edit_message_text(text, reply_markup=main_menu(lang))
        else:
            await query.edit_message_text(text, reply_markup=kb)


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
    db.add_user(entity.id, username, first, tracked_by=update.effective_user.id)
    settings.unblock_user(entity.id)
    await update.message.reply_text(
        _(lang, "add_success", username=username),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(_(lang, "to_menu"), callback_data="menu")]
        ]),
    )
    return ConversationHandler.END


async def receive_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle rename input."""
    lang = guard(update)
    if not lang:
        await reject(update)
        return ConversationHandler.END
    user_id = context.user_data.get("rename_user")
    if not user_id:
        return ConversationHandler.END
    new_name = update.message.text.strip()
    current_uid = update.effective_user.id
    if not new_name or new_name.lower() in ("cancel", "/cancel"):
        db.rename_user(user_id, "", current_uid)
        await update.message.reply_text(
            _(lang, "rename_cleared", username=display(user_id)),
            reply_markup=main_menu(lang),
        )
    else:
        db.rename_user(user_id, new_name, current_uid)
        await update.message.reply_text(
            _(lang, "rename_done", username=display(user_id), name=new_name),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_(lang, "back_to_user"), callback_data=f"user_{user_id}")]
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
        name = display(user_id)
        text, total_pages = fmt_daily_log_for_user(lang, user_id, name, date_str, 0, current_uid)
        btns = [[InlineKeyboardButton(_(lang, "back"), callback_data=f"log_{user_id}")]]
        if total_pages > 1:
            btns.insert(0, [InlineKeyboardButton(
                _(lang, "btn_more"), callback_data=f"log_{user_id}_{date_str}_1"
            )])
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(btns))
    return ConversationHandler.END


# ── Telethon event handler ───────────────────────────────────────────


def make_status_handler(bot_app):
    """Event handler that logs sessions and sends notifications with context."""
    tracked_ids = set()

    def _fmt_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        h, m = divmod(seconds, 3600)
        return f"{h}h {m // 60}m" if m >= 60 else f"{h}h"

    async def on_status(event):
        nonlocal tracked_ids
        user_id = event.user_id
        status = event.status

        # Get all tracked user IDs across ALL bot users
        all_tracked = {u["user_id"] for u in db.get_active_users()}
        tracked_ids = all_tracked
        if user_id not in tracked_ids:
            return

        now_utc = datetime.now(timezone.utc)

        # Find all bot users tracking this Telegram user
        trackers = set()
        for u in db.get_active_users():
            if u["user_id"] == user_id:
                trackers.add(u["tracked_by"])
        if not trackers:
            return

        if isinstance(status, UserStatusOnline):
            for tu in trackers:
                db.start_session(user_id, tu)
            print(f"[{now_utc}] 🟢 user_id={user_id} (tracked by {len(trackers)}) → online")

            for tu in trackers:
                user = db.get_user(user_id, tu)
                if not user:
                    continue
                mode = db.get_notify_mode(user_id, tu)
                if mode in ("online", "both") and not db.is_muted(user_id, tu):
                    prev = db.get_prev_session(user_id, tu)
                    ctx = ""
                    if prev and prev["went_offline"]:
                        try:
                            prev_off = datetime.fromisoformat(str(prev["went_offline"]))
                            delta = int((now_utc - prev_off).total_seconds())
                            if delta > 0:
                                ctx = f" (was offline {_fmt_duration(delta)})"
                        except (ValueError, TypeError):
                            pass
                    name = user["display_name"] or user["username"] or str(user_id)
                    text = f"🟢 {name} online{ctx}"
                    try:
                        await bot_app.bot.send_message(tu, text)
                    except Exception:
                        pass

        elif isinstance(status, UserStatusOffline):
            for tu in trackers:
                db.end_session(user_id, tu)
            print(f"[{now_utc}] ⚫ user_id={user_id} (tracked by {len(trackers)}) → offline")

            for tu in trackers:
                user = db.get_user(user_id, tu)
                if not user:
                    continue
                mode = db.get_notify_mode(user_id, tu)
                if mode in ("offline", "both") and not db.is_muted(user_id, tu):
                    prev = db.get_prev_session(user_id, tu)
                    ctx = ""
                    if prev and prev["went_online"]:
                        try:
                            prev_on = datetime.fromisoformat(str(prev["went_online"]))
                            delta = int((now_utc - prev_on).total_seconds())
                            if delta > 0:
                                ctx = f" (session {_fmt_duration(delta)})"
                        except (ValueError, TypeError):
                            pass
                    name = user["display_name"] or user["username"] or str(user_id)
                    text = f"⚫ {name} offline{ctx}"
                    try:
                        await bot_app.bot.send_message(tu, text)
                    except Exception:
                        pass

    return on_status


# ── Main ───────────────────────────────────────────────────────────────


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
        "|db_stats|cleanup_db|restart_confirm|do_restart"
        "|stats|ustats_\\d+"
        "|remove_\\d+|ls_\\d+|log_\\d+|log_\\d+_\\S+|date_\\d+_\\S+|wldel_\\d+|unblock_\\d+"
        "|user_\\d+|notifymode_\\d+|rename_\\d+|mute_\\d+_\\d+|unmute_\\d+|export_\\d+)$"
    )

    rename_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^rename_\\d+$")],
        states={WAIT_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_rename)]},
        fallbacks=[CallbackQueryHandler(menu_callback, pattern="^user_\\d+$")],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=default_pattern))
    app.add_handler(add_conv)
    app.add_handler(wl_conv)
    app.add_handler(date_conv)
    app.add_handler(rename_conv)

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print(f"[main] Bot polling started. @{app.bot.username}")

    # Start REST API on localhost
    import api as _api
    _api.run_api()

    try:
        await telethon.run_until_disconnected()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
