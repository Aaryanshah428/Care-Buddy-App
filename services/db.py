from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "senior_care_bot.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _add_column_if_missing(cur: sqlite3.Cursor, table: str, column: str, col_def: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    if column not in {r[1] for r in cur.fetchall()}:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def ensure_db() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, key)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    # Legacy tables kept for compatibility/migration.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            reminder_date TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            place TEXT NOT NULL,
            medicine_type TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS general_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            reminder_date TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            place TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    _add_column_if_missing(cur, "reminders", "schedule_type", "TEXT NOT NULL DEFAULT 'once'")
    _add_column_if_missing(cur, "reminders", "schedule_detail", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(cur, "general_reminders", "schedule_type", "TEXT NOT NULL DEFAULT 'once'")
    _add_column_if_missing(cur, "general_reminders", "schedule_detail", "TEXT NOT NULL DEFAULT ''")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS unified_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            reminder_date TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            place TEXT NOT NULL DEFAULT '',
            notes TEXT DEFAULT '',
            schedule_type TEXT NOT NULL DEFAULT 'once',
            schedule_detail TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            source_legacy_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profile (
            session_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            age TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT 'English',
            timezone TEXT NOT NULL DEFAULT 'UTC',
            reminder_style TEXT NOT NULL DEFAULT 'gentle',
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            summary_date TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(session_id, summary_date)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            reminder_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            reminder_id INTEGER NOT NULL,
            completed_on TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(session_id, reminder_id, completed_on)
        )
        """
    )
    conn.commit()
    conn.close()


def now_iso() -> str:
    return datetime.utcnow().isoformat()

