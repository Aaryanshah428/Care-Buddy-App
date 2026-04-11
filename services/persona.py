from __future__ import annotations

from dataclasses import dataclass

from services.db import connect, now_iso


@dataclass
class Persona:
    name: str = ""
    age: str = ""
    language: str = "English"
    timezone: str = "UTC"
    reminder_style: str = "gentle"


def get_persona(session_id: str) -> Persona:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_profile WHERE session_id = ?", (session_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return Persona()
    return Persona(
        name=row["name"] or "",
        age=row["age"] or "",
        language=row["language"] or "English",
        timezone=row["timezone"] or "UTC",
        reminder_style=row["reminder_style"] or "gentle",
    )


def save_persona(session_id: str, persona: Persona) -> None:
    conn = connect()
    cur = conn.cursor()
    ts = now_iso()
    cur.execute(
        """
        INSERT INTO user_profile (session_id, name, age, language, timezone, reminder_style, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE
        SET name=excluded.name,
            age=excluded.age,
            language=excluded.language,
            timezone=excluded.timezone,
            reminder_style=excluded.reminder_style,
            updated_at=excluded.updated_at
        """,
        (session_id, persona.name, persona.age, persona.language, persona.timezone, persona.reminder_style, ts),
    )
    conn.commit()
    conn.close()

