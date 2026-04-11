"""Due-time notification dispatch with deduplication."""

from __future__ import annotations

from datetime import datetime, timedelta

from services.db import connect, now_iso
from services.reminders import list_reminders, next_occurrence_datetime


def _already_sent(session_id: str, reminder_id: int, channel: str, within_minutes: int = 3) -> bool:
    conn = connect()
    cur = conn.cursor()
    since = (datetime.utcnow() - timedelta(minutes=within_minutes)).isoformat()
    cur.execute(
        """
        SELECT 1 FROM notification_log
        WHERE session_id = ? AND reminder_id = ? AND channel = ? AND created_at >= ?
        LIMIT 1
        """,
        (session_id, reminder_id, channel, since),
    )
    ok = cur.fetchone() is not None
    conn.close()
    return ok


def _log_send(session_id: str, reminder_id: int, channel: str, status: str, detail: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO notification_log (session_id, reminder_id, channel, status, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, reminder_id, channel, status, detail, now_iso()),
    )
    conn.commit()
    conn.close()


def notify_due_reminders(
    session_id: str,
    destination: str,
    channel: str,
    provider,
) -> None:
    if not destination or provider is None:
        return
    now = datetime.now()
    for r in list_reminders(session_id):
        if r["status"] == "completed":
            continue
        dt = next_occurrence_datetime(r, now)
        if dt is None:
            continue
        if abs((dt - now).total_seconds()) > 90:
            continue
        if _already_sent(session_id, r["id"], channel):
            continue
        ok, detail = provider.send(destination, f"CareBuddy reminder: {r['title']} at {r['reminder_time']}")
        _log_send(session_id, r["id"], channel, "ok" if ok else "fail", detail[:500])
