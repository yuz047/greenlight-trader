"""Watermark policy for generated Greenlight outputs."""
from __future__ import annotations

from typing import Any

from data_contracts import utc_now_iso


SYSTEMATIC_TEMPLATE_OUTPUT = "SYSTEMATIC_TEMPLATE_OUTPUT"
ML_ESTIMATED_OUTPUT = "ML_ESTIMATED_OUTPUT"
AI_GENERATED_MEMO = "AI_GENERATED_MEMO"
AI_GENERATED_AGENT_DECISION_EXPERIMENTAL = "AI_GENERATED_AGENT_DECISION_EXPERIMENTAL"
HUMAN_APPROVED_CHANGE = "HUMAN_APPROVED_CHANGE"

VALID_WATERMARKS = {
    SYSTEMATIC_TEMPLATE_OUTPUT,
    ML_ESTIMATED_OUTPUT,
    AI_GENERATED_MEMO,
    AI_GENERATED_AGENT_DECISION_EXPERIMENTAL,
    HUMAN_APPROVED_CHANGE,
}


def add_watermark(payload: dict[str, Any], watermark: str = SYSTEMATIC_TEMPLATE_OUTPUT) -> dict[str, Any]:
    if watermark not in VALID_WATERMARKS:
        raise ValueError(f"Unknown watermark: {watermark}")
    out = dict(payload)
    out.setdefault("watermark", watermark)
    out.setdefault("generated_at", utc_now_iso())
    watermarks = list(out.get("watermarks", []))
    if watermark not in watermarks:
        watermarks.append(watermark)
    out["watermarks"] = watermarks
    return out


def watermarked_text(title: str, body: str, watermark: str) -> str:
    if watermark not in VALID_WATERMARKS:
        raise ValueError(f"Unknown watermark: {watermark}")
    return f"Watermark: {watermark}\nGenerated-At: {utc_now_iso()}\n\n# {title}\n\n{body.rstrip()}\n"


def find_watermarks(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        wm = value.get("watermark")
        if isinstance(wm, str):
            found.add(wm)
        for item in value.get("watermarks", []):
            if isinstance(item, str):
                found.add(item)
        for child in value.values():
            found.update(find_watermarks(child))
    elif isinstance(value, list):
        for item in value:
            found.update(find_watermarks(item))
    elif isinstance(value, str):
        for watermark in VALID_WATERMARKS:
            if watermark in value:
                found.add(watermark)
    return found


def has_valid_watermark(value: Any) -> bool:
    return bool(find_watermarks(value) & VALID_WATERMARKS)
