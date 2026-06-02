"""Risk engine and traffic-light gate."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from config import DATA_DIR, MANDATE
from data_contracts import RiskStatus, write_json
from exposure import group_exposure, top_n_weight
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def evaluate_risk(
    portfolio_state: dict[str, Any],
    target_payload: dict[str, Any],
    data_health: dict[str, Any],
    regime_payload: dict[str, Any],
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    allocations = target_payload.get("target_allocations", [])
    reasons: list[str] = []
    light = "GREEN"

    if not data_health.get("ok", False):
        light = "BLACK"
        reasons.append("critical data health is not ok")
    if data_health.get("synthetic"):
        light = "BLACK"
        reasons.append("fallback synthetic data cannot be used for production trading")
    if regime_payload.get("regime") == "DATA_FAILURE":
        light = "BLACK"
        reasons.append("regime is DATA_FAILURE")

    nav = float(portfolio_state.get("nav") or MANDATE.starting_capital)
    peak_nav = max(float(portfolio_state.get("peak_nav") or nav), nav, 1.0)
    absolute_drawdown = nav / peak_nav - 1
    if absolute_drawdown <= -MANDATE.max_absolute_drawdown_pct:
        light = _worse(light, "RED")
        reasons.append("absolute drawdown cap breached")
    elif absolute_drawdown <= -MANDATE.max_absolute_drawdown_pct * 0.70:
        light = _worse(light, "YELLOW")
        reasons.append("absolute drawdown approaching cap")

    relative_drawdown = float(portfolio_state.get("relative_drawdown_pct") or 0.0)
    if relative_drawdown >= MANDATE.max_relative_drawdown_pct:
        light = _worse(light, "RED")
        reasons.append("relative drawdown cap breached")
    elif relative_drawdown >= MANDATE.max_relative_drawdown_pct * 0.70:
        light = _worse(light, "YELLOW")
        reasons.append("relative drawdown approaching cap")

    concentration = _concentration(allocations)
    if concentration["top3_weight"] > MANDATE.max_top3_weight + 0.0001:
        light = _worse(light, "YELLOW")
        reasons.append("top-3 concentration exceeds cap")
    if concentration["max_sector_weight"] > MANDATE.max_sector_weight + 0.0001:
        light = _worse(light, "YELLOW")
        reasons.append("sector concentration exceeds cap")
    if concentration["max_theme_weight"] > MANDATE.max_theme_weight + 0.0001:
        light = _worse(light, "YELLOW")
        reasons.append("theme concentration exceeds cap")

    if not reasons:
        reasons.append("risk checks passed")

    status = RiskStatus(
        as_of=as_of,
        light=light,
        reasons=reasons,
        data_health=data_health,
        absolute_drawdown_pct=round(absolute_drawdown, 6),
        relative_drawdown_pct=round(relative_drawdown, 6),
        concentration=concentration,
        allow_new_alpha_entries=light in ("GREEN", "YELLOW") and regime_payload.get("allow_new_alpha_entries", False),
    )
    return add_watermark({"risk_status": asdict(status)}, SYSTEMATIC_TEMPLATE_OUTPUT)


def write_risk_status(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "risk_status.json", payload)


def _concentration(allocations: list[dict[str, Any]]) -> dict[str, float]:
    alpha_allocations = [
        row for row in allocations
        if row.get("sleeve") in {"dynamic_etf", "stock_alpha", "agent_experimental"}
    ]
    sector = group_exposure(alpha_allocations, "sector")
    theme = group_exposure(alpha_allocations, "theme")
    sector_values = list(sector.values())
    theme_values = list(theme.values())
    return {
        "top3_weight": round(top_n_weight(alpha_allocations, 3), 6),
        "max_symbol_weight": round(max([float(row.get("weight", 0.0)) for row in allocations] or [0.0]), 6),
        "max_sector_weight": round(max(sector_values or [0.0]), 6),
        "max_theme_weight": round(max(theme_values or [0.0]), 6),
    }


def _worse(current: str, candidate: str) -> str:
    order = {"GREEN": 0, "YELLOW": 1, "RED": 2, "BLACK": 3}
    return candidate if order[candidate] > order[current] else current
