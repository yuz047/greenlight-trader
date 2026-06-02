"""Approved and candidate score-weight registry."""
from __future__ import annotations

from datetime import date
from typing import Any

from config import DATA_DIR, DEFAULT_ETF_SCORE_WEIGHTS, DEFAULT_STOCK_SCORE_WEIGHTS
from data_contracts import read_json, write_json
from watermark import HUMAN_APPROVED_CHANGE, ML_ESTIMATED_OUTPUT, SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


REGISTRY_PATH = DATA_DIR / "weight_registry.json"


def default_registry() -> dict[str, Any]:
    return add_watermark(
        {
            "approved": {
                "stock": DEFAULT_STOCK_SCORE_WEIGHTS,
                "etf": DEFAULT_ETF_SCORE_WEIGHTS,
                "approved_at": None,
                "approval_watermark": None,
                "version": "fixed_v1",
            },
            "candidates": [],
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def load_registry() -> dict[str, Any]:
    return read_json(REGISTRY_PATH, default=default_registry())


def write_candidate_weights(candidate: dict[str, Any], as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    registry = load_registry()
    candidates = registry.get("candidates", [])
    candidates.append(add_watermark({"as_of": as_of, "candidate": candidate, "approved": False}, ML_ESTIMATED_OUTPUT))
    registry["candidates"] = candidates[-20:]
    write_json(REGISTRY_PATH, registry)
    return registry


def approve_weights(asset_type: str, weights: dict[str, float], approver: str, as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    registry = load_registry()
    registry.setdefault("approved", {})[asset_type] = weights
    registry["approved"]["approved_at"] = as_of
    registry["approved"]["approved_by"] = approver
    registry["approved"]["approval_watermark"] = HUMAN_APPROVED_CHANGE
    registry["approved"]["version"] = f"human_approved_{as_of}"
    write_json(REGISTRY_PATH, add_watermark(registry, HUMAN_APPROVED_CHANGE))
    return registry
