"""Exposure calculations and caps."""
from __future__ import annotations

from typing import Any

from config import MANDATE


def weights_from_allocations(allocations: list[dict[str, Any]]) -> dict[str, float]:
    return {row["symbol"]: float(row["weight"]) for row in allocations if float(row.get("weight", 0.0)) > 0}


def group_exposure(allocations: list[dict[str, Any]], key: str) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for row in allocations:
        group = row.get(key) or "Unknown"
        exposure[group] = exposure.get(group, 0.0) + float(row.get("weight", 0.0))
    return dict(sorted(exposure.items(), key=lambda item: item[1], reverse=True))


def top_n_weight(allocations: list[dict[str, Any]], n: int = 3) -> float:
    weights = sorted([float(row.get("weight", 0.0)) for row in allocations], reverse=True)
    return sum(weights[:n])


def apply_exposure_caps(allocations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, list[str]]:
    """Reduce allocations that violate concentration caps.

    Returns adjusted allocations, leftover weight, and cap reasons. Leftover is
    normally routed to the defensive sleeve by the allocator.
    """

    adjusted = [dict(row) for row in allocations]
    leftover = 0.0
    reasons: list[str] = []

    for row in adjusted:
        weight = float(row.get("weight", 0.0))
        if row.get("asset_type") == "stock" and weight > MANDATE.max_single_stock_weight:
            leftover += weight - MANDATE.max_single_stock_weight
            row["weight"] = MANDATE.max_single_stock_weight
            reasons.append(f"{row['symbol']} capped at max_single_stock_weight")
        if row.get("asset_type") == "etf" and weight > MANDATE.max_etf_weight:
            leftover += weight - MANDATE.max_etf_weight
            row["weight"] = MANDATE.max_etf_weight
            reasons.append(f"{row['symbol']} capped at max_etf_weight")

    alpha_rows = _concentration_cap_scope(adjusted)
    leftover += _cap_group(alpha_rows, "sector", MANDATE.max_sector_weight, reasons)
    leftover += _cap_group(alpha_rows, "theme", MANDATE.max_theme_weight, reasons)

    top3 = top_n_weight(alpha_rows, 3)
    if top3 > MANDATE.max_top3_weight:
        scale = MANDATE.max_top3_weight / top3
        ranked = sorted(alpha_rows, key=lambda row: row.get("weight", 0.0), reverse=True)
        top_symbols = {row["symbol"] for row in ranked[:3]}
        for row in adjusted:
            if row["symbol"] in top_symbols:
                old = float(row["weight"])
                row["weight"] = old * scale
                leftover += old - float(row["weight"])
        reasons.append("top_3_weight capped")

    return adjusted, leftover, reasons


def _concentration_cap_scope(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row.get("sleeve") in {"dynamic_etf", "stock_alpha", "agent_experimental"}
    ]


def _cap_group(rows: list[dict[str, Any]], key: str, cap: float, reasons: list[str]) -> float:
    leftover = 0.0
    groups = group_exposure(rows, key)
    for group, total in groups.items():
        if group == "Unknown" or total <= cap:
            continue
        scale = cap / total
        for row in rows:
            if (row.get(key) or "Unknown") == group:
                old = float(row["weight"])
                row["weight"] = old * scale
                leftover += old - float(row["weight"])
        reasons.append(f"{key}_{group}_capped")
    return leftover
