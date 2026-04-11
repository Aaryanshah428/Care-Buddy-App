from __future__ import annotations

from datetime import date, datetime

from services.db import connect, now_iso
from services.reminders import count_completions_on_day, list_upcoming_in_hours, reminders_for_day


def build_daily_summary(session_id: str, target_day: date) -> str:
    today_rows = reminders_for_day(session_id, target_day)
    completed_n = count_completions_on_day(session_id, target_day)
    upcoming = list_upcoming_in_hours(session_id, 24)
    meds = [r for r in today_rows if r["kind"] == "medicine"]

    day_iso = target_day.isoformat()
    lines = [
        f"Date: {day_iso}",
        f"Scheduled today (including repeating): {len(today_rows)}",
        f"Medication-type items today: {len(meds)}",
        f"Marked done today: {completed_n}",
        f"Due in the next 24 hours: {len(upcoming)}",
    ]
    if today_rows:
        preview = "; ".join(
            f"{r['reminder_time']} {r['title']} ({r['kind']})" for r in today_rows[:6]
        )
        lines.append(f"Today's line-up: {preview}")
    if upcoming:
        parts = []
        for dt, r in upcoming[:5]:
            parts.append(f"{r['title']} @ {dt.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"Soon: {', '.join(parts)}")
    return "\n".join(lines)


def save_daily_summary(session_id: str, target_day: date, content: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO daily_summaries (session_id, summary_date, content, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(session_id, summary_date) DO UPDATE SET content = excluded.content, created_at = excluded.created_at
        """,
        (session_id, target_day.isoformat(), content, now_iso()),
    )
    conn.commit()
    conn.close()
