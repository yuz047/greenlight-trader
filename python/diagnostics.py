"""Diagnostics for adaptive review events."""
from __future__ import annotations

from datetime import date
from typing import Any

from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def run_diagnostics(metrics_payload: dict[str, Any], as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    metrics = metrics_payload.get("metrics", {})
    fixed = metrics.get("fixed_weight_Greenlight", {})
    spy = metrics.get("SPY_buy_hold", {})
    diagnostics = {
        "as_of": as_of,
        "rolling_alpha_decay": fixed.get("alpha_vs_SPY", 0.0) < 0,
        "relative_drawdown_breach": fixed.get("max_relative_drawdown_vs_SPY", 0.0) > 0.12,
        "underperformed_spy": fixed.get("total_return", 0.0) < spy.get("total_return", 0.0),
        "excess_turnover_without_alpha": fixed.get("turnover", 0.0) > 1.0 and fixed.get("alpha_vs_SPY", 0.0) <= 0,
        "recommendation": "review_weights_and_benchmarks",
    }
    return add_watermark(diagnostics, SYSTEMATIC_TEMPLATE_OUTPUT)
