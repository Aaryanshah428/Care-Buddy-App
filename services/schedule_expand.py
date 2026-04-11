"""Expand recurring reminders onto concrete calendar dates."""

from __future__ import annotations

from datetime import date, timedelta

from services.schedule_constants import (
    SCHEDULE_BIWEEKLY,
    SCHEDULE_DAILY,
    SCHEDULE_ONCE,
    SCHEDULE_SPECIAL,
    SCHEDULE_WEEKLY,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _anchor_date(reminder_date: str) -> date:
    return date.fromisoformat((reminder_date or "")[:10])


def _first_weekday_on_or_after(d: date, weekday_index: int) -> date:
    delta = (weekday_index - d.weekday()) % 7
    return d + timedelta(days=delta)


def iter_occurrence_dates(
    reminder_row: dict,
    range_start: date,
    range_end: date,
) -> list[date]:
    """
    Return dates in [range_start, range_end] when this reminder fires.
    Uses reminder_date as anchor / reference date.
    """
    anchor = _anchor_date(reminder_row["reminder_date"])
    stype = reminder_row.get("schedule_type") or SCHEDULE_ONCE
    detail = (reminder_row.get("schedule_detail") or "").strip()

    if stype == SCHEDULE_ONCE:
        return [anchor] if range_start <= anchor <= range_end else []

    if stype == SCHEDULE_DAILY:
        d = max(anchor, range_start)
        out: list[date] = []
        while d <= range_end:
            out.append(d)
            d += timedelta(days=1)
        return out

    if stype == SCHEDULE_WEEKLY:
        if detail in WEEKDAYS:
            wi = WEEKDAYS.index(detail)
            first = _first_weekday_on_or_after(anchor, wi)
            if first < anchor:
                first += timedelta(days=7)
            d = first
            while d < range_start:
                d += timedelta(days=7)
            out = []
            while d <= range_end:
                out.append(d)
                d += timedelta(days=7)
            return out
        d = anchor
        while d < range_start:
            d += timedelta(days=7)
        out = []
        while d <= range_end:
            out.append(d)
            d += timedelta(days=7)
        return out

    if stype == SCHEDULE_BIWEEKLY:
        d = anchor
        while d < range_start:
            d += timedelta(days=14)
        out = []
        while d <= range_end:
            out.append(d)
            d += timedelta(days=14)
        return out

    if stype == SCHEDULE_SPECIAL:
        return [anchor] if range_start <= anchor <= range_end else []

    return []


def occurs_on(reminder_row: dict, day: date) -> bool:
    return day in iter_occurrence_dates(reminder_row, day, day)
