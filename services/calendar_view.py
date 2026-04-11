from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from services.reminders import reminders_for_day, reminders_for_week


def daily_view_events(session_id: str, day: date) -> list[dict[str, Any]]:
    rows = reminders_for_day(session_id, day)
    return sorted(rows, key=lambda r: (r["reminder_time"], r["id"]))


def weekly_view_events(session_id: str, start_day: date) -> list[tuple[str, list[dict[str, Any]]]]:
    week = reminders_for_week(session_id, start_day)
    days = []
    for i in range(7):
        key = (start_day + timedelta(days=i)).isoformat()
        rows = sorted(week.get(key, []), key=lambda r: (r["reminder_time"], r["id"]))
        days.append((key, rows))
    return days

