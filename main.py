"""
CareBuddy FastAPI server: REST API + static web UI.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from medicine_bottle_vision import analyze_medicine_bottle_image_bytes
from services.calendar_view import daily_view_events, weekly_view_events
from services.chat_core import (
    chat_response,
    format_medicine_bottle_analysis,
    get_chat_history,
    log_message,
    resolve_openai_key,
)
from services.db import ensure_db
from services.medicine_info import detect_medicine_name, get_medicine_guidance
from services.persona import Persona, get_persona, save_persona
from services.phase2_interfaces import (
    EmailNotificationProvider,
    NtfyNotificationProvider,
    TwilioNotificationProvider,
)
from services.reminders import (
    SCHEDULE_BIWEEKLY,
    SCHEDULE_DAILY,
    SCHEDULE_ONCE,
    SCHEDULE_SPECIAL,
    SCHEDULE_WEEKLY,
    add_reminder,
    delete_reminder,
    format_schedule_summary,
    list_reminders,
    next_reminder,
    update_reminder,
)
from services.summary import build_daily_summary, save_daily_summary

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

SCHEDULE_LABELS: dict[str, str] = {
    SCHEDULE_ONCE: "One-time",
    SCHEDULE_DAILY: "Daily",
    SCHEDULE_WEEKLY: "Weekly",
    SCHEDULE_BIWEEKLY: "Every two weeks",
    SCHEDULE_SPECIAL: "Special days",
}

LANGUAGES = ["English", "Spanish", "French", "Hindi", "Urdu", "Arabic"]
REMINDER_STYLES = ["gentle", "direct", "encouraging", "short"]

# Per-session overrides (server env OPENAI_API_KEY is preferred for production)
_session_openai_keys: dict[str, str] = {}
_session_notifications: dict[str, tuple[str, str]] = {}  # session_id -> (channel, destination)


def _notify_due_reminders(session_id: str, destination: str, channel: str) -> None:
    if not destination:
        return
    providers = {
        "email": EmailNotificationProvider(),
        "twilio": TwilioNotificationProvider(),
        "ntfy": NtfyNotificationProvider(),
    }
    provider = providers.get(channel)
    if not provider:
        return
    now = datetime.now()
    for r in list_reminders(session_id):
        try:
            dt = datetime.fromisoformat(f"{r['reminder_date']}T{r['reminder_time']}:00")
        except ValueError:
            continue
        if abs((dt - now).total_seconds()) <= 60 and r["status"] == "pending":
            provider.send(destination, f"Reminder: {r['title']} at {r['reminder_time']}")


def get_session_openai_key(session_id: str) -> str | None:
    return _session_openai_keys.get(session_id) or None


def _mask_openai_key(key: str | None) -> str:
    if not key:
        return ""
    visible = key[:10]
    hidden_len = max(len(key) - 10, 0)
    return visible + ("*" * hidden_len)


def resolve_key_for_session(session_id: str) -> str:
    return resolve_openai_key(get_session_openai_key(session_id))


def require_session_id(x_session_id: str | None = Header(None, alias="X-Session-Id")) -> str:
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(status_code=400, detail="Missing X-Session-Id header")
    return x_session_id.strip()


app = FastAPI(title="CareBuddy API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PersonaOut(BaseModel):
    name: str = ""
    age: str = ""
    language: str = "English"
    timezone: str = "UTC"
    reminder_style: str = "gentle"


class PersonaUpdate(BaseModel):
    name: str = ""
    age: str = ""
    language: str = "English"
    timezone: str = "UTC"
    reminder_style: str = "gentle"
    openai_api_key: str | None = None
    notification_channel: str = "email"
    notification_destination: str = ""


class ReminderCreate(BaseModel):
    kind: str = "medicine"
    title: str
    reminder_date: str
    reminder_time: str
    place: str = ""
    notes: str = ""
    schedule_type: str = SCHEDULE_ONCE
    schedule_detail: str = ""


class ReminderPatch(BaseModel):
    kind: str | None = None
    title: str | None = None
    reminder_date: str | None = None
    reminder_time: str | None = None
    place: str | None = None
    notes: str | None = None
    schedule_type: str | None = None
    schedule_detail: str | None = None
    status: str | None = None


class ChatMessageIn(BaseModel):
    message: str = Field(..., min_length=1)


def _row_to_dict(r: dict) -> dict:
    d = dict(r)
    d["schedule_summary"] = format_schedule_summary(
        d.get("schedule_type") or "",
        d.get("schedule_detail") or "",
        d.get("reminder_date") or "",
    )
    return d


@app.on_event("startup")
def _startup() -> None:
    ensure_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "schedule_labels": SCHEDULE_LABELS,
        "languages": LANGUAGES,
        "reminder_styles": REMINDER_STYLES,
        "schedule_keys": list(SCHEDULE_LABELS.keys()),
    }


@app.get("/api/bootstrap")
def bootstrap(session_id: str | None = None) -> dict:
    sid = (session_id or "").strip() or str(uuid.uuid4())
    persona = get_persona(sid)
    notif_ch, notif_dest = _session_notifications.get(sid, ("email", ""))
    masked_session_key = _mask_openai_key(get_session_openai_key(sid))
    return {
        "session_id": sid,
        "persona": PersonaOut(
            name=persona.name,
            age=persona.age,
            language=persona.language,
            timezone=persona.timezone,
            reminder_style=persona.reminder_style,
        ),
        "notification_channel": notif_ch,
        "notification_destination": notif_dest,
        "has_server_openai_key": bool(resolve_openai_key(None)),
        "masked_openai_api_key": masked_session_key,
    }


@app.get("/api/persona", response_model=PersonaOut)
def api_get_persona(session_id: str = Depends(require_session_id)) -> PersonaOut:
    p = get_persona(session_id)
    return PersonaOut(
        name=p.name,
        age=p.age,
        language=p.language,
        timezone=p.timezone,
        reminder_style=p.reminder_style,
    )


@app.put("/api/persona")
def api_put_persona(body: PersonaUpdate, session_id: str = Depends(require_session_id)) -> dict:
    save_persona(
        session_id,
        Persona(
            name=body.name.strip(),
            age=body.age.strip(),
            language=body.language,
            timezone=body.timezone.strip() or "UTC",
            reminder_style=body.reminder_style,
        ),
    )
    if body.openai_api_key is not None and body.openai_api_key.strip():
        _session_openai_keys[session_id] = body.openai_api_key.strip()
    _session_notifications[session_id] = (body.notification_channel.strip() or "email", body.notification_destination.strip())
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(session_id: str = Depends(require_session_id)) -> dict:
    ch, dest = _session_notifications.get(session_id, ("email", ""))
    _notify_due_reminders(session_id, dest, ch)
    persona = get_persona(session_id)
    nr = next_reminder(session_id)
    today_iso = date.today().isoformat()
    todays = [r for r in list_reminders(session_id) if r["reminder_date"] == today_iso]
    summary = build_daily_summary(session_id, date.today())
    save_daily_summary(session_id, date.today(), summary)
    return {
        "persona": PersonaOut(
            name=persona.name,
            age=persona.age,
            language=persona.language,
            timezone=persona.timezone,
            reminder_style=persona.reminder_style,
        ),
        "next_reminder": _row_to_dict(nr) if nr else None,
        "today_reminders": [_row_to_dict(dict(r)) for r in todays],
        "daily_summary": summary,
    }


@app.get("/api/reminders", response_model=list[dict])
def api_list_reminders(session_id: str = Depends(require_session_id)) -> list[dict]:
    return [_row_to_dict(dict(r)) for r in list_reminders(session_id)]


@app.post("/api/reminders")
def api_add_reminder(body: ReminderCreate, session_id: str = Depends(require_session_id)) -> dict:
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    add_reminder(
        session_id,
        kind=body.kind,
        title=body.title.strip(),
        reminder_date=body.reminder_date,
        reminder_time=body.reminder_time,
        place=body.place,
        notes=body.notes,
        schedule_type=body.schedule_type,
        schedule_detail=body.schedule_detail,
    )
    return {"ok": True}


@app.patch("/api/reminders/{reminder_id}")
def api_patch_reminder(
    reminder_id: int,
    body: ReminderPatch,
    session_id: str = Depends(require_session_id),
) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return {"ok": True}
    update_reminder(session_id, reminder_id, **fields)
    return {"ok": True}


@app.delete("/api/reminders/{reminder_id}")
def api_delete_reminder(reminder_id: int, session_id: str = Depends(require_session_id)) -> dict:
    delete_reminder(session_id, reminder_id)
    return {"ok": True}


@app.get("/api/calendar/daily")
def api_calendar_daily(
    date_str: str | None = None,
    session_id: str = Depends(require_session_id),
) -> dict:
    d = date.fromisoformat(date_str) if date_str else date.today()
    rows = daily_view_events(session_id, d)
    return {"date": d.isoformat(), "reminders": [_row_to_dict(dict(r)) for r in rows]}


@app.get("/api/calendar/weekly")
def api_calendar_weekly(
    start: str | None = None,
    session_id: str = Depends(require_session_id),
) -> dict:
    if start:
        start_day = date.fromisoformat(start)
    else:
        today = date.today()
        start_day = today - timedelta(days=today.weekday())
    days_out = []
    for day_iso, rows in weekly_view_events(session_id, start_day):
        days_out.append(
            {
                "date": day_iso,
                "reminders": [_row_to_dict(dict(r)) for r in rows],
            }
        )
    return {"week_start": start_day.isoformat(), "days": days_out}


@app.get("/api/chat/history")
def api_chat_history(session_id: str = Depends(require_session_id)) -> dict:
    return {"messages": get_chat_history(session_id)}


@app.post("/api/chat")
def api_chat(body: ChatMessageIn, session_id: str = Depends(require_session_id)) -> dict:
    key = resolve_key_for_session(session_id)
    if not key:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured. Set OPENAI_API_KEY on the server or save "
            "one in Settings.",
        )
    persona = get_persona(session_id)
    log_message(session_id, "user", body.message)
    try:
        reply = chat_response(session_id, body.message, persona, api_key=key)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    med = detect_medicine_name(body.message + " " + reply)
    guidance = get_medicine_guidance(med)
    if guidance:
        reply += (
            "\n\n**Simple medicine info**\n"
            f"- How to take: {guidance['how_to_take']}\n"
            f"- Precautions: {guidance['precautions']}\n"
            "- Verify details with your pharmacist or prescriber."
        )
    log_message(session_id, "assistant", reply)
    return {"reply": reply}


@app.post("/api/chat/image")
async def api_chat_image(
    session_id: str = Depends(require_session_id),
    file: UploadFile = File(...),
) -> dict:
    key = resolve_key_for_session(session_id)
    if not key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured.")
    raw = await file.read()
    mime = file.content_type or "image/jpeg"
    try:
        result = analyze_medicine_bottle_image_bytes(raw, mime_type=mime, api_key=key)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    assistant_text = format_medicine_bottle_analysis(result)
    med = detect_medicine_name(assistant_text)
    guidance = get_medicine_guidance(med)
    if guidance:
        assistant_text += (
            "\n\n**Simple medicine info**\n"
            f"- How to take: {guidance['how_to_take']}\n"
            f"- Precautions: {guidance['precautions']}\n"
            "- Verify details with your pharmacist or prescriber."
        )
    log_message(session_id, "user", "[Image uploaded]")
    log_message(session_id, "assistant", assistant_text)
    return {"reply": assistant_text}


# Mount static files and SPA fallback
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_index() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="UI not built. Add static/index.html")
    return FileResponse(index)


@app.get("/onboarding")
@app.get("/today")
@app.get("/medications")
@app.get("/appointments")
@app.get("/progress")
@app.get("/assistant")
@app.get("/settings")
@app.get("/family")
@app.get("/family/alerts")
@app.get("/family/settings")
async def serve_spa_routes() -> FileResponse:
    return await serve_index()
