"""Experimental agent-led decision track.

This module never executes or overrides production logic. It creates a separate
watermarked comparison artifact from structured systematic fields.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from config import DATA_DIR
from data_contracts import write_json
from watermark import AI_GENERATED_AGENT_DECISION_EXPERIMENTAL, add_watermark


def build_agent_led_decision(
    target_payload: dict[str, Any],
    score_payload: dict[str, Any],
    risk_payload: dict[str, Any],
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or target_payload.get("as_of") or date.today().isoformat()
    risk_status = risk_payload.get("risk_status", {})
    top_scores = score_payload.get("scores", [])[:8]
    target = {row["symbol"]: row["weight"] for row in target_payload.get("target_allocations", [])}
    risks = list(risk_status.get("reasons", []))
    confidence = 0.65
    if risk_status.get("light") in ("RED", "BLACK"):
        confidence = 0.15
    elif risk_status.get("light") == "YELLOW":
        confidence = 0.40

    rationale = (
        "Experimental comparison track mirrors the systematic allocation and "
        "highlights top ranked candidates. It is not allowed to execute or "
        "override risk controls."
    )

    return add_watermark(
        {
            "as_of": as_of,
            "target_allocation": target,
            "rationale": rationale,
            "confidence": confidence,
            "risks": risks,
            "top_ranked_symbols": [row["symbol"] for row in top_scores],
            "allowed_for_execution": False,
        },
        AI_GENERATED_AGENT_DECISION_EXPERIMENTAL,
    )


def write_agent_decision(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "agent_decision.json", payload)
