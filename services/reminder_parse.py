"""Extract reminder fields from free text (e.g. voice) using the LLM."""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from services.schedule_constants import SCHEDULE_ONCE

_SYSTEM = """You extract reminder details from user text. Return ONE JSON object only, no markdown.
Keys (use null if unknown):
- kind: "medicine" or "general"
- title: short string
- reminder_date: YYYY-MM-DD (use today's date if user says today)
- reminder_time: HH:MM 24h
- place: string or null
- notes: string or null
- schedule_type: one of once, daily, weekly, biweekly, special
- schedule_detail: for weekly: weekday name like Monday; for special: short text; else empty string
If the message is NOT about setting a reminder, return {"intent":"other"} only.
"""


def try_parse_reminder_from_text(text: str, api_key: str, today_iso: str) -> dict | None:
    text = (text or "").strip()
    if not text or not api_key:
        return None
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=api_key)
    out = llm.invoke(
        [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=f"Today is {today_iso}.\n\nUser said:\n{text}"),
        ]
    )
    raw = (out.content or "").strip()
    if isinstance(raw, list):
        raw = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in raw
        )
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if data.get("intent") == "other":
        return None
    required = {"kind", "title", "reminder_date", "reminder_time"}
    if not required.issubset(set(data.keys())):
        return None
    if not str(data.get("title") or "").strip():
        return None
    data.setdefault("place", "")
    data.setdefault("notes", "")
    data.setdefault("schedule_type", SCHEDULE_ONCE)
    data.setdefault("schedule_detail", "")
    return data
