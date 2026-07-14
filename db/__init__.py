"""Database package — re-exports from core module."""
from .core import (
    init_db, get_conn, DB_PATH,
    add_user, remove_user, get_active_users, get_user, get_user_by_username,
    start_session, end_session, get_last_seen, get_daily_log, is_online_now,
    set_display_name, get_display_name,
    set_notify_mode, get_notify_mode,
    set_mute, is_muted,
    get_prev_session, get_export_data,
    get_db_stats, cleanup_old_sessions, vacuum_db,
    get_user_stats, get_hourly_activity, get_overall_stats,
)
