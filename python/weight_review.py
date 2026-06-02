"""Quarterly learned-weight review workflow."""
from __future__ import annotations

from datetime import date
from typing import Any

from config import DATA_DIR
from data_contracts import read_json, write_json
from watermark import ML_ESTIMATED_OUTPUT, SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark
from weight_registry import load_registry


MAX_WEIGHT_CHANGE_PER_REVIEW = 0.20


def review_candidate_weights(candidate: dict[str, Any], as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    registry = load_registry()
    approved = registry.get("approved", {})
    asset_type = candidate.get("asset_type", "stock")
    current = approved.get(asset_type, {})
    proposed = candidate.get("weights", {})
    changes = {
        key: round(float(proposed.get(key, 0.0)) - float(current.get(key, 0.0)), 6)
        for key in set(current) | set(proposed)
        if isinstance(current.get(key, 0.0), (int, float)) or isinstance(proposed.get(key, 0.0), (int, float))
    }
    breach = any(abs(value) > MAX_WEIGHT_CHANGE_PER_REVIEW for value in changes.values())
    event = add_watermark(
        {
            "as_of": as_of,
            "asset_type": asset_type,
            "candidate_weights": proposed,
            "current_weights": current,
            "changes": changes,
            "max_weight_change_per_review": MAX_WEIGHT_CHANGE_PER_REVIEW,
            "requires_human_approval": True,
            "approved_for_production": False,
            "blocked_reasons": ["human_approval_required"] + (["max_weight_change_breach"] if breach else []),
        },
        ML_ESTIMATED_OUTPUT,
    )
    append_weight_review(event)
    return event


def append_weight_review(event: dict[str, Any]) -> dict[str, Any]:
    path = DATA_DIR / "weight_reviews.json"
    existing = read_json(path, default={"watermark": SYSTEMATIC_TEMPLATE_OUTPUT, "reviews": []})
    reviews = existing.get("reviews", []) if isinstance(existing, dict) else []
    reviews.append(event)
    payload = add_watermark({"reviews": reviews[-40:]}, SYSTEMATIC_TEMPLATE_OUTPUT)
    write_json(path, payload)
    return payload
