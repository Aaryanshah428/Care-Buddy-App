from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from services import db as dbmod
from services.db import ensure_db
from services.persona import Persona, get_persona, save_persona
from services.reminders import (
    SCHEDULE_DAILY,
    SCHEDULE_ONCE,
    SCHEDULE_WEEKLY,
    add_reminder,
    list_reminders,
    migrate_legacy_reminders,
)
from services.schedule_expand import iter_occurrence_dates, occurs_on
from services.summary import build_daily_summary


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    monkeypatch.setattr(dbmod, "DB_DIR", tmp_path)
    ensure_db()
    yield path


def test_daily_occurrences_span(fresh_db: Path) -> None:
    row = {
        "reminder_date": "2026-01-01",
        "reminder_time": "09:00",
        "schedule_type": SCHEDULE_DAILY,
        "schedule_detail": "",
    }
    days = iter_occurrence_dates(row, date(2026, 1, 5), date(2026, 1, 7))
    assert days == [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]


def test_weekly_occurrence(fresh_db: Path) -> None:
    row = {
        "reminder_date": "2026-01-05",
        "reminder_time": "10:00",
        "schedule_type": SCHEDULE_WEEKLY,
        "schedule_detail": "Monday",
    }
    # 2026-01-05 is a Monday
    assert occurs_on(row, date(2026, 1, 5)) is True
    assert occurs_on(row, date(2026, 1, 12)) is True


def test_persona_roundtrip(fresh_db: Path) -> None:
    sid = "sess-1"
    save_persona(
        sid,
        Persona(name="Ada", age="72", language="Spanish", timezone="America/New_York", reminder_style="direct"),
    )
    p = get_persona(sid)
    assert p.name == "Ada"
    assert p.language == "Spanish"
    assert p.reminder_style == "direct"


def test_legacy_migration_to_unified(fresh_db: Path) -> None:
    conn = dbmod.connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO reminders (session_id, reminder_date, reminder_time, place, medicine_type, notes, created_at)
        VALUES ('s1', '2026-02-01', '08:00', '', 'Aspirin', '', '2026-01-01T00:00:00')
        """
    )
    conn.commit()
    conn.close()
    migrate_legacy_reminders("s1")
    rows = list_reminders("s1")
    assert len(rows) == 1
    assert rows[0]["title"] == "Aspirin"
    assert rows[0]["kind"] == "medicine"


def test_summary_counts_today(fresh_db: Path) -> None:
    sid = "s2"
    add_reminder(
        sid,
        kind="medicine",
        title="Med A",
        reminder_date="2026-03-10",
        reminder_time="09:00",
        schedule_type=SCHEDULE_ONCE,
    )
    text = build_daily_summary(sid, date(2026, 3, 10))
    assert "2026-03-10" in text
    assert "Medication-type items today: 1" in text
