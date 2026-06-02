"""Portfolio allocator: scores to target weights."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from config import DATA_DIR, MANDATE, REGIME_BUDGETS
from data_contracts import TargetAllocation, write_json
from exposure import apply_exposure_caps, group_exposure, top_n_weight
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def allocate_targets(
    score_payload: dict[str, Any],
    feature_payload: dict[str, Any],
    selected_etfs_payload: dict[str, Any],
    regime_payload: dict[str, Any],
    as_of: str | None = None,
    budget_overrides: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    as_of = as_of or score_payload.get("as_of") or date.today().isoformat()
    regime = regime_payload.get("regime", "DATA_FAILURE")
    source_budgets = budget_overrides or REGIME_BUDGETS
    budgets = dict(source_budgets.get(regime, source_budgets.get("DATA_FAILURE", REGIME_BUDGETS["DATA_FAILURE"])))
    features = {row["symbol"]: row for row in feature_payload.get("feature_rows", [])}
    scores = {row["symbol"]: row for row in score_payload.get("scores", [])}

    allocations: list[TargetAllocation] = []
    leftover = 0.0

    leftover += _add_anchor(allocations, MANDATE.benchmark, budgets["spy"], "SPY core anchor", features)
    leftover += _add_anchor(
        allocations,
        MANDATE.secondary_growth_anchor,
        budgets["qqq"],
        "regime-dependent Nasdaq/growth anchor",
        features,
    )

    selected_symbols = [row["symbol"] for row in selected_etfs_payload.get("selected_etfs", [])]
    etf_rows = [scores[s] for s in selected_symbols if s in scores]
    etf_allocs, unused = _allocate_pool(etf_rows, features, budgets["dynamic_etf"], "dynamic_etf")
    leftover += unused
    allocations.extend(etf_allocs)

    stock_rows = [
        row
        for row in score_payload.get("scores", [])
        if row.get("asset_type") == "stock"
        and row.get("investable_flag")
        and not row.get("wait_flag")
        and float(row.get("final_score", 0.0)) >= 0.38
    ][: MANDATE.max_candidates_per_sleeve]
    stock_allocs, unused = _allocate_pool(stock_rows, features, budgets["stock"], "stock_alpha")
    leftover += unused
    allocations.extend(stock_allocs)

    defensive_weight = budgets["defensive"] + leftover
    if defensive_weight > 0:
        _add_anchor(allocations, MANDATE.defensive_anchor, min(defensive_weight, MANDATE.max_cash_or_defensive_weight), "defensive/cash sleeve", features)

    allocation_dicts = [asdict(row) for row in allocations if row.weight > 0]
    allocation_dicts, cap_leftover, cap_reasons = apply_exposure_caps(allocation_dicts)
    if cap_leftover > 0:
        _merge_defensive(allocation_dicts, cap_leftover, features)

    total = sum(float(row["weight"]) for row in allocation_dicts)
    if total > 1.0:
        scale = 1.0 / total
        for row in allocation_dicts:
            row["weight"] = float(row["weight"]) * scale
    else:
        residual = 1.0 - total
        if residual > 0.0001:
            _merge_defensive(allocation_dicts, residual, features)

    for row in allocation_dicts:
        row["weight"] = round(float(row["weight"]), 6)

    return add_watermark(
        {
            "as_of": as_of,
            "regime": regime,
            "budgets": budgets,
            "target_allocations": sorted(allocation_dicts, key=lambda row: row["weight"], reverse=True),
            "exposure": {
                "sector": group_exposure(allocation_dicts, "sector"),
                "theme": group_exposure(allocation_dicts, "theme"),
                "top3_weight": round(top_n_weight(allocation_dicts, 3), 6),
            },
            "cap_reasons": cap_reasons,
            "rules": [
                "Allocator outputs target weights, not raw buy/sell calls.",
                "QQQ allocation is regime-dependent.",
                "Dynamic ETFs earn allocation through score.",
                "Unused alpha budget routes to defensive sleeve.",
            ],
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def write_target_allocations(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "target_allocations.json", payload)


def _add_anchor(
    allocations: list[TargetAllocation],
    symbol: str,
    weight: float,
    reason: str,
    features: dict[str, dict[str, Any]],
) -> float:
    if weight <= 0:
        return 0.0
    row = features.get(symbol, {})
    if row and row.get("investable_flag") is False and symbol != MANDATE.defensive_anchor:
        return weight
    allocations.append(
        TargetAllocation(
            symbol=symbol,
            weight=weight,
            sleeve="core" if symbol in (MANDATE.benchmark, MANDATE.secondary_growth_anchor) else "defensive",
            reason=reason,
            asset_type=row.get("asset_type", "benchmark" if symbol != MANDATE.defensive_anchor else "cash_proxy"),
            sector=row.get("sector"),
            theme=row.get("theme"),
        )
    )
    return 0.0


def _allocate_pool(
    score_rows: list[dict[str, Any]],
    features: dict[str, dict[str, Any]],
    budget: float,
    sleeve: str,
) -> tuple[list[TargetAllocation], float]:
    if budget <= 0:
        return [], 0.0
    strengths: list[tuple[dict[str, Any], float]] = []
    for score in score_rows:
        feature = features.get(score["symbol"], {})
        volatility = max(float(feature.get("realized_volatility") or MANDATE.volatility_floor), MANDATE.volatility_floor)
        raw = (
            float(score.get("final_score") or 0.0)
            * float(score.get("timing_multiplier") or 1.0)
            * float(score.get("data_quality_multiplier") or 1.0)
        )
        if not score.get("investable_flag"):
            raw = 0.0
        strengths.append((score, raw / volatility if volatility > 0 else 0.0))

    total_strength = sum(strength for _, strength in strengths if strength > 0)
    if total_strength <= 0:
        return [], budget

    out = []
    for score, strength in strengths:
        if strength <= 0:
            continue
        symbol = score["symbol"]
        feature = features.get(symbol, {})
        weight = budget * strength / total_strength
        out.append(
            TargetAllocation(
                symbol=symbol,
                weight=weight,
                sleeve=sleeve,
                reason=f"risk-adjusted score allocation from {score.get('final_score')}",
                asset_type=feature.get("asset_type", score.get("asset_type")),
                sector=feature.get("sector"),
                theme=feature.get("theme"),
            )
        )
    return out, 0.0


def _merge_defensive(allocations: list[dict[str, Any]], add_weight: float, features: dict[str, dict[str, Any]]) -> None:
    if add_weight <= 0:
        return
    for row in allocations:
        if row["symbol"] == MANDATE.defensive_anchor:
            row["weight"] = min(MANDATE.max_cash_or_defensive_weight, float(row["weight"]) + add_weight)
            return
    feature = features.get(MANDATE.defensive_anchor, {})
    allocations.append(
        {
            "symbol": MANDATE.defensive_anchor,
            "weight": min(MANDATE.max_cash_or_defensive_weight, add_weight),
            "sleeve": "defensive",
            "reason": "residual/unallocated risk budget",
            "asset_type": feature.get("asset_type", "cash_proxy"),
            "sector": feature.get("sector"),
            "theme": feature.get("theme"),
        }
    )
