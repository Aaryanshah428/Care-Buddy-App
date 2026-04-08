"""
Senior Care Chatbot — SQLite memory, chat logging, persona prompt.
Helps older adults with medicine reminders, exercise, and daily wellness.
"""

import io
import os
import sqlite3
import uuid
from datetime import datetime, time as time_cls
from pathlib import Path

import streamlit as st

from medicine_bottle_vision import analyze_medicine_bottle_image_bytes
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# =============================================================================
# Config & paths
# =============================================================================
DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "senior_care_bot.db"

# Schedule types stored in DB (medicine + general reminders)
SCHEDULE_ONCE = "once"
SCHEDULE_DAILY = "daily"
SCHEDULE_WEEKLY = "weekly"
SCHEDULE_BIWEEKLY = "biweekly"
SCHEDULE_SPECIAL = "special"

SCHEDULE_LABELS = {
    SCHEDULE_ONCE: "One-time (pick a date)",
    SCHEDULE_DAILY: "Every day",
    SCHEDULE_WEEKLY: "Every week (same weekday)",
    SCHEDULE_BIWEEKLY: "Every two weeks",
    SCHEDULE_SPECIAL: "Special days (describe below)",
}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Dynamic date field label by schedule (same key=rem_date / gen_date keeps one picker)
DATE_LABEL_FOR_SCHEDULE = {
    SCHEDULE_ONCE: "On this date",
    SCHEDULE_DAILY: "Starting / reference date",
    SCHEDULE_WEEKLY: "Reference date (first week)",
    SCHEDULE_BIWEEKLY: "Anchor date (repeats every 2 weeks from here)",
    SCHEDULE_SPECIAL: "Reference date (optional anchor)",
}

def parse_stored_date(s: str):
    if not s:
        return datetime.now().date()
    return datetime.fromisoformat(s[:10]).date()


def parse_stored_time(s: str) -> time_cls:
    if not s:
        return time_cls(9, 0)
    s = s.strip()
    if len(s) >= 5:
        return datetime.strptime(s[:5], "%H:%M").time()
    return time_cls(9, 0)


def schedule_type_index(sched_keys: list, sched_type: str) -> int:
    if sched_type in sched_keys:
        return sched_keys.index(sched_type)
    return 0


def weekday_index(detail: str) -> int:
    d = (detail or "").strip()
    if d in WEEKDAYS:
        return WEEKDAYS.index(d)
    return 0


def clear_edit_key_prefix(prefix: str):
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(prefix):
            del st.session_state[k]


def ensure_new_med_add_defaults(mv: int):
    """First paint of a new add form: one-time schedule, 9:00 time — not clock-now or stale values."""
    sk = f"med_sched_{mv}"
    if sk not in st.session_state:
        st.session_state[sk] = SCHEDULE_ONCE
    tk = f"rem_time_{mv}"
    if tk not in st.session_state:
        st.session_state[tk] = time_cls(9, 0)


def ensure_new_gen_add_defaults(gv: int):
    sk = f"gen_sched_{gv}"
    if sk not in st.session_state:
        st.session_state[sk] = SCHEDULE_ONCE
    tk = f"gen_time_{gv}"
    if tk not in st.session_state:
        st.session_state[tk] = time_cls(9, 0)


def _add_column_if_missing(cur, table: str, column: str, col_def: str):
    cur.execute(f"PRAGMA table_info({table})")
    if column not in {r[1] for r in cur.fetchall()}:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def ensure_db():
    """Create data dir and DB tables if they don't exist."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, key)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
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
    """)
    cur.execute("""
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
    """)
    _add_column_if_missing(cur, "reminders", "schedule_type", "TEXT NOT NULL DEFAULT 'once'")
    _add_column_if_missing(cur, "reminders", "schedule_detail", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(cur, "general_reminders", "schedule_type", "TEXT NOT NULL DEFAULT 'once'")
    _add_column_if_missing(cur, "general_reminders", "schedule_detail", "TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


def log_message(session_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_log (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_chat_history(session_id: str, limit: int = 50):
    """Return list of (role, content) for this session, oldest first."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content FROM chat_log WHERE session_id = ? ORDER BY id ASC LIMIT ?",
        (session_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]


def memory_set(session_id: str, key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        """
        INSERT INTO memory (session_id, key, value, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(session_id, key) DO UPDATE SET value = ?, updated_at = ?
        """,
        (session_id, key, value, now, value, now),
    )
    conn.commit()
    conn.close()


def memory_get(session_id: str, key: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT value FROM memory WHERE session_id = ? AND key = ?", (session_id, key))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def memory_get_all(session_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM memory WHERE session_id = ?", (session_id,))
    rows = cur.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


# =============================================================================
# Medicines (simple list)
# =============================================================================
def medicine_list(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM medicines WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1]} for r in rows]


def medicine_add(session_id: str, name: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO medicines (session_id, name, created_at) VALUES (?, ?, ?)",
        (session_id, name.strip(), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def medicine_add_if_new(session_id: str, name: str):
    """Add a medicine name only if not already listed (case-insensitive), so chat context stays in sync with reminders."""
    name = (name or "").strip()
    if not name or name == "—":
        return
    existing = {m["name"].lower() for m in medicine_list(session_id)}
    if name.lower() in existing:
        return
    medicine_add(session_id, name)


def medicine_delete(session_id: str, medicine_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM medicines WHERE session_id = ? AND id = ?", (session_id, medicine_id))
    conn.commit()
    conn.close()


# =============================================================================
# Reminders (date, time, place, type of medicine, notes)
# =============================================================================
def _normalize_place(place):
    return (place or "").strip()


def format_schedule_summary(
    schedule_type: str,
    schedule_detail: str,
    anchor_date: str,
) -> str:
    """Human-readable schedule for UI and LLM context."""
    detail = (schedule_detail or "").strip()
    if schedule_type == SCHEDULE_ONCE:
        return f"One-time on {anchor_date}"
    if schedule_type == SCHEDULE_DAILY:
        return f"Every day (reference/start date: {anchor_date})"
    if schedule_type == SCHEDULE_WEEKLY:
        day = detail or "weekly"
        return f"Every week on {day} (reference date: {anchor_date})"
    if schedule_type == SCHEDULE_BIWEEKLY:
        return f"Every two weeks (anchor date: {anchor_date})" + (f" — {detail}" if detail else "")
    if schedule_type == SCHEDULE_SPECIAL:
        return f"Special schedule: {detail or '(see notes)'}" + (f" (reference date: {anchor_date})" if anchor_date else "")
    return f"{anchor_date} ({schedule_type})"


def reminder_list(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, reminder_date, reminder_time, place, medicine_type, notes, schedule_type, schedule_detail
        FROM reminders WHERE session_id = ? ORDER BY reminder_date, reminder_time
        """,
        (session_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "date": r[1],
            "time": r[2],
            "place": r[3] or "",
            "medicine_type": r[4],
            "notes": r[5] or "",
            "schedule_type": r[6] if len(r) > 6 and r[6] else SCHEDULE_ONCE,
            "schedule_detail": r[7] if len(r) > 7 and r[7] is not None else "",
        }
        for r in rows
    ]


def reminder_add(
    session_id: str,
    reminder_date: str,
    reminder_time: str,
    place: str,
    medicine_type: str,
    notes: str = "",
    schedule_type: str = SCHEDULE_ONCE,
    schedule_detail: str = "",
):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO reminders (
            session_id, reminder_date, reminder_time, place, medicine_type, notes,
            schedule_type, schedule_detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            reminder_date,
            reminder_time,
            _normalize_place(place),
            medicine_type.strip(),
            (notes or "").strip(),
            schedule_type,
            (schedule_detail or "").strip(),
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    medicine_add_if_new(session_id, medicine_type)


def reminder_delete(session_id: str, reminder_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM reminders WHERE session_id = ? AND id = ?", (session_id, reminder_id))
    conn.commit()
    conn.close()


def reminder_update(
    session_id: str,
    reminder_id: int,
    reminder_date: str,
    reminder_time: str,
    place: str,
    medicine_type: str,
    notes: str = "",
    schedule_type: str = SCHEDULE_ONCE,
    schedule_detail: str = "",
):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE reminders SET
            reminder_date = ?, reminder_time = ?, place = ?, medicine_type = ?, notes = ?,
            schedule_type = ?, schedule_detail = ?
        WHERE session_id = ? AND id = ?
        """,
        (
            reminder_date,
            reminder_time,
            _normalize_place(place),
            medicine_type.strip(),
            (notes or "").strip(),
            schedule_type,
            (schedule_detail or "").strip(),
            session_id,
            reminder_id,
        ),
    )
    conn.commit()
    conn.close()
    medicine_add_if_new(session_id, medicine_type)


# =============================================================================
# General reminders (non-medicine: appointments, tasks, events)
# =============================================================================
def general_reminder_list(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, reminder_date, reminder_time, place, notes, schedule_type, schedule_detail
        FROM general_reminders WHERE session_id = ? ORDER BY reminder_date, reminder_time
        """,
        (session_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "title": r[1],
            "date": r[2],
            "time": r[3],
            "place": r[4] or "",
            "notes": r[5] or "",
            "schedule_type": r[6] if len(r) > 6 and r[6] else SCHEDULE_ONCE,
            "schedule_detail": r[7] if len(r) > 7 and r[7] is not None else "",
        }
        for r in rows
    ]


def general_reminder_add(
    session_id: str,
    title: str,
    reminder_date: str,
    reminder_time: str,
    place: str,
    notes: str = "",
    schedule_type: str = SCHEDULE_ONCE,
    schedule_detail: str = "",
):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO general_reminders (
            session_id, title, reminder_date, reminder_time, place, notes,
            schedule_type, schedule_detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            title.strip(),
            reminder_date,
            reminder_time,
            _normalize_place(place),
            (notes or "").strip(),
            schedule_type,
            (schedule_detail or "").strip(),
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def general_reminder_delete(session_id: str, reminder_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM general_reminders WHERE session_id = ? AND id = ?", (session_id, reminder_id))
    conn.commit()
    conn.close()


def general_reminder_update(
    session_id: str,
    reminder_id: int,
    title: str,
    reminder_date: str,
    reminder_time: str,
    place: str,
    notes: str = "",
    schedule_type: str = SCHEDULE_ONCE,
    schedule_detail: str = "",
):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE general_reminders SET
            title = ?, reminder_date = ?, reminder_time = ?, place = ?, notes = ?,
            schedule_type = ?, schedule_detail = ?
        WHERE session_id = ? AND id = ?
        """,
        (
            title.strip(),
            reminder_date,
            reminder_time,
            _normalize_place(place),
            (notes or "").strip(),
            schedule_type,
            (schedule_detail or "").strip(),
            session_id,
            reminder_id,
        ),
    )
    conn.commit()
    conn.close()


# =============================================================================
# Persona prompt template (senior care)
# =============================================================================
PERSONA_SYSTEM = """You are a warm, patient, and caring assistant for older adults. Your name is CareBuddy.

Your goals:
- Remind and encourage them to take their medicine on time.
- Gently encourage light exercise (walking, stretching, chair exercises) when appropriate.
- Help with simple daily routines: hydration, sleep, meals.
- Provide practical tips for staying organized, such as managing appointments and remembering important dates.
- Offer reminders for important events (e.g., family birthdays, doctor appointments).
- Suggest fun and safe indoor or outdoor activities tailored for older adults.
- Assist with basic technology questions, like how to use a phone, send a message, or access an app.
- Offer gentle mental stimulation activities (e.g., simple puzzles, trivia, or memory games) when asked.
- Offer positive encouragement and emotional support for daily challenges.
- Provide safety tips for home and outside (e.g., fall prevention, emergency contacts).
- Offer companionship and check-ins (“How are you today?”).
- Help with organizing shopping lists or meal ideas for the week.
- Share light, uplifting stories or jokes if the user asks.
- Be reassuring and use clear, simple language. Avoid jargon.
- Never be condescending; treat them with respect and dignity.
- If they share health concerns, encourage them to talk to their doctor or family; do not give medical advice.
- Keep responses concise and easy to read (short paragraphs or bullet points when helpful).
- Offer brain teasers or short memory games for cognitive exercise if the user is interested.
- Suggest easy at-home crafts, hobbies, or new skills to learn based on the user's preferences.
- Proactively ask if the user would like assistance setting up reminders for medications, appointments, or important tasks.
- Provide gentle sleep hygiene tips or evening wind-down routines if the user has trouble sleeping.
- Check if the user needs help contacting family, caregivers, or local services.
- Help track water intake or suggest hydration reminders.
- Offer seasonal advice, such as staying cool in summer or warm in winter.
- Assist with transportation tips (public transit, ride apps, senior ride programs) if the user asks.
- Share simple, nutritious recipe ideas tailored to dietary restrictions if requested.
- Offer gentle digital security tips (e.g., recognizing scams, creating strong passwords).

IMPORTANT — Only use the following information that the user has added in this app. Do not invent or assume any medicines or reminders.
- The left sidebar has two tabs: "Medicine reminders" and "General reminders". Each row includes a schedule: one-time, daily, weekly, every two weeks, or special days (with their description). Place is optional.
- If the user asks for medicine reminders and that list is empty, say they can add one under the Medicine reminders tab.
- If they ask for general reminders and that list is empty, say they can add one under the General reminders tab.
- If they ask broadly "what are my reminders?", combine information from both medicine reminders and general reminders when both exist.
- If the user asks for their medicines and the medicines list is empty with no medicine reminders, suggest adding a medicine reminder in the sidebar.
- For scheduling questions about medicine, use the medicine reminders list; for non-medicine events, use the general reminders list.
- All information you give about medicines or reminders must come only from these lists. Be accurate.

User's medicines (names from saved medicine reminders and any legacy entries):
{medicines_context}

User's medicine reminders (medicine, schedule, time, optional place, notes — only what they have added):
{reminders_context}

User's general reminders (non-medicine: title, schedule, time, optional place, notes — only what they have added):
{general_reminders_context}

Respond in a friendly, supportive way. If they mention adding a reminder or medicine, suggest they add it in the correct sidebar tab so it's saved."""


def build_medicines_context(session_id: str) -> str:
    items = medicine_list(session_id)
    if not items:
        return "None. The user has not added any medicines yet."
    return "\n".join(f"- {m['name']}" for m in items)


def build_reminders_context(session_id: str) -> str:
    items = reminder_list(session_id)
    if not items:
        return "None. The user has not added any medicine reminders yet."
    lines = []
    for r in items:
        sched = format_schedule_summary(
            r.get("schedule_type") or SCHEDULE_ONCE,
            r.get("schedule_detail") or "",
            r["date"],
        )
        place = (r.get("place") or "").strip()
        place_part = f", Place: {place}" if place else ""
        line = f"- Medicine: {r['medicine_type']}, Schedule: {sched}, Time: {r['time']}{place_part}"
        if r.get("notes"):
            line += f", Notes: {r['notes']}"
        lines.append(line)
    return "\n".join(lines)


def build_general_reminders_context(session_id: str) -> str:
    items = general_reminder_list(session_id)
    if not items:
        return "None. The user has not added any general reminders yet."
    lines = []
    for r in items:
        sched = format_schedule_summary(
            r.get("schedule_type") or SCHEDULE_ONCE,
            r.get("schedule_detail") or "",
            r["date"],
        )
        place = (r.get("place") or "").strip()
        place_part = f", Place: {place}" if place else ""
        line = f"- {r['title']}: Schedule: {sched}, Time: {r['time']}{place_part}"
        if r.get("notes"):
            line += f", Notes: {r['notes']}"
        lines.append(line)
    return "\n".join(lines)


def get_llm():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        st.error("OpenAI API key is not set. Go to the ⚙️ Settings tab in the sidebar and enter your key.")
        st.stop()
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.6, api_key=api_key)


def build_messages(session_id: str, user_message: str) -> list:
    medicines_context = build_medicines_context(session_id)
    reminders_context = build_reminders_context(session_id)
    general_reminders_context = build_general_reminders_context(session_id)
    system_content = PERSONA_SYSTEM.format(
        medicines_context=medicines_context,
        reminders_context=reminders_context,
        general_reminders_context=general_reminders_context,
    )
    messages = [SystemMessage(content=system_content)]

    history = get_chat_history(session_id)
    for h in history:
        if h["role"] == "user":
            messages.append(HumanMessage(content=h["content"]))
        else:
            messages.append(AIMessage(content=h["content"]))

    messages.append(HumanMessage(content=user_message))
    return messages


def chat_response(session_id: str, user_message: str) -> str:
    llm = get_llm()
    messages = build_messages(session_id, user_message)
    response = llm.invoke(messages)
    return response.content if hasattr(response, "content") else str(response)


def format_medicine_bottle_analysis(result: dict) -> str:
    """Turn vision JSON into readable markdown for chat."""
    parts: list[str] = []
    if result.get("parse_error"):
        parts.append(
            "**Could not parse structured details.** Showing raw model output when available.\n"
        )
    pkg = result.get("is_medicine_packaging")
    if pkg is not None:
        yn = "Yes" if pkg else "No"
        parts.append(f"- **Looks like medicine packaging:** {yn}")
    conf = result.get("confidence")
    if conf:
        parts.append(f"- **Confidence:** {conf}")
    labels = [
        ("what_it_appears_to_be", "Description"),
        ("active_ingredient_or_drug_name", "Name / active ingredient"),
        ("strength_and_form", "Strength & form"),
        ("stated_use_or_indications_from_label", "Stated use (from label)"),
        ("visible_warnings_or_cautions", "Warnings / cautions (visible)"),
        ("notes", "Notes"),
    ]
    for key, title in labels:
        val = result.get(key)
        if val:
            parts.append(f"- **{title}:** {val}")
    excerpts = result.get("readable_label_excerpts") or []
    if excerpts:
        joined = "; ".join(f'"{e}"' for e in excerpts if e)
        if joined:
            parts.append(f"- **Readable phrases from label:** {joined}")
    issues = result.get("issues_limiting_interpretation") or []
    if issues:
        parts.append(
            "- **Issues limiting interpretation:** "
            + "; ".join(str(i) for i in issues if i)
        )
    raw = result.get("raw_text") or ""
    if result.get("parse_error") and raw:
        snippet = raw if len(raw) <= 4000 else raw[:4000] + "\n…"
        parts.append(f"\n**Raw response:**\n```\n{snippet}\n```")
    if not parts and raw:
        return raw
    return "\n".join(parts) if parts else "_No details returned._"


# =============================================================================
# Streamlit UI
# =============================================================================
def show_welcome_screen():
    st.title("Welcome to CareBuddy")
    st.markdown(
        """
CareBuddy is a friendly assistant for **medicine reminders**, **general reminders** (appointments, errands, visits), and **daily wellness** chat.

**What you can do here**
- Add **medicine reminders** with a schedule: one-time, every day, weekly, every two weeks, or special days you describe.
- Add **general reminders** the same way — for anything that is not medicine.
- **Place** is optional for every reminder.
- Chat on the right: CareBuddy reads your saved reminders so answers stay accurate.

Use the button below when you are ready to continue.
        """
    )
    if st.button("Continue to CareBuddy", type="primary", use_container_width=True):
        st.session_state.welcome_done = True
        st.rerun()


def main():
    ensure_db()

    st.set_page_config(
        page_title="CareBuddy — Senior Care Assistant",
        page_icon="🌸",
        layout="centered",
    )

    if "welcome_done" not in st.session_state:
        st.session_state.welcome_done = False

    if not st.session_state.welcome_done:
        show_welcome_screen()
        return

    st.title("🌸 CareBuddy")
    st.caption("Your friendly assistant for medicine reminders, exercise, and daily wellness.")

    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    session_id = st.session_state.session_id

    if "messages" not in st.session_state:
        history = get_chat_history(session_id)
        st.session_state.messages = []
        for h in history:
            if h["role"] == "user":
                st.session_state.messages.append({"role": "user", "content": h["content"]})
            else:
                st.session_state.messages.append({"role": "assistant", "content": h["content"]})

    st.divider()
    st.subheader("Medicine label photo")
    st.caption(
        "Upload a clear photo of a bottle, box, or blister pack. CareBuddy describes the label "
        "for organizing only — not dosing. Always confirm with a pharmacist or doctor."
    )
    api_ok = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    ph_col1, ph_col2 = st.columns([1, 1])
    with ph_col1:
        top_med_upload = st.file_uploader(
            "Choose image",
            type=["png", "jpg", "jpeg", "webp", "gif"],
            key="medicine_bottle_uploader_top",
            label_visibility="visible",
        )
    with ph_col2:
        st.write("")  # align button under uploader
        st.write("")
        can_read = top_med_upload is not None and api_ok
        if st.button(
            "Read label & add to chat",
            type="primary",
            use_container_width=True,
            key="medicine_bottle_read_btn_top",
            disabled=not can_read,
        ):
            if top_med_upload is None:
                st.warning("Choose an image first.")
            elif not api_ok:
                st.warning("Open **Settings** in the sidebar and save your OpenAI API key first.")
            else:
                data = top_med_upload.getvalue()
                mime = top_med_upload.type or "image/jpeg"
                with st.spinner("Reading label…"):
                    try:
                        result = analyze_medicine_bottle_image_bytes(
                            data, mime_type=mime
                        )
                        analysis_md = format_medicine_bottle_analysis(result)
                        assistant_text = (
                            "**Label readout** (automated — verify with a pharmacist):\n\n"
                            + analysis_md
                        )
                        st.session_state.messages.append(
                            {
                                "role": "user",
                                "content": "🖼️ *Shared a medicine bottle photo*",
                                "image_bytes": data,
                                "mime": mime,
                            }
                        )
                        st.session_state.messages.append(
                            {"role": "assistant", "content": assistant_text}
                        )
                        log_message(session_id, "user", "[Medicine bottle photo]")
                        log_message(session_id, "assistant", assistant_text)
                        st.success("Added to your chat below.")
                    except Exception as e:
                        st.error(f"Could not read the image: {e}")
    if top_med_upload is not None:
        st.image(top_med_upload, width=200, caption="Preview")
    if not api_ok:
        st.info("Tip: save your API key under **Sidebar → Settings** to enable photo reading.")
    st.divider()

    if "med_add_version" not in st.session_state:
        st.session_state.med_add_version = 0
    if "gen_add_version" not in st.session_state:
        st.session_state.gen_add_version = 0

    sched_keys = list(SCHEDULE_LABELS.keys())

    with st.sidebar:
        tab_med, tab_gen, tab_settings = st.tabs(["💊 Medicine", "📋 General", "⚙️ Settings"])

        with tab_med:
            st.caption("**Saved** = what you already stored. **Add new** resets after each save (blank medicine, one-time @ 9:00 — choose your date).")
            reminders = reminder_list(session_id)

            st.subheader("Saved")
            if reminders:
                for r in reminders:
                    rid = r["id"]
                    sched = format_schedule_summary(
                        r.get("schedule_type") or SCHEDULE_ONCE,
                        r.get("schedule_detail") or "",
                        r["date"],
                    )
                    place_str = f" · {r['place']}" if (r.get("place") or "").strip() else ""
                    st.markdown(f"**{r['medicine_type']}**  \n{sched} · {r['time']}{place_str}")
                    if r.get("notes"):
                        st.caption(f"Notes: {r['notes']}")
                    with st.expander("Edit this reminder"):
                        st.markdown("**When**")
                        e_med = st.text_input(
                            "Medicine",
                            value=r["medicine_type"],
                            key=f"em_{rid}_name",
                        )
                        erow_sched, erow_time = st.columns([1.25, 1])
                        with erow_sched:
                            e_sched = st.selectbox(
                                "How often",
                                options=sched_keys,
                                index=schedule_type_index(sched_keys, r.get("schedule_type") or SCHEDULE_ONCE),
                                format_func=lambda k: SCHEDULE_LABELS[k],
                                key=f"em_{rid}_sched",
                            )
                        with erow_time:
                            e_time = st.time_input(
                                "Time",
                                value=parse_stored_time(r["time"]),
                                key=f"em_{rid}_time",
                            )
                        e_weekday = None
                        e_special = ""
                        if e_sched == SCHEDULE_WEEKLY:
                            ec_dow, ec_ref = st.columns([1, 1])
                            with ec_dow:
                                e_weekday = st.selectbox(
                                    "Which day",
                                    options=WEEKDAYS,
                                    index=weekday_index(r.get("schedule_detail") or ""),
                                    key=f"em_{rid}_dow",
                                )
                            with ec_ref:
                                e_date = st.date_input(
                                    DATE_LABEL_FOR_SCHEDULE[e_sched],
                                    value=parse_stored_date(r["date"]),
                                    key=f"em_{rid}_date",
                                )
                        elif e_sched == SCHEDULE_SPECIAL:
                            e_date = st.date_input(
                                DATE_LABEL_FOR_SCHEDULE[e_sched],
                                value=parse_stored_date(r["date"]),
                                key=f"em_{rid}_date",
                            )
                            e_special = st.text_area(
                                "Describe when (e.g. Mon/Wed/Fri, or 1st of month)",
                                value=r.get("schedule_detail") or "",
                                key=f"em_{rid}_special",
                                height=88,
                            )
                        else:
                            e_date = st.date_input(
                                DATE_LABEL_FOR_SCHEDULE[e_sched],
                                value=parse_stored_date(r["date"]),
                                key=f"em_{rid}_date",
                            )
                        e_place = st.text_input(
                            "Place (optional)",
                            value=r.get("place") or "",
                            key=f"em_{rid}_place",
                        )
                        e_notes = st.text_input(
                            "Notes (optional)",
                            value=r.get("notes") or "",
                            key=f"em_{rid}_notes",
                        )
                        bsave, bdel = st.columns(2)
                        with bsave:
                            if st.button("Save changes", key=f"em_{rid}_save"):
                                detail = ""
                                if e_sched == SCHEDULE_WEEKLY:
                                    detail = e_weekday or ""
                                elif e_sched == SCHEDULE_SPECIAL:
                                    detail = (e_special or "").strip()
                                if e_sched == SCHEDULE_SPECIAL and not detail:
                                    st.warning("Please describe when this happens.")
                                elif not (e_med or "").strip():
                                    st.warning("Please enter a medicine name.")
                                else:
                                    reminder_update(
                                        session_id,
                                        rid,
                                        str(e_date),
                                        e_time.strftime("%H:%M"),
                                        e_place,
                                        e_med.strip(),
                                        e_notes or "",
                                        schedule_type=e_sched,
                                        schedule_detail=detail,
                                    )
                                    clear_edit_key_prefix(f"em_{rid}_")
                                    st.success("Updated.")
                                    st.rerun()
                        with bdel:
                            if st.button("Delete", key=f"em_{rid}_del"):
                                reminder_delete(session_id, rid)
                                clear_edit_key_prefix(f"em_{rid}_")
                                st.rerun()
                    st.divider()
            else:
                st.caption("No saved reminders yet.")

            st.subheader("Add new")
            mv = st.session_state.med_add_version
            ensure_new_med_add_defaults(mv)
            with st.expander("New reminder (starts empty after each save)", expanded=True):
                rem_med = st.text_input(
                    "Medicine",
                    key=f"rem_type_{mv}",
                    placeholder="e.g. Blood pressure pill",
                )
                with st.container():
                    st.markdown("**When**")
                    st.caption(
                        "Defaults for a new row: **One-time** and **9:00 AM**. Open the calendar to set the date."
                    )
                    row_sched, row_time = st.columns([1.25, 1])
                    with row_sched:
                        med_sched = st.selectbox(
                            "How often",
                            options=sched_keys,
                            format_func=lambda k: SCHEDULE_LABELS[k],
                            key=f"med_sched_{mv}",
                        )
                    with row_time:
                        rem_time = st.time_input("Time", key=f"rem_time_{mv}")
                    med_weekday = None
                    med_special = ""
                    if med_sched == SCHEDULE_WEEKLY:
                        col_dow, col_ref = st.columns([1, 1])
                        with col_dow:
                            med_weekday = st.selectbox(
                                "Which day", options=WEEKDAYS, key=f"med_weekday_{mv}"
                            )
                        with col_ref:
                            rem_date = st.date_input(
                                DATE_LABEL_FOR_SCHEDULE[med_sched],
                                key=f"rem_date_{mv}",
                            )
                    elif med_sched == SCHEDULE_SPECIAL:
                        rem_date = st.date_input(
                            DATE_LABEL_FOR_SCHEDULE[med_sched],
                            key=f"rem_date_{mv}",
                        )
                        med_special = st.text_area(
                            "Describe when (e.g. Mon/Wed/Fri, or 1st of month)",
                            key=f"med_special_{mv}",
                            placeholder="Be as specific as you like.",
                            height=88,
                        )
                    else:
                        rem_date = st.date_input(
                            DATE_LABEL_FOR_SCHEDULE[med_sched],
                            key=f"rem_date_{mv}",
                        )
                rem_place = st.text_input(
                    "Place (optional)",
                    key=f"rem_place_{mv}",
                    placeholder="e.g. Kitchen — leave blank if not needed",
                )
                rem_notes = st.text_input(
                    "Notes (optional)",
                    key=f"rem_notes_{mv}",
                    placeholder="e.g. Take with water",
                )
                if st.button("Save reminder", key=f"add_rem_{mv}"):
                    detail = ""
                    if med_sched == SCHEDULE_WEEKLY:
                        detail = med_weekday or ""
                    elif med_sched == SCHEDULE_SPECIAL:
                        detail = (med_special or "").strip()
                    if med_sched == SCHEDULE_SPECIAL and not detail:
                        st.warning("Please describe when this happens under Special days.")
                    elif not (rem_med or "").strip():
                        st.warning("Please enter a medicine name.")
                    else:
                        reminder_add(
                            session_id,
                            str(rem_date),
                            rem_time.strftime("%H:%M"),
                            rem_place,
                            rem_med.strip(),
                            rem_notes or "",
                            schedule_type=med_sched,
                            schedule_detail=detail,
                        )
                        st.session_state.med_add_version = mv + 1
                        st.success("Saved. The assistant can see this reminder.")
                        st.rerun()

        with tab_gen:
            st.caption(
                "**Saved** = stored items you can edit. **Add new** resets after each save (blank title, one-time @ 9:00 — choose your date)."
            )
            gen_list = general_reminder_list(session_id)

            st.subheader("Saved")
            if gen_list:
                for g in gen_list:
                    gid = g["id"]
                    sched = format_schedule_summary(
                        g.get("schedule_type") or SCHEDULE_ONCE,
                        g.get("schedule_detail") or "",
                        g["date"],
                    )
                    place_str = f" · {g['place']}" if (g.get("place") or "").strip() else ""
                    st.markdown(f"**{g['title']}**  \n{sched} · {g['time']}{place_str}")
                    if g.get("notes"):
                        st.caption(f"Notes: {g['notes']}")
                    with st.expander("Edit this reminder"):
                        st.markdown("**When**")
                        g_title = st.text_input(
                            "What / title",
                            value=g["title"],
                            key=f"eg_{gid}_title",
                        )
                        grow_sched, grow_time = st.columns([1.25, 1])
                        with grow_sched:
                            g_sched = st.selectbox(
                                "How often",
                                options=sched_keys,
                                index=schedule_type_index(sched_keys, g.get("schedule_type") or SCHEDULE_ONCE),
                                format_func=lambda k: SCHEDULE_LABELS[k],
                                key=f"eg_{gid}_sched",
                            )
                        with grow_time:
                            g_time = st.time_input(
                                "Time",
                                value=parse_stored_time(g["time"]),
                                key=f"eg_{gid}_time",
                            )
                        g_weekday = None
                        g_special = ""
                        if g_sched == SCHEDULE_WEEKLY:
                            gc_dow, gc_ref = st.columns([1, 1])
                            with gc_dow:
                                g_weekday = st.selectbox(
                                    "Which day",
                                    options=WEEKDAYS,
                                    index=weekday_index(g.get("schedule_detail") or ""),
                                    key=f"eg_{gid}_dow",
                                )
                            with gc_ref:
                                g_date = st.date_input(
                                    DATE_LABEL_FOR_SCHEDULE[g_sched],
                                    value=parse_stored_date(g["date"]),
                                    key=f"eg_{gid}_date",
                                )
                        elif g_sched == SCHEDULE_SPECIAL:
                            g_date = st.date_input(
                                DATE_LABEL_FOR_SCHEDULE[g_sched],
                                value=parse_stored_date(g["date"]),
                                key=f"eg_{gid}_date",
                            )
                            g_special = st.text_area(
                                "Describe when",
                                value=g.get("schedule_detail") or "",
                                key=f"eg_{gid}_special",
                                height=88,
                            )
                        else:
                            g_date = st.date_input(
                                DATE_LABEL_FOR_SCHEDULE[g_sched],
                                value=parse_stored_date(g["date"]),
                                key=f"eg_{gid}_date",
                            )
                        g_place = st.text_input(
                            "Place (optional)",
                            value=g.get("place") or "",
                            key=f"eg_{gid}_place",
                        )
                        g_notes = st.text_input(
                            "Notes (optional)",
                            value=g.get("notes") or "",
                            key=f"eg_{gid}_notes",
                        )
                        gsave, gdel = st.columns(2)
                        with gsave:
                            if st.button("Save changes", key=f"eg_{gid}_save"):
                                detail = ""
                                if g_sched == SCHEDULE_WEEKLY:
                                    detail = g_weekday or ""
                                elif g_sched == SCHEDULE_SPECIAL:
                                    detail = (g_special or "").strip()
                                if g_sched == SCHEDULE_SPECIAL and not detail:
                                    st.warning("Please describe when this happens.")
                                elif not (g_title or "").strip():
                                    st.warning("Please enter a title.")
                                else:
                                    general_reminder_update(
                                        session_id,
                                        gid,
                                        g_title.strip(),
                                        str(g_date),
                                        g_time.strftime("%H:%M"),
                                        g_place,
                                        g_notes or "",
                                        schedule_type=g_sched,
                                        schedule_detail=detail,
                                    )
                                    clear_edit_key_prefix(f"eg_{gid}_")
                                    st.success("Updated.")
                                    st.rerun()
                        with gdel:
                            if st.button("Delete", key=f"eg_{gid}_del"):
                                general_reminder_delete(session_id, gid)
                                clear_edit_key_prefix(f"eg_{gid}_")
                                st.rerun()
                    st.divider()
            else:
                st.caption("No saved general reminders yet.")

            st.subheader("Add new")
            gv = st.session_state.gen_add_version
            ensure_new_gen_add_defaults(gv)
            with st.expander("New general reminder (starts empty after each save)", expanded=True):
                gen_title = st.text_input(
                    "What / title",
                    key=f"gen_title_{gv}",
                    placeholder="e.g. Doctor visit, call Sarah",
                )
                with st.container():
                    st.markdown("**When**")
                    st.caption(
                        "Defaults for a new row: **One-time** and **9:00 AM**. Open the calendar to set the date."
                    )
                    g_row_sched, g_row_time = st.columns([1.25, 1])
                    with g_row_sched:
                        gen_sched = st.selectbox(
                            "How often",
                            options=sched_keys,
                            format_func=lambda k: SCHEDULE_LABELS[k],
                            key=f"gen_sched_{gv}",
                        )
                    with g_row_time:
                        gen_time = st.time_input("Time", key=f"gen_time_{gv}")
                    gen_weekday = None
                    gen_special = ""
                    if gen_sched == SCHEDULE_WEEKLY:
                        g_col_dow, g_col_ref = st.columns([1, 1])
                        with g_col_dow:
                            gen_weekday = st.selectbox(
                                "Which day", options=WEEKDAYS, key=f"gen_weekday_{gv}"
                            )
                        with g_col_ref:
                            gen_date = st.date_input(
                                DATE_LABEL_FOR_SCHEDULE[gen_sched],
                                key=f"gen_date_{gv}",
                            )
                    elif gen_sched == SCHEDULE_SPECIAL:
                        gen_date = st.date_input(
                            DATE_LABEL_FOR_SCHEDULE[gen_sched],
                            key=f"gen_date_{gv}",
                        )
                        gen_special = st.text_area(
                            "Describe when",
                            key=f"gen_special_{gv}",
                            placeholder="e.g. Every other Thursday, or holidays only",
                            height=88,
                        )
                    else:
                        gen_date = st.date_input(
                            DATE_LABEL_FOR_SCHEDULE[gen_sched],
                            key=f"gen_date_{gv}",
                        )
                gen_place = st.text_input(
                    "Place (optional)",
                    key=f"gen_place_{gv}",
                    placeholder="e.g. Clinic — leave blank if not needed",
                )
                gen_notes = st.text_input(
                    "Notes (optional)",
                    key=f"gen_notes_{gv}",
                    placeholder="e.g. Bring insurance card",
                )
                if st.button("Save reminder", key=f"add_gen_{gv}"):
                    detail = ""
                    if gen_sched == SCHEDULE_WEEKLY:
                        detail = gen_weekday or ""
                    elif gen_sched == SCHEDULE_SPECIAL:
                        detail = (gen_special or "").strip()
                    if not (gen_title or "").strip():
                        st.warning("Please enter a title or what to remember.")
                    elif gen_sched == SCHEDULE_SPECIAL and not detail:
                        st.warning("Please describe when this happens under Special days.")
                    else:
                        general_reminder_add(
                            session_id,
                            gen_title.strip(),
                            str(gen_date),
                            gen_time.strftime("%H:%M"),
                            gen_place,
                            gen_notes or "",
                            schedule_type=gen_sched,
                            schedule_detail=detail,
                        )
                        st.session_state.gen_add_version = gv + 1
                        st.success("Saved. The assistant can see this reminder.")
                        st.rerun()

        with tab_settings:
            st.subheader("OpenAI API Key")
            st.caption("Your key is stored only in memory for this session — it is never written to disk or code.")
            current_key = os.environ.get("OPENAI_API_KEY", "")
            new_key = st.text_input(
                "API Key",
                value=current_key,
                type="password",
                placeholder="sk-...",
                key="settings_api_key_input",
            )
            if st.button("Save Key", key="settings_save_key"):
                stripped = new_key.strip()
                if stripped:
                    os.environ["OPENAI_API_KEY"] = stripped
                    st.success("Key saved for this session.")
                else:
                    st.warning("Please enter a valid API key.")
            if current_key:
                st.caption(f"Key is set: `{current_key[:8]}...`")
            else:
                st.warning("No API key set. The chat won't work until you save one.")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg.get("image_bytes"):
                st.image(io.BytesIO(msg["image_bytes"]), width=min(320, 400))
            st.markdown(msg["content"])

    if prompt := st.chat_input("Type your message..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        log_message(session_id, "user", prompt)

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    reply = chat_response(session_id, prompt)
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    log_message(session_id, "assistant", reply)
                except Exception as e:
                    st.error(f"Something went wrong: {e}")


if __name__ == "__main__":
    main()
