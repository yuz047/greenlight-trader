"""Decision ledger."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from config import DATA_DIR
from data_contracts import DecisionLog, read_json, write_json
from exposure import weights_from_allocations
from watermark import (
    AI_GENERATED_AGENT_DECISION_EXPERIMENTAL,
    SYSTEMATIC_TEMPLATE_OUTPUT,
    add_watermark,
)


def build_decision_log(
    universe_payload: dict[str, Any],
    score_payload: dict[str, Any],
    etf_payload: dict[str, Any],
    regime_payload: dict[str, Any],
    target_payload: dict[str, Any],
    risk_payload: dict[str, Any],
    execution_payload: dict[str, Any],
    agent_payload: dict[str, Any],
    portfolio_snapshot: dict[str, Any],
    benchmark_snapshot: dict[str, Any],
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    risk_status = risk_payload.get("risk_status", {})
    execution = execution_payload.get("execution_decision", {})
    top_stocks = [
        row for row in score_payload.get("scores", [])
        if row.get("asset_type") == "stock" and row.get("investable_flag")
    ][:10]
    log = DecisionLog(
        date=as_of,
        market_regime=regime_payload.get("regime", "UNKNOWN"),
        risk_light=risk_status.get("light", "UNKNOWN"),
        data_health=risk_status.get("data_health", {}),
        universe_size=len(universe_payload.get("candidates", [])),
        selected_etfs=etf_payload.get("selected_etfs", []),
        rejected_etfs=etf_payload.get("rejected_etfs", []),
        top_stock_candidates=top_stocks,
        candidate_score_summary=score_payload.get("summary", {}),
        current_allocation=portfolio_snapshot.get("weights", {}),
        target_allocation=weights_from_allocations(target_payload.get("target_allocations", [])),
        systematic_decision={
            "target_allocations": target_payload.get("target_allocations", []),
            "risk_status": risk_status,
        },
        agent_led_decision=agent_payload,
        execution_decision=execution.get("decision", "NO_TRADE"),
        execution_reason=execution.get("reason", "not evaluated"),
        orders=execution.get("orders", []),
        portfolio_snapshot=portfolio_snapshot,
        benchmark_snapshot=benchmark_snapshot,
        watermarks=[SYSTEMATIC_TEMPLATE_OUTPUT, AI_GENERATED_AGENT_DECISION_EXPERIMENTAL],
    )
    return add_watermark(asdict(log), SYSTEMATIC_TEMPLATE_OUTPUT)


def append_decision_log(log_payload: dict[str, Any]) -> dict[str, Any]:
    path = DATA_DIR / "decision_logs.json"
    existing = read_json(path, default={"watermark": SYSTEMATIC_TEMPLATE_OUTPUT, "logs": []})
    logs = existing.get("logs", []) if isinstance(existing, dict) else []
    logs = [row for row in logs if row.get("date") != log_payload.get("date")]
    logs.append(log_payload)
    logs = sorted(logs, key=lambda row: row.get("date", ""))[-750:]
    payload = add_watermark({"logs": logs}, SYSTEMATIC_TEMPLATE_OUTPUT)
    write_json(path, payload)
    return payload


def load_decision_history() -> list[dict[str, Any]]:
    payload = read_json(DATA_DIR / "decision_logs.json", default={"logs": []})
    return payload.get("logs", []) if isinstance(payload, dict) else []
