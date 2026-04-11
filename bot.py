from __future__ import annotations

import io
import os
import uuid
from datetime import date, datetime, timedelta

import streamlit as st

from medicine_bottle_vision import analyze_medicine_bottle_image_bytes
from services.chat_core import (
    chat_response as chat_response_core,
    format_medicine_bottle_analysis,
    get_chat_history,
    log_message,
)
from services.calendar_view import daily_view_events, weekly_view_events
from services.db import ensure_db
from services.medicine_info import (
    detect_medicine_name,
    get_medicine_guidance,
    get_medicine_guidance_llm,
)
from services.notifications import notify_due_reminders
from services.persona import Persona, get_persona, save_persona
from services.phase2_interfaces import (
    EmailNotificationProvider,
    NtfyNotificationProvider,
    TwilioNotificationProvider,
    WhisperVoiceProvider,
)
from services.reminder_parse import try_parse_reminder_from_text
from services.reminders import (
    SCHEDULE_BIWEEKLY,
    SCHEDULE_DAILY,
    SCHEDULE_ONCE,
    SCHEDULE_SPECIAL,
    SCHEDULE_WEEKLY,
    add_reminder,
    delete_reminder,
    format_schedule_summary,
    is_completed_for_day,
    list_reminders,
    mark_completed_for_day,
    next_reminder,
    reminders_for_day,
    unmark_completed_for_day,
    update_reminder,
)
from services.summary import build_daily_summary, save_daily_summary

SCHEDULE_LABELS = {
    SCHEDULE_ONCE: "One-time",
    SCHEDULE_DAILY: "Daily",
    SCHEDULE_WEEKLY: "Weekly",
    SCHEDULE_BIWEEKLY: "Every two weeks",
    SCHEDULE_SPECIAL: "Special days",
}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LANGUAGES = ["English", "Spanish", "French", "Hindi", "Urdu", "Arabic"]
REMINDER_STYLES = ["gentle", "direct", "encouraging", "short"]


def _append_medicine_info(text: str, api_key: str) -> str:
    med = detect_medicine_name(text)
    guidance = get_medicine_guidance(med) if med else None
    if not guidance and med and api_key:
        guidance = get_medicine_guidance_llm(med, api_key)
    if not guidance:
        return text
    return (
        text
        + "\n\n**Simple medicine info**\n"
        f"- How to take: {guidance['how_to_take']}\n"
        f"- Precautions: {guidance['precautions']}\n"
        "- Verify details with your pharmacist or prescriber."
    )


def _vision_medicine_hint(result: dict) -> str | None:
    for k in ("active_ingredient_or_drug_name", "what_it_appears_to_be"):
        v = (result.get(k) or "").strip()
        if v:
            return v
    return None


def render_sidebar(session_id: str, persona: Persona) -> Persona:
    st.sidebar.header("Dashboard")
    nr = next_reminder(session_id)
    if nr:
        st.sidebar.info(
            f"Next: {nr['title']} on {nr['reminder_date']} at {nr['reminder_time']}"
        )
    else:
        st.sidebar.caption("No upcoming reminders.")

    upcoming = list_reminders(session_id)[:8]
    if upcoming:
        st.sidebar.caption("Upcoming saved reminders")
        for r in upcoming:
            st.sidebar.write(
                f"· {r['title']} — {format_schedule_summary(r['schedule_type'], r['schedule_detail'], r['reminder_date'])} @ {r['reminder_time']}"
            )

    st.sidebar.header("Reminders")
    if st.sidebar.button("Add Reminder", use_container_width=True):
        st.session_state.show_add_reminder = True
    if st.session_state.get("show_add_reminder"):
        with st.sidebar.form("add_reminder_form", clear_on_submit=True):
            kind = st.selectbox("Type", ["medicine", "general"])
            title = st.text_input("Title / Medicine")
            r_date = st.date_input("Date", value=date.today())
            r_time = st.time_input("Time")
            place = st.text_input("Place")
            notes = st.text_input("Notes")
            sched = st.selectbox(
                "Schedule",
                list(SCHEDULE_LABELS.keys()),
                format_func=lambda x: SCHEDULE_LABELS[x],
            )
            sdetail = st.text_input("Schedule detail (weekday / special description)")
            submitted = st.form_submit_button("Save Reminder", type="primary")
            if submitted:
                if title.strip():
                    add_reminder(
                        session_id,
                        kind=kind,
                        title=title,
                        reminder_date=r_date.isoformat(),
                        reminder_time=r_time.strftime("%H:%M"),
                        place=place,
                        notes=notes,
                        schedule_type=sched,
                        schedule_detail=sdetail,
                    )
                    st.session_state.show_add_reminder = False
                    st.rerun()
                else:
                    st.warning("Please enter a title.")

    st.sidebar.header("Settings")
    with st.sidebar.form("persona_form"):
        name = st.text_input("Name", value=persona.name)
        age = st.text_input("Age", value=persona.age)
        language = st.selectbox(
            "Language",
            LANGUAGES,
            index=max(0, LANGUAGES.index(persona.language)) if persona.language in LANGUAGES else 0,
        )
        timezone = st.text_input("Timezone", value=persona.timezone)
        style = st.selectbox(
            "Reminder style",
            REMINDER_STYLES,
            index=max(0, REMINDER_STYLES.index(persona.reminder_style))
            if persona.reminder_style in REMINDER_STYLES
            else 0,
        )
        api = st.text_input(
            "OpenAI API Key",
            value=os.environ.get("OPENAI_API_KEY", ""),
            type="password",
        )
        channel = st.selectbox("Notification channel", ["email", "twilio", "ntfy"], key="notif_channel")
        destination = st.text_input("Notification destination (email / phone / ntfy topic)", key="notif_dest")
        if st.form_submit_button("Save Settings", type="primary"):
            save_persona(
                session_id,
                Persona(
                    name=name.strip(),
                    age=age.strip(),
                    language=language,
                    timezone=timezone.strip() or "UTC",
                    reminder_style=style,
                ),
            )
            if api.strip():
                os.environ["OPENAI_API_KEY"] = api.strip()
            st.session_state.notification_channel = channel
            st.session_state.notification_destination = destination.strip()
            st.success("Settings saved.")
            st.rerun()
    with st.sidebar.expander("Email delivery (SMTP env)"):
        st.caption(
            "Set CAREBUDDY_SMTP_HOST, CAREBUDDY_SMTP_PORT, CAREBUDDY_SMTP_USER, "
            "CAREBUDDY_SMTP_PASSWORD, CAREBUDDY_SMTP_FROM on the machine running Streamlit."
        )
    return get_persona(session_id)


def render_left_panel(session_id: str, persona: Persona) -> None:
    st.subheader("Profile")
    st.write(f"**Name:** {persona.name or 'Not set'}")
    st.write(f"**Age:** {persona.age or 'Not set'}")
    st.write(f"**Language:** {persona.language}")
    st.write(f"**Timezone:** {persona.timezone}")
    st.write(f"**Reminder style:** {persona.reminder_style}")

    st.subheader("Next Reminder")
    nr = next_reminder(session_id)
    if nr:
        st.success(f"{nr['title']} at {nr['reminder_time']} on {nr['reminder_date']}")
        st.caption(
            f"{nr['kind']} · {format_schedule_summary(nr['schedule_type'], nr['schedule_detail'], nr['reminder_date'])}"
        )
    else:
        st.caption("No upcoming reminders.")

    st.subheader("Today's Reminders")
    today = date.today()
    todays = reminders_for_day(session_id, today)
    if not todays:
        st.caption("No reminders today.")
    for r in todays:
        done = is_completed_for_day(session_id, r["id"], today)
        c1, c2 = st.columns([4, 1])
        with c1:
            st.write(f"{r['reminder_time']} · {r['title']} ({r['kind']}) — {'done' if done else 'pending'}")
        with c2:
            if done:
                if st.button("Undo", key=f"undo_{r['id']}"):
                    unmark_completed_for_day(session_id, r["id"], today)
                    if r.get("schedule_type") == SCHEDULE_ONCE:
                        update_reminder(session_id, r["id"], status="pending")
                    st.rerun()
            else:
                if st.button("Done", key=f"done_{r['id']}"):
                    mark_completed_for_day(session_id, r["id"], today)
                    if r.get("schedule_type") == SCHEDULE_ONCE:
                        update_reminder(session_id, r["id"], status="completed")
                    st.rerun()

    st.subheader("Daily Summary")
    summary = build_daily_summary(session_id, today)
    save_daily_summary(session_id, today, summary)
    st.text(summary)


def render_chat_tab(session_id: str, persona: Persona) -> None:
    st.caption("Chat with CareBuddy.")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg.get("image_bytes"):
                st.image(io.BytesIO(msg["image_bytes"]), width=220)
            st.markdown(msg["content"])

    if hasattr(st, "audio_input"):
        audio = st.audio_input("Record a message", key="voice_rec")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if audio is not None and st.button("Transcribe (Whisper)", key="whisper_btn"):
                w = WhisperVoiceProvider(api_key=api_key)
                spoken = w.transcribe(audio.getvalue(), mime_hint=getattr(audio, "type", "") or "audio/webm")
                if spoken:
                    st.session_state.pending_voice_text = spoken
                    st.success(spoken)
                else:
                    st.warning("No transcription (check API key and audio).")
        with col_b:
            if audio is not None and st.button("Create reminder from voice", key="voice_rem_btn"):
                w = WhisperVoiceProvider(api_key=api_key)
                spoken = w.transcribe(audio.getvalue(), mime_hint=getattr(audio, "type", "") or "audio/webm")
                if not spoken:
                    st.warning("Transcription empty.")
                else:
                    parsed = try_parse_reminder_from_text(spoken, api_key, date.today().isoformat())
                    if not parsed:
                        st.info("Could not parse a reminder; try rephrasing or use Add Reminder.")
                    else:
                        add_reminder(
                            session_id,
                            kind=parsed["kind"],
                            title=parsed["title"],
                            reminder_date=parsed["reminder_date"],
                            reminder_time=parsed["reminder_time"],
                            place=str(parsed.get("place") or ""),
                            notes=str(parsed.get("notes") or ""),
                            schedule_type=str(parsed.get("schedule_type") or SCHEDULE_ONCE),
                            schedule_detail=str(parsed.get("schedule_detail") or ""),
                        )
                        st.success(f"Saved reminder: {parsed['title']}")
                        st.rerun()
        with col_c:
            if st.session_state.get("pending_voice_text") and st.button("Send transcribed text to chat", key="send_voice"):
                text = st.session_state.pop("pending_voice_text")
                st.session_state.messages.append({"role": "user", "content": text})
                log_message(session_id, "user", text)
                try:
                    reply = chat_response_core(session_id, text, persona, api_key=api_key)
                    reply = _append_medicine_info(reply, api_key)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    log_message(session_id, "assistant", reply)
                except Exception as e:
                    st.error(str(e))
                st.rerun()
    else:
        st.caption("Upgrade Streamlit to use microphone recording (audio_input).")

    st.markdown("**Medicine label photo**")
    up = st.file_uploader("Upload image", type=["png", "jpg", "jpeg", "webp"], key="chat_img")
    if up is not None and st.button("Analyze Image"):
        try:
            result = analyze_medicine_bottle_image_bytes(up.getvalue(), mime_type=up.type or "image/jpeg")
            assistant_text = format_medicine_bottle_analysis(result)
            hint = _vision_medicine_hint(result)
            med_key = detect_medicine_name(assistant_text + " " + (hint or ""))
            guidance = get_medicine_guidance(med_key)
            if not guidance and hint and api_key:
                guidance = get_medicine_guidance_llm(hint, api_key)
            if guidance:
                assistant_text += (
                    "\n\n**Simple medicine info**\n"
                    f"- How to take: {guidance['how_to_take']}\n"
                    f"- Precautions: {guidance['precautions']}\n"
                    "- Verify details with your pharmacist or prescriber."
                )
            st.session_state.messages.append(
                {"role": "user", "content": "Shared a medicine photo", "image_bytes": up.getvalue()}
            )
            st.session_state.messages.append({"role": "assistant", "content": assistant_text})
            log_message(session_id, "user", "[Image uploaded]")
            log_message(session_id, "assistant", assistant_text)
            st.rerun()
        except Exception as e:
            st.error(f"Image analysis failed: {e}")

    if prompt := st.chat_input("Type your message..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        log_message(session_id, "user", prompt)
        with st.spinner("Thinking..."):
            try:
                reply = chat_response_core(session_id, prompt, persona, api_key=api_key)
                reply = _append_medicine_info(prompt + " " + reply, api_key)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                log_message(session_id, "assistant", reply)
            except Exception as e:
                st.error(f"Something went wrong: {e}")
        st.rerun()


def _render_reminder_editor(session_id: str, r: dict, key_prefix: str) -> None:
    with st.expander(f"{r['reminder_time']} · {r['title']} ({r['kind']})", expanded=False):
        st.caption(
            f"{format_schedule_summary(r['schedule_type'], r['schedule_detail'], r['reminder_date'])} · Status: {r['status']}"
        )
        kind = st.selectbox(
            "Kind",
            ["medicine", "general"],
            index=0 if r["kind"] == "medicine" else 1,
            key=f"{key_prefix}_kind_{r['id']}",
        )
        title = st.text_input("Title", value=r["title"], key=f"{key_prefix}_title_{r['id']}")
        r_date = st.date_input(
            "Date",
            value=datetime.fromisoformat(r["reminder_date"]).date(),
            key=f"{key_prefix}_date_{r['id']}",
        )
        r_time = st.time_input(
            "Time",
            value=datetime.strptime(r["reminder_time"], "%H:%M").time(),
            key=f"{key_prefix}_time_{r['id']}",
        )
        place = st.text_input("Place", value=r["place"] or "", key=f"{key_prefix}_place_{r['id']}")
        notes = st.text_input("Notes", value=r["notes"] or "", key=f"{key_prefix}_notes_{r['id']}")
        sched_keys = list(SCHEDULE_LABELS.keys())
        sched_idx = sched_keys.index(r["schedule_type"]) if r.get("schedule_type") in sched_keys else 0
        sched = st.selectbox(
            "Schedule",
            sched_keys,
            index=sched_idx,
            format_func=lambda x: SCHEDULE_LABELS[x],
            key=f"{key_prefix}_sched_{r['id']}",
        )
        sdetail_default = r.get("schedule_detail") or ""
        if sched == SCHEDULE_WEEKLY:
            wd = sdetail_default if sdetail_default in WEEKDAYS else WEEKDAYS[0]
            wd_i = WEEKDAYS.index(wd) if wd in WEEKDAYS else 0
            sdetail = st.selectbox("Weekday", WEEKDAYS, index=wd_i, key=f"{key_prefix}_sd_{r['id']}")
        else:
            sdetail = st.text_input(
                "Schedule detail",
                value=sdetail_default,
                key=f"{key_prefix}_sd_{r['id']}",
            )
        status = st.selectbox(
            "Status",
            ["pending", "completed", "skipped"],
            index=["pending", "completed", "skipped"].index(r["status"])
            if r["status"] in ["pending", "completed", "skipped"]
            else 0,
            key=f"{key_prefix}_status_{r['id']}",
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save", key=f"{key_prefix}_save_{r['id']}"):
                update_reminder(
                    session_id,
                    r["id"],
                    kind=kind,
                    title=title,
                    reminder_date=r_date.isoformat(),
                    reminder_time=r_time.strftime("%H:%M"),
                    place=place,
                    notes=notes,
                    schedule_type=sched,
                    schedule_detail=sdetail if isinstance(sdetail, str) else str(sdetail),
                    status=status,
                )
                st.rerun()
        with c2:
            if st.button("Delete", key=f"{key_prefix}_del_{r['id']}"):
                delete_reminder(session_id, r["id"])
                st.rerun()


def render_calendar_tab(session_id: str) -> None:
    st.caption("Visual reminder calendar (daily / weekly). Open an item to edit or delete.")
    mode = st.radio("Mode", ["Daily", "Weekly"], horizontal=True)
    if mode == "Daily":
        d = st.date_input("Pick day", value=date.today(), key="calendar_daily_date")
        rows = daily_view_events(session_id, d)
        if not rows:
            st.info("No reminders for this day.")
        for r in rows:
            _render_reminder_editor(session_id, r, "calday")
    else:
        start = st.date_input(
            "Week start",
            value=date.today() - timedelta(days=date.today().weekday()),
            key="calendar_week_start",
        )
        for day, rows in weekly_view_events(session_id, start):
            st.markdown(f"**{day}**")
            if not rows:
                st.caption("No reminders.")
                continue
            for r in rows:
                _render_reminder_editor(session_id, r, "calweek")


def render_reminders_tab(session_id: str) -> None:
    st.caption("All reminders")
    rows = list_reminders(session_id)
    if not rows:
        st.info("No reminders yet.")
    for r in rows:
        _render_reminder_editor(session_id, r, "all")


def main() -> None:
    ensure_db()
    st.set_page_config(page_title="CareBuddy", page_icon="🌸", layout="wide")
    st.title("CareBuddy")
    st.caption("Simple, structured, and personalized reminder support.")

    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    session_id = st.session_state.session_id

    if "messages" not in st.session_state:
        st.session_state.messages = get_chat_history(session_id)
    if "show_add_reminder" not in st.session_state:
        st.session_state.show_add_reminder = False
    if "notification_channel" not in st.session_state:
        st.session_state.notification_channel = "email"
    if "notification_destination" not in st.session_state:
        st.session_state.notification_destination = ""

    persona = get_persona(session_id)
    persona = render_sidebar(session_id, persona)

    dest = st.session_state.get("notification_destination", "")
    ch = st.session_state.get("notification_channel", "email")
    providers = {
        "email": EmailNotificationProvider(),
        "twilio": TwilioNotificationProvider(),
        "ntfy": NtfyNotificationProvider(),
    }
    notify_due_reminders(session_id, dest, ch, providers.get(ch))

    left, right = st.columns([1, 2], gap="large")
    with left:
        render_left_panel(session_id, persona)
    with right:
        tab_chat, tab_calendar, tab_rem = st.tabs(["Chat", "Calendar", "Reminders"])
        with tab_chat:
            render_chat_tab(session_id, persona)
        with tab_calendar:
            render_calendar_tab(session_id)
        with tab_rem:
            render_reminders_tab(session_id)


if __name__ == "__main__":
    main()
