"""
Shared chat / LLM helpers for CareBuddy (Streamlit bot and FastAPI).
"""

from __future__ import annotations

import os

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from services.persona import Persona
from services.reminders import list_medicines, list_reminders
from services.db import connect, now_iso


def log_message(session_id: str, role: str, content: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_log (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now_iso()),
    )
    conn.commit()
    conn.close()


def get_chat_history(session_id: str, limit: int = 100) -> list[dict]:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content FROM chat_log WHERE session_id = ? ORDER BY id ASC LIMIT ?",
        (session_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def resolve_openai_key(explicit: str | None = None) -> str:
    return (explicit or os.environ.get("OPENAI_API_KEY", "") or "").strip()


def get_llm(api_key: str | None = None) -> ChatOpenAI:
    key = resolve_openai_key(api_key)
    if not key:
        raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY or provide it in settings.")
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.4, api_key=key)


def _reminder_style_instructions(style: str) -> str:
    s = (style or "gentle").lower()
    mapping = {
        "gentle": "Use warm, patient language; short sentences; avoid sounding rushed.",
        "direct": "Be clear and concise; state the next step plainly without extra fluff.",
        "encouraging": "Be upbeat and supportive; celebrate small wins when appropriate.",
        "short": "Keep replies very brief (a few sentences max) unless the user asks for detail.",
    }
    return mapping.get(s, mapping["gentle"])


def _persona_prompt_block(persona: Persona) -> str:
    name = persona.name or "the user"
    age = persona.age or "unknown"
    return (
        "User profile for personalization:\n"
        f"- Name: {name}\n"
        f"- Age: {age}\n"
        f"- Language preference: {persona.language}\n"
        f"- Timezone: {persona.timezone}\n"
        f"- Reminder style: {persona.reminder_style}\n"
        f"- Style instructions: {_reminder_style_instructions(persona.reminder_style)}\n"
    )


def build_messages(session_id: str, user_message: str, persona: Persona) -> list:
    reminders = list_reminders(session_id)
    meds = list_medicines(session_id)
    reminders_ctx = "\n".join(
        f"- [{r['kind']}] {r['title']} @ {r['reminder_date']} {r['reminder_time']} ({r['status']})"
        for r in reminders[:80]
    ) or "None"
    meds_ctx = ", ".join(meds) if meds else "None"
    system = (
        "You are CareBuddy, a calm assistant for older adults.\n"
        "Give simple, clear guidance and never provide medical diagnosis.\n"
        "When discussing medicines, suggest label verification with a pharmacist.\n"
        "Keep response language aligned with the user's preferred language.\n"
        "If the user asks to create or change a reminder, restate title, date, time, and type (medicine vs general) clearly.\n\n"
        + _persona_prompt_block(persona)
        + f"\nUser medicines: {meds_ctx}\nUser reminders:\n{reminders_ctx}"
    )
    messages = [SystemMessage(content=system)]
    for h in get_chat_history(session_id):
        if h["role"] == "user":
            messages.append(HumanMessage(content=h["content"]))
        else:
            messages.append(AIMessage(content=h["content"]))
    messages.append(HumanMessage(content=user_message))
    return messages


def _translator_for_persona(persona: Persona, api_key: str | None = None):
    from services.phase2_interfaces import OpenAITranslator, PassthroughTranslator

    lang = (persona.language or "").strip().lower()
    if lang in ("english", "en", ""):
        return PassthroughTranslator()
    try:
        return OpenAITranslator(api_key=resolve_openai_key(api_key))
    except ValueError:
        return PassthroughTranslator()


def chat_response(session_id: str, user_message: str, persona: Persona, api_key: str | None = None) -> str:
    llm = get_llm(api_key)
    translator = _translator_for_persona(persona, api_key)
    normalized = translator.to_english(user_message, persona.language)
    out = llm.invoke(build_messages(session_id, normalized, persona))
    text = out.content if hasattr(out, "content") else str(out)
    return translator.from_english(text, persona.language)


def format_medicine_bottle_analysis(result: dict) -> str:
    lines = []
    if result.get("is_medicine_packaging") is not None:
        lines.append(
            f"- Looks like medicine packaging: {'Yes' if result['is_medicine_packaging'] else 'No'}"
        )
    for key, label in [
        ("active_ingredient_or_drug_name", "Name or active ingredient"),
        ("strength_and_form", "Strength and form"),
        ("visible_warnings_or_cautions", "Visible cautions"),
        ("notes", "Notes"),
    ]:
        val = result.get(key)
        if val:
            lines.append(f"- {label}: {val}")
    excerpts = result.get("readable_label_excerpts") or []
    if excerpts:
        lines.append(f"- Label text: {'; '.join(excerpts[:5])}")
    return "\n".join(lines) if lines else (result.get("raw_text") or "No details.")
