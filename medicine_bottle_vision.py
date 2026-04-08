"""
Medicine bottle image analysis using OpenAI vision.

Uses the same stack as the main app (langchain-openai). Intended for labeling,
accessibility, and organization—not for medical diagnosis or treatment decisions.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

DEFAULT_MODEL = "gpt-4o-mini"

_SYSTEM = (
    "You help describe medicine bottles and packaging from photos for "
    "accessibility and safe organization. You are not a doctor or pharmacist; "
    "do not give dosing instructions or medical advice. Be clear when text is "
    "unreadable or the object may not be a medicine container."
)

_USER_TEMPLATE = """Look at this image.

1. Decide whether it shows a medicine bottle, box, blister pack, or similar pharmaceutical packaging (or not).
2. Summarize what the label appears to say: product name, active ingredient if visible, strength, form (tablet, liquid, etc.).
3. Note any visible warnings, directions, or storage text only as you read it—do not infer clinical meaning beyond the label.
4. Call out problems: blur, glare, angle, foreign language, missing information, or anything that limits confidence.

Respond with a single JSON object only (no markdown code fences), using this exact shape:
{
  "is_medicine_packaging": <boolean>,
  "confidence": "<low|medium|high>",
  "what_it_appears_to_be": "<short plain description or null>",
  "active_ingredient_or_drug_name": "<string or null>",
  "strength_and_form": "<string or null>",
  "stated_use_or_indications_from_label": "<string or null>",
  "visible_warnings_or_cautions": "<string or null>",
  "readable_label_excerpts": ["<phrase>", "..."],
  "issues_limiting_interpretation": ["<issue>", "..."],
  "notes": "<brief extra context; remind user to verify with a pharmacist or prescriber>"
}"""


def _image_to_data_url(image_path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(image_path))
    if not mime:
        mime = "image/jpeg"
    raw = image_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def analyze_medicine_bottle_image(
    image_path: str | Path,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """
    Send a local image file to OpenAI vision and return structured interpretation
    of the medicine packaging (identity from label, readable text, limitations).

    Parameters
    ----------
    image_path
        Path to an image file (JPEG, PNG, WebP, etc.).
    api_key
        OpenAI API key. Defaults to ``OPENAI_API_KEY`` in the environment.
    model
        Vision-capable chat model (default ``gpt-4o-mini``).

    Returns
    -------
    dict
        Parsed JSON fields from the model (see prompt for keys), plus ``raw_text``
        if JSON parsing fails.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")

    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ValueError(
            "OpenAI API key is missing. Set OPENAI_API_KEY or pass api_key=."
        )

    data_url = _image_to_data_url(path)
    human = HumanMessage(
        content=[
            {"type": "text", "text": _USER_TEMPLATE},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )

    llm = ChatOpenAI(model=model, temperature=0.2, api_key=key)
    out = llm.invoke([SystemMessage(content=_SYSTEM), human])
    raw = (out.content or "").strip()
    if isinstance(raw, list):
        raw = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in raw
        )

    try:
        parsed = _parse_json_response(raw)
        parsed["raw_text"] = raw
        return parsed
    except json.JSONDecodeError:
        return {
            "parse_error": True,
            "raw_text": raw,
            "is_medicine_packaging": None,
            "notes": "Model did not return valid JSON; see raw_text.",
        }


def analyze_medicine_bottle_image_bytes(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """
    Same as ``analyze_medicine_bottle_image`` but accepts raw image bytes and an
    explicit MIME type (e.g. ``image/png``).
    """
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ValueError(
            "OpenAI API key is missing. Set OPENAI_API_KEY or pass api_key=."
        )

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"

    human = HumanMessage(
        content=[
            {"type": "text", "text": _USER_TEMPLATE},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )

    llm = ChatOpenAI(model=model, temperature=0.2, api_key=key)
    out = llm.invoke([SystemMessage(content=_SYSTEM), human])
    raw = (out.content or "").strip()
    if isinstance(raw, list):
        raw = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in raw
        )

    try:
        parsed = _parse_json_response(raw)
        parsed["raw_text"] = raw
        return parsed
    except json.JSONDecodeError:
        return {
            "parse_error": True,
            "raw_text": raw,
            "is_medicine_packaging": None,
            "notes": "Model did not return valid JSON; see raw_text.",
        }
