"""Sparse execution policy."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from config import DATA_DIR, MANDATE
from data_contracts import ExecutionDecision, write_json
from exposure import weights_from_allocations
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def decide_execution(
    portfolio_state: dict[str, Any],
    target_payload: dict[str, Any],
    risk_payload: dict[str, Any],
    decision_history: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    decision_history = decision_history or []
    risk_status = risk_payload.get("risk_status", {})
    risk_light = risk_status.get("light", "BLACK")
    current_weights = {k: float(v) for k, v in portfolio_state.get("weights", {}).items()}
    target_weights = weights_from_allocations(target_payload.get("target_allocations", []))
    drift = _max_drift(current_weights, target_weights)
    turnover = _turnover(current_weights, target_weights)

    if risk_light == "BLACK":
        decision = ExecutionDecision(as_of, "DATA_HALT", "Risk light BLACK: no trading on failed/fallback data.", [], turnover, drift)
        return add_watermark({"execution_decision": asdict(decision)}, SYSTEMATIC_TEMPLATE_OUTPUT)

    if risk_light == "RED":
        decision = ExecutionDecision(as_of, "RISK_REDUCE", "Risk light RED: only de-risking rebalance is allowed.", [], min(turnover, MANDATE.max_daily_turnover), drift)
        return add_watermark({"execution_decision": asdict(decision)}, SYSTEMATIC_TEMPLATE_OUTPUT)

    if drift < MANDATE.drift_threshold:
        decision = ExecutionDecision(as_of, "NO_TRADE", f"Max drift {drift:.2%} is below threshold {MANDATE.drift_threshold:.2%}.", [], turnover, drift)
        return add_watermark({"execution_decision": asdict(decision)}, SYSTEMATIC_TEMPLATE_OUTPUT)

    days_since = _days_since_rebalance(portfolio_state.get("last_rebalance_date"), as_of)
    has_positions = bool(portfolio_state.get("positions"))
    if has_positions and days_since < MANDATE.min_rebalance_days:
        decision = ExecutionDecision(as_of, "NO_TRADE", f"Only {days_since} days since last rebalance; minimum is {MANDATE.min_rebalance_days}.", [], turnover, drift)
        return add_watermark({"execution_decision": asdict(decision)}, SYSTEMATIC_TEMPLATE_OUTPUT)

    if has_positions and not _signal_persistent(decision_history, target_weights):
        decision = ExecutionDecision(as_of, "NO_TRADE", f"Target drift has not persisted for {MANDATE.signal_persistence_days} decision days.", [], turnover, drift)
        return add_watermark({"execution_decision": asdict(decision)}, SYSTEMATIC_TEMPLATE_OUTPUT)

    if has_positions and turnover > MANDATE.max_daily_turnover:
        decision = ExecutionDecision(as_of, "NO_TRADE", f"Turnover {turnover:.2%} exceeds cap {MANDATE.max_daily_turnover:.2%}.", [], turnover, drift)
        return add_watermark({"execution_decision": asdict(decision)}, SYSTEMATIC_TEMPLATE_OUTPUT)

    reason = (
        "Initial allocation from cash passed risk and drift gates."
        if not has_positions
        else "Drift threshold, persistence, rebalance interval, turnover, and risk gates passed."
    )
    decision = ExecutionDecision(as_of, "EXECUTE", reason, [], turnover, drift)
    return add_watermark({"execution_decision": asdict(decision)}, SYSTEMATIC_TEMPLATE_OUTPUT)


def write_execution_decision(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "execution_decisions.json", payload)


def _max_drift(current: dict[str, float], target: dict[str, float]) -> float:
    symbols = set(current) | set(target)
    return max([abs(current.get(symbol, 0.0) - target.get(symbol, 0.0)) for symbol in symbols] or [0.0])


def _turnover(current: dict[str, float], target: dict[str, float]) -> float:
    symbols = set(current) | set(target)
    return sum(abs(current.get(symbol, 0.0) - target.get(symbol, 0.0)) for symbol in symbols) / 2


def _days_since_rebalance(last_rebalance_date: str | None, as_of: str) -> int:
    if not last_rebalance_date:
        return 10_000
    try:
        return (datetime.fromisoformat(as_of).date() - datetime.fromisoformat(last_rebalance_date).date()).days
    except ValueError:
        return 10_000


def _signal_persistent(history: list[dict[str, Any]], target: dict[str, float]) -> bool:
    if MANDATE.signal_persistence_days <= 1:
        return True
    recent = history[-MANDATE.signal_persistence_days + 1 :]
    if len(recent) < MANDATE.signal_persistence_days - 1:
        return False
    target_symbols = {symbol for symbol, weight in target.items() if weight > 0.01}
    for log in recent:
        logged_target = log.get("target_allocation") or {}
        logged_symbols = {symbol for symbol, weight in logged_target.items() if float(weight) > 0.01}
        if len(target_symbols & logged_symbols) < max(1, len(target_symbols) // 2):
            return False
    return True
