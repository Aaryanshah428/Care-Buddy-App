from __future__ import annotations

import base64
import io
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


class VoiceProvider(Protocol):
    name: str

    def transcribe(self, audio_bytes: bytes, mime_hint: str = "audio/webm") -> str:
        ...


class TranslatorProvider(Protocol):
    name: str

    def to_english(self, text: str, source_language: str) -> str:
        ...

    def from_english(self, text: str, target_language: str) -> str:
        ...


class NotificationProvider(Protocol):
    name: str

    def send(self, destination: str, message: str) -> tuple[bool, str]:
        ...


@dataclass
class BrowserVoiceProvider:
    """Placeholder when browser capture is not wired; prefer Whisper + st.audio_input."""

    name: str = "browser"

    def transcribe(self, audio_bytes: bytes, mime_hint: str = "audio/webm") -> str:
        return ""


@dataclass
class WhisperVoiceProvider:
    name: str = "whisper"
    api_key: str = ""

    def transcribe(self, audio_bytes: bytes, mime_hint: str = "audio/webm") -> str:
        key = (self.api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        if not key or not audio_bytes:
            return ""
        try:
            from openai import OpenAI
        except ImportError:
            return ""
        client = OpenAI(api_key=key)
        buf = io.BytesIO(audio_bytes)
        ext = ".webm" if "webm" in mime_hint else ".wav"
        buf.name = f"audio{ext}"
        tr = client.audio.transcriptions.create(model="whisper-1", file=buf)
        return (tr.text or "").strip()


@dataclass
class PassthroughTranslator:
    name: str = "passthrough"

    def to_english(self, text: str, source_language: str) -> str:
        return text

    def from_english(self, text: str, target_language: str) -> str:
        return text


@dataclass
class OpenAITranslator:
    """Translate user input/output when language is not English."""

    name: str = "openai"
    api_key: str = ""

    def _llm(self) -> ChatOpenAI:
        key = (self.api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        if not key:
            raise ValueError("API key required for translation")
        return ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=key)

    def to_english(self, text: str, source_language: str) -> str:
        if not text.strip():
            return text
        if (source_language or "").strip().lower() in ("english", "en"):
            return text
        llm = self._llm()
        out = llm.invoke(
            [
                SystemMessage(
                    content="Translate the user's message to clear English. Output only the translation."
                ),
                HumanMessage(content=f"Language: {source_language}\n\n{text}"),
            ]
        )
        return (out.content or "").strip() or text

    def from_english(self, text: str, target_language: str) -> str:
        if not text.strip():
            return text
        if (target_language or "").strip().lower() in ("english", "en"):
            return text
        llm = self._llm()
        out = llm.invoke(
            [
                SystemMessage(
                    content=f"Translate the assistant reply into {target_language}. "
                    "Keep a warm, simple tone. Output only the translation."
                ),
                HumanMessage(content=text),
            ]
        )
        return (out.content or "").strip() or text


@dataclass
class EmailNotificationProvider:
    name: str = "email"

    def send(self, destination: str, message: str) -> tuple[bool, str]:
        host = os.environ.get("CAREBUDDY_SMTP_HOST", "").strip()
        port = int(os.environ.get("CAREBUDDY_SMTP_PORT", "587") or "587")
        user = os.environ.get("CAREBUDDY_SMTP_USER", "").strip()
        password = os.environ.get("CAREBUDDY_SMTP_PASSWORD", "").strip()
        from_addr = os.environ.get("CAREBUDDY_SMTP_FROM", user).strip()
        if not host or not from_addr:
            return False, "Set CAREBUDDY_SMTP_HOST and CAREBUDDY_SMTP_FROM (and usually USER/PASSWORD)."
        try:
            msg = EmailMessage()
            msg["Subject"] = "CareBuddy reminder"
            msg["From"] = from_addr
            msg["To"] = destination
            msg.set_content(message)
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
            return True, "sent"
        except Exception as e:
            return False, str(e)


@dataclass
class TwilioNotificationProvider:
    name: str = "twilio"

    def send(self, destination: str, message: str) -> tuple[bool, str]:
        sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        from_num = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
        if not sid or not token or not from_num:
            return False, "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER."
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
            body = urllib.parse.urlencode(
                {"To": destination, "From": from_num, "Body": message[:1500]}
            ).encode()
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            creds = f"{sid}:{token}"
            b64 = base64.b64encode(creds.encode()).decode()
            req.add_header("Authorization", f"Basic {b64}")
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp.read()
            return True, "sent"
        except urllib.error.HTTPError as e:
            return False, e.read().decode(errors="replace")[:300]
        except Exception as e:
            return False, str(e)


@dataclass
class NtfyNotificationProvider:
    name: str = "ntfy"

    def send(self, destination: str, message: str) -> tuple[bool, str]:
        """
        destination: ntfy topic (e.g. myphone) or full URL https://ntfy.sh/mytopic
        """
        topic = destination.strip()
        if topic.startswith("http"):
            url = topic.rstrip("/")
        else:
            base = os.environ.get("CAREBUDDY_NTFY_BASE", "https://ntfy.sh").rstrip("/")
            url = f"{base}/{urllib.parse.quote(topic)}"
        try:
            req = urllib.request.Request(
                url,
                data=message.encode("utf-8"),
                method="POST",
                headers={"Title": "CareBuddy"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp.read()
            return True, "sent"
        except Exception as e:
            return False, str(e)
