"""Simplified adaptive review monitor."""
from __future__ import annotations

from datetime import date
from typing import Any

from config import DATA_DIR
from data_contracts import read_json, write_json
from diagnostics import run_diagnostics
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def evaluate_adaptive_triggers(metrics_payload: dict[str, Any], as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    diagnostics = run_diagnostics(metrics_payload, as_of)
    triggers = [key for key, value in diagnostics.items() if isinstance(value, bool) and value]
    event = add_watermark(
        {
            "as_of": as_of,
            "triggers": triggers,
            "diagnostics": diagnostics,
            "human_approval_required": True,
            "automatic_logic_mutation_allowed": False,
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )
    write_review_event(event)
    write_json(DATA_DIR / "adaptive_monitor_status.json", event)
    return event


def write_review_event(event: dict[str, Any]) -> dict[str, Any]:
    path = DATA_DIR / "review_events.json"
    existing = read_json(path, default={"watermark": SYSTEMATIC_TEMPLATE_OUTPUT, "events": []})
    events = existing.get("events", []) if isinstance(existing, dict) else []
    events.append(event)
    payload = add_watermark({"events": events[-100:]}, SYSTEMATIC_TEMPLATE_OUTPUT)
    write_json(path, payload)
    return payload
