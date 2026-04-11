from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from services.db import connect, now_iso
from services.schedule_constants import (
    SCHEDULE_BIWEEKLY,
    SCHEDULE_DAILY,
    SCHEDULE_ONCE,
    SCHEDULE_SPECIAL,
    SCHEDULE_WEEKLY,
)
from services.schedule_expand import iter_occurrence_dates, occurs_on


def migrate_legacy_reminders(session_id: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM unified_reminders WHERE session_id = ?",
        (session_id,),
    )
    if (cur.fetchone()["c"] or 0) > 0:
        conn.close()
        return
    cur.execute("SELECT * FROM reminders WHERE session_id = ? ORDER BY id ASC", (session_id,))
    legacy_meds = cur.fetchall()
    cur.execute(
        "SELECT * FROM general_reminders WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    )
    legacy_gen = cur.fetchall()
    ts = now_iso()
    for r in legacy_meds:
        cur.execute(
            """
            INSERT INTO unified_reminders (
                session_id, kind, title, reminder_date, reminder_time, place, notes,
                schedule_type, schedule_detail, status, source_legacy_id, created_at, updated_at
            ) VALUES (?, 'medicine', ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                session_id,
                r["medicine_type"],
                r["reminder_date"],
                r["reminder_time"],
                r["place"] or "",
                r["notes"] or "",
                r["schedule_type"] or SCHEDULE_ONCE,
                r["schedule_detail"] or "",
                r["id"],
                r["created_at"] or ts,
                ts,
            ),
        )
    for r in legacy_gen:
        cur.execute(
            """
            INSERT INTO unified_reminders (
                session_id, kind, title, reminder_date, reminder_time, place, notes,
                schedule_type, schedule_detail, status, source_legacy_id, created_at, updated_at
            ) VALUES (?, 'general', ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                session_id,
                r["title"],
                r["reminder_date"],
                r["reminder_time"],
                r["place"] or "",
                r["notes"] or "",
                r["schedule_type"] or SCHEDULE_ONCE,
                r["schedule_detail"] or "",
                r["id"],
                r["created_at"] or ts,
                ts,
            ),
        )
    conn.commit()
    conn.close()


def list_reminders(session_id: str) -> list[dict[str, Any]]:
    migrate_legacy_reminders(session_id)
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM unified_reminders
        WHERE session_id = ?
        ORDER BY reminder_date ASC, reminder_time ASC, id ASC
        """,
        (session_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_reminder(
    session_id: str,
    *,
    kind: str,
    title: str,
    reminder_date: str,
    reminder_time: str,
    place: str = "",
    notes: str = "",
    schedule_type: str = SCHEDULE_ONCE,
    schedule_detail: str = "",
) -> None:
    conn = connect()
    cur = conn.cursor()
    ts = now_iso()
    cur.execute(
        """
        INSERT INTO unified_reminders
        (session_id, kind, title, reminder_date, reminder_time, place, notes, schedule_type, schedule_detail, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            session_id,
            kind,
            title.strip(),
            reminder_date,
            reminder_time,
            (place or "").strip(),
            (notes or "").strip(),
            schedule_type,
            (schedule_detail or "").strip(),
            ts,
            ts,
        ),
    )
    conn.commit()
    conn.close()


def update_reminder(session_id: str, reminder_id: int, **fields: Any) -> None:
    allowed = {
        "kind",
        "title",
        "reminder_date",
        "reminder_time",
        "place",
        "notes",
        "schedule_type",
        "schedule_detail",
        "status",
    }
    pairs = [(k, v) for k, v in fields.items() if k in allowed]
    if not pairs:
        return
    set_sql = ", ".join(f"{k} = ?" for k, _ in pairs) + ", updated_at = ?"
    vals = [v for _, v in pairs] + [now_iso(), session_id, reminder_id]
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE unified_reminders SET {set_sql} WHERE session_id = ? AND id = ?",
        vals,
    )
    conn.commit()
    conn.close()


def delete_reminder(session_id: str, reminder_id: int) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM unified_reminders WHERE session_id = ? AND id = ?",
        (session_id, reminder_id),
    )
    conn.commit()
    conn.close()


def list_medicines(session_id: str) -> list[str]:
    meds = []
    seen = set()
    for r in list_reminders(session_id):
        if r["kind"] != "medicine":
            continue
        name = (r["title"] or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            meds.append(name)
    return meds


def format_schedule_summary(schedule_type: str, schedule_detail: str, reminder_date: str) -> str:
    if schedule_type == SCHEDULE_DAILY:
        return "Daily"
    if schedule_type == SCHEDULE_WEEKLY:
        d = (schedule_detail or "").strip() or "Weekly"
        return f"Weekly ({d})"
    if schedule_type == SCHEDULE_BIWEEKLY:
        return "Every two weeks"
    if schedule_type == SCHEDULE_SPECIAL:
        s = (schedule_detail or "").strip() or "Special days"
        return f"Special: {s}"
    return f"One-time ({reminder_date})"


def _parse_dt(d: str, t: str) -> datetime:
    return datetime.fromisoformat(f"{d}T{t}:00")


def next_occurrence_datetime(r: dict[str, Any], now: datetime) -> datetime | None:
    if r["status"] == "completed":
        return None
    start_d = now.date()
    end_d = start_d + timedelta(days=366)
    best: datetime | None = None
    for d in iter_occurrence_dates(r, start_d, end_d):
        try:
            dt = _parse_dt(d.isoformat(), r["reminder_time"])
        except ValueError:
            continue
        if dt >= now and (best is None or dt < best):
            best = dt
    return best


def next_reminder(session_id: str, today: date | None = None) -> dict[str, Any] | None:
    now = datetime.now()
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for r in list_reminders(session_id):
        dt = next_occurrence_datetime(r, now)
        if dt is not None:
            candidates.append((dt, r))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def reminders_for_day(session_id: str, target_day: date) -> list[dict[str, Any]]:
    return [r for r in list_reminders(session_id) if occurs_on(r, target_day)]


def reminders_for_week(session_id: str, start_day: date) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for i in range(7):
        d = start_day + timedelta(days=i)
        out[d.isoformat()] = reminders_for_day(session_id, d)
    return out


def mark_completed_for_day(session_id: str, reminder_id: int, on_day: date) -> None:
    conn = connect()
    cur = conn.cursor()
    ts = now_iso()
    cur.execute(
        """
        INSERT OR IGNORE INTO reminder_completions (session_id, reminder_id, completed_on, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, reminder_id, on_day.isoformat(), ts),
    )
    conn.commit()
    conn.close()


def unmark_completed_for_day(session_id: str, reminder_id: int, on_day: date) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM reminder_completions
        WHERE session_id = ? AND reminder_id = ? AND completed_on = ?
        """,
        (session_id, reminder_id, on_day.isoformat()),
    )
    conn.commit()
    conn.close()


def is_completed_for_day(session_id: str, reminder_id: int, on_day: date) -> bool:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM reminder_completions
        WHERE session_id = ? AND reminder_id = ? AND completed_on = ?
        LIMIT 1
        """,
        (session_id, reminder_id, on_day.isoformat()),
    )
    ok = cur.fetchone() is not None
    conn.close()
    return ok


def count_completions_on_day(session_id: str, on_day: date) -> int:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM reminder_completions
        WHERE session_id = ? AND completed_on = ?
        """,
        (session_id, on_day.isoformat()),
    )
    n = int(cur.fetchone()["c"] or 0)
    conn.close()
    return n


def list_upcoming_in_hours(session_id: str, hours: int = 24) -> list[tuple[datetime, dict[str, Any]]]:
    now = datetime.now()
    end = now + timedelta(hours=hours)
    out: list[tuple[datetime, dict[str, Any]]] = []
    start_d = now.date()
    end_d = end.date() + timedelta(days=1)
    for r in list_reminders(session_id):
        if r["status"] == "completed":
            continue
        for d in iter_occurrence_dates(r, start_d, end_d):
            try:
                dt = _parse_dt(d.isoformat(), r["reminder_time"])
            except ValueError:
                continue
            if now <= dt <= end:
                out.append((dt, r))
    out.sort(key=lambda x: x[0])
    return out

