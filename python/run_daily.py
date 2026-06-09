"""Daily Greenlight Trader runner."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from allocator import allocate_targets, write_target_allocations
from config import DATA_DIR, MANDATE
from data_contracts import read_json, write_json
from decision_log import append_decision_log, build_decision_log, load_decision_history
from etf_selector import select_dynamic_etfs, write_selected_etfs
from execution_policy import decide_execution, write_execution_decision
from features import compute_features, write_features
from massive_client import MassiveClient
from portfolio import PaperPortfolio
from regime import determine_regime
from risk import evaluate_risk, write_risk_status
from scoring import score_candidates, write_candidate_scores
from strategy_benchmarks import run_benchmarks
from universe import build_universe, candidate_symbols, write_candidate_universe
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def main() -> None:
    as_of = date.today().isoformat()
    client = MassiveClient()
    portfolio = PaperPortfolio.load()

    universe_payload = build_universe(as_of=as_of, client=client, current_holdings=list(portfolio.positions))
    symbols = candidate_symbols(universe_payload)
    start_date = (date.today() - timedelta(days=420)).isoformat()
    critical_symbols = {
        MANDATE.benchmark,
        MANDATE.secondary_growth_anchor,
        MANDATE.defensive_anchor,
        *portfolio.positions,
    }
    price_history, data_health = client.load_price_history(
        symbols,
        start_date,
        as_of,
        allow_synthetic=True,
        optional_symbols=set(symbols) - critical_symbols,
    )
    latest_prices = _latest_prices(price_history)
    portfolio.mark_to_market(latest_prices)

    feature_payload = compute_features(universe_payload, price_history, as_of, portfolio.weights())
    regime_payload = determine_regime(price_history, feature_payload, data_health, as_of)
    score_payload = score_candidates(feature_payload, regime_payload, as_of=as_of)
    etf_payload = select_dynamic_etfs(score_payload, feature_payload, regime_payload, as_of)
    target_payload = allocate_targets(score_payload, feature_payload, etf_payload, regime_payload, as_of)
    risk_payload = evaluate_risk(portfolio.snapshot(), target_payload, data_health, regime_payload, as_of)
    execution_payload = decide_execution(portfolio.snapshot(), target_payload, risk_payload, load_decision_history(), as_of)

    orders = portfolio.rebalance_to_targets(
        target_payload.get("target_allocations", []),
        latest_prices,
        execution_payload,
        as_of,
    )
    if orders:
        execution_payload["execution_decision"]["orders"] = orders
    portfolio.mark_to_market(latest_prices)
    _update_relative_benchmark_state(portfolio, price_history)
    portfolio.save()

    strategy_equity = _strategy_equity_from_snapshots(portfolio.nav(), as_of)
    benchmark_payload = run_benchmarks(price_history, strategy_equity=strategy_equity, as_of=as_of)

    benchmark_snapshot = _benchmark_snapshot(price_history, benchmark_payload)
    decision_payload = build_decision_log(
        universe_payload,
        score_payload,
        etf_payload,
        regime_payload,
        target_payload,
        risk_payload,
        execution_payload,
        {},
        portfolio.snapshot(),
        benchmark_snapshot,
        as_of,
    )
    decision_logs_payload = append_decision_log(decision_payload)

    _append_snapshot(portfolio, benchmark_snapshot, risk_payload, regime_payload, execution_payload, as_of)
    _write_system_status(as_of, data_health, risk_payload, regime_payload, client.availability_report(), decision_logs_payload)

    write_candidate_universe(universe_payload)
    write_features(feature_payload)
    write_candidate_scores(score_payload)
    write_selected_etfs(etf_payload)
    write_target_allocations(target_payload)
    write_risk_status(risk_payload)
    write_execution_decision(execution_payload)


def _latest_prices(price_history: dict[str, pd.DataFrame]) -> dict[str, float]:
    prices = {}
    for symbol, frame in price_history.items():
        if frame is not None and not frame.empty:
            prices[symbol] = float(frame["close"].iloc[-1])
    return prices


def _benchmark_snapshot(price_history: dict[str, pd.DataFrame], benchmark_payload: dict[str, Any]) -> dict[str, Any]:
    out = {"watermark": SYSTEMATIC_TEMPLATE_OUTPUT}
    for symbol in ("SPY", "QQQ"):
        frame = price_history.get(symbol)
        if frame is not None and len(frame) > 1:
            out[symbol] = {
                "close": round(float(frame["close"].iloc[-1]), 4),
                "daily_return": round(float(frame["close"].iloc[-1] / frame["close"].iloc[-2] - 1), 6),
            }
    out["verdict"] = benchmark_payload.get("verdict", {})
    return out


def _append_snapshot(
    portfolio: PaperPortfolio,
    benchmark_snapshot: dict[str, Any],
    risk_payload: dict[str, Any],
    regime_payload: dict[str, Any],
    execution_payload: dict[str, Any],
    as_of: str,
) -> None:
    path = DATA_DIR / "snapshots.json"
    existing = read_json(path, default={"watermark": SYSTEMATIC_TEMPLATE_OUTPUT, "snapshots": []})
    snapshots = existing.get("snapshots", []) if isinstance(existing, dict) else []
    snapshots = [row for row in snapshots if row.get("date") != as_of]
    snapshots.append(
        {
            "date": as_of,
            "nav": round(portfolio.nav(), 4),
            "cash": round(portfolio.cash, 4),
            "weights": portfolio.weights(),
            "market_regime": regime_payload.get("regime"),
            "risk_light": risk_payload.get("risk_status", {}).get("light"),
            "execution_decision": execution_payload.get("execution_decision", {}).get("decision"),
            "benchmark_snapshot": benchmark_snapshot,
            "watermark": SYSTEMATIC_TEMPLATE_OUTPUT,
        }
    )
    write_json(path, add_watermark({"snapshots": sorted(snapshots, key=lambda row: row["date"])[-1000:]}, SYSTEMATIC_TEMPLATE_OUTPUT))


def _write_system_status(
    as_of: str,
    data_health: dict[str, Any],
    risk_payload: dict[str, Any],
    regime_payload: dict[str, Any],
    endpoint_availability: dict[str, Any],
    decision_logs_payload: dict[str, Any],
) -> None:
    payload = add_watermark(
        {
            "latest_run_date": as_of,
            "risk_light": risk_payload.get("risk_status", {}).get("light"),
            "market_regime": regime_payload.get("regime"),
            "data_health": data_health,
            "endpoint_availability": endpoint_availability,
            "watermark_status": "present",
            "decision_log_count": len(decision_logs_payload.get("logs", [])),
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )
    write_json(DATA_DIR / "system_status.json", payload)


def _strategy_equity_from_snapshots(current_nav: float, as_of: str) -> pd.Series:
    payload = read_json(DATA_DIR / "snapshots.json", default={"snapshots": []})
    rows = payload.get("snapshots", []) if isinstance(payload, dict) else []
    rows = [row for row in rows if row.get("date") != as_of]
    rows.append({"date": as_of, "nav": current_nav})
    if not rows:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")["nav"].astype(float).sort_index()


def _update_relative_benchmark_state(portfolio: PaperPortfolio, price_history: dict[str, pd.DataFrame]) -> None:
    spy = price_history.get(MANDATE.benchmark)
    if spy is None or len(spy) < 2:
        return
    daily_return = float(spy["close"].iloc[-1] / spy["close"].iloc[-2] - 1)
    portfolio.benchmark_equity *= 1 + daily_return
    portfolio_return = portfolio.nav() / MANDATE.starting_capital - 1
    benchmark_return = portfolio.benchmark_equity / MANDATE.starting_capital - 1
    relative = portfolio_return - benchmark_return
    portfolio.peak_relative_outperformance = max(portfolio.peak_relative_outperformance, relative)
    portfolio.relative_drawdown_pct = max(0.0, portfolio.peak_relative_outperformance - relative)


if __name__ == "__main__":
    main()
