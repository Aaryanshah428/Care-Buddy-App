from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

_MED_GUIDE = {
    "ibuprofen": {
        "how_to_take": "Take with food or milk to reduce stomach upset.",
        "precautions": "Avoid combining with other NSAIDs unless advised by your clinician.",
    },
    "acetaminophen": {
        "how_to_take": "Use only as directed on the label and track total daily amount.",
        "precautions": "Do not exceed label limits; many cold/flu products also contain acetaminophen.",
    },
    "advil": {
        "how_to_take": "Advil is ibuprofen; take with food when possible.",
        "precautions": "Avoid if you were told not to take NSAIDs.",
    },
}


def detect_medicine_name(text: str) -> str | None:
    low = (text or "").lower()
    for k in _MED_GUIDE:
        if re.search(rf"\b{re.escape(k)}\b", low):
            return k
    return None


def get_medicine_guidance(name: str | None) -> dict[str, str] | None:
    if not name:
        return None
    return _MED_GUIDE.get(name.lower())


def get_medicine_guidance_llm(drug_name: str, api_key: str) -> dict[str, str] | None:
    """High-level non-prescriptive tips; not medical advice."""
    drug_name = (drug_name or "").strip()
    if not drug_name or not api_key:
        return None
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, api_key=api_key)
    out = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are not a doctor. Give 2 short bullet ideas: how people commonly take this medicine "
                    "category (very general) and common precautions to discuss with a pharmacist. "
                    "No dosing numbers. Output JSON with keys how_to_take and precautions only."
                )
            ),
            HumanMessage(content=f"Medicine name or ingredient: {drug_name}"),
        ]
    )
    raw = (out.content or "").strip()
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        ht = str(data.get("how_to_take", "")).strip()
        pr = str(data.get("precautions", "")).strip()
        if ht and pr:
            return {"how_to_take": ht, "precautions": pr}
    except Exception:
        pass
    return None

