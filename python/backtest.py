"""Backtest engine for Greenlight 2.0."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from typing import Any

import pandas as pd

from agent_decision import build_agent_led_decision
from ai_review import build_ai_memo, build_systematic_review
from allocator import allocate_targets
from comparison_report import write_comparison_report
from config import DATA_DIR, MANDATE
from data_contracts import write_json
from decision_log import build_decision_log
from etf_selector import select_dynamic_etfs
from execution_policy import decide_execution
from features import compute_features
from massive_client import MassiveClient
from portfolio import PaperPortfolio
from regime import determine_regime
from risk import evaluate_risk
from scoring import score_candidates
from strategy_benchmarks import run_benchmarks, write_benchmark_outputs
from universe import build_universe, candidate_symbols
from watermark import AI_GENERATED_MEMO, SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark
from weight_learning import learn_weights, write_learning_report
from weight_review import review_candidate_weights


BUDGET_PRESETS: dict[str, dict[str, dict[str, float]] | None] = {
    "default": None,
    "growth_tilt": {
        "RISK_ON": {"spy": 0.35, "qqq": 0.25, "dynamic_etf": 0.20, "stock": 0.20, "defensive": 0.00, "agent_experimental": 0.00},
        "NEUTRAL": {"spy": 0.40, "qqq": 0.15, "dynamic_etf": 0.15, "stock": 0.15, "defensive": 0.15, "agent_experimental": 0.00},
        "FEAR": {"spy": 0.25, "qqq": 0.05, "dynamic_etf": 0.05, "stock": 0.05, "defensive": 0.60, "agent_experimental": 0.00},
        "STRESS": {"spy": 0.20, "qqq": 0.00, "dynamic_etf": 0.00, "stock": 0.00, "defensive": 0.80, "agent_experimental": 0.00},
        "DATA_FAILURE": {"spy": 0.00, "qqq": 0.00, "dynamic_etf": 0.00, "stock": 0.00, "defensive": 1.00, "agent_experimental": 0.00},
    },
    "alpha_tilt": {
        "RISK_ON": {"spy": 0.30, "qqq": 0.25, "dynamic_etf": 0.25, "stock": 0.20, "defensive": 0.00, "agent_experimental": 0.00},
        "NEUTRAL": {"spy": 0.35, "qqq": 0.15, "dynamic_etf": 0.15, "stock": 0.20, "defensive": 0.15, "agent_experimental": 0.00},
        "FEAR": {"spy": 0.25, "qqq": 0.05, "dynamic_etf": 0.05, "stock": 0.05, "defensive": 0.60, "agent_experimental": 0.00},
        "STRESS": {"spy": 0.20, "qqq": 0.00, "dynamic_etf": 0.00, "stock": 0.00, "defensive": 0.80, "agent_experimental": 0.00},
        "DATA_FAILURE": {"spy": 0.00, "qqq": 0.00, "dynamic_etf": 0.00, "stock": 0.00, "defensive": 1.00, "agent_experimental": 0.00},
    },
    "stock_alpha_tilt": {
        "RISK_ON": {"spy": 0.30, "qqq": 0.20, "dynamic_etf": 0.15, "stock": 0.30, "defensive": 0.05, "agent_experimental": 0.00},
        "NEUTRAL": {"spy": 0.35, "qqq": 0.10, "dynamic_etf": 0.10, "stock": 0.25, "defensive": 0.20, "agent_experimental": 0.00},
        "FEAR": {"spy": 0.25, "qqq": 0.05, "dynamic_etf": 0.05, "stock": 0.05, "defensive": 0.60, "agent_experimental": 0.00},
        "STRESS": {"spy": 0.20, "qqq": 0.00, "dynamic_etf": 0.00, "stock": 0.00, "defensive": 0.80, "agent_experimental": 0.00},
        "DATA_FAILURE": {"spy": 0.00, "qqq": 0.00, "dynamic_etf": 0.00, "stock": 0.00, "defensive": 1.00, "agent_experimental": 0.00},
    },
}


def run_backtest(
    start_date: str,
    end_date: str,
    train_start: str | None = None,
    train_end: str = "2020-12-31",
    invest_start: str = "2021-01-01",
    max_symbols: int | None = None,
    allow_synthetic_trading: bool = False,
    use_secondary_price_fallback: bool = True,
    rolling_train_years: int = 12,
    ai_memo_mode: str = "template",
    ai_memo_frequency: str = "weekly",
    budget_preset: str = "default",
    step_days: int = 1,
    train_step_days: int | None = None,
) -> dict[str, Any]:
    train_start = train_start or start_date
    train_step_days = train_step_days or step_days
    budget_overrides = BUDGET_PRESETS.get(budget_preset)
    client = MassiveClient()
    universe_payload = build_universe(as_of=end_date, client=client)
    symbols = candidate_symbols(universe_payload)
    if max_symbols:
        core = ["SPY", "QQQ", "SGOV", "^VIX"]
        rest = [s for s in symbols if s not in core][: max(0, max_symbols - len(core))]
        symbols = sorted(set(core + rest))
        universe_payload["candidates"] = [row for row in universe_payload["candidates"] if row["symbol"] in symbols]

    fetch_start = (pd.Timestamp(train_start) - pd.Timedelta(days=430)).date().isoformat()
    price_history, data_health = client.load_price_history(
        symbols,
        fetch_start,
        end_date,
        allow_synthetic=True,
        allow_secondary_price_fallback=use_secondary_price_fallback,
    )
    loop_health = dict(data_health)
    if allow_synthetic_trading and loop_health.get("synthetic"):
        loop_health["ok"] = True
        loop_health["synthetic"] = False
        loop_health["source"] = "fallback.synthetic_research_only"

    print(
        (
            f"Backtest data loaded: {len(symbols)} symbols, initial train {train_start}..{train_end}, "
            f"rolling {rolling_train_years}y, invest {invest_start}..{end_date}"
        ),
        flush=True,
    )
    learning_rows = _collect_training_rows(
        universe_payload=universe_payload,
        price_history=price_history,
        data_health=loop_health,
        train_start=train_start,
        train_end=end_date,
        step_days=train_step_days,
    )

    portfolio = PaperPortfolio()
    decision_history: list[dict[str, Any]] = []
    ai_review_history: list[dict[str, Any]] = []
    ai_provider_weeks: set[tuple[int, int]] = set()
    ai_provider_months: set[tuple[int, int]] = set()
    ai_provider_call_count = 0
    weight_history: list[dict[str, Any]] = []
    equity_rows = []
    agent_equity_rows = []
    latest_stock_learning = learn_weights([], "stock", as_of=train_end)
    latest_etf_learning = learn_weights([], "etf", as_of=train_end)
    latest_benchmarks: dict[str, Any] = {}
    dates = pd.bdate_range(invest_start, end_date)
    dates = dates[:: max(1, step_days)]
    total_invest_dates = len(dates)
    print(f"Investment replay dates: {total_invest_dates}", flush=True)
    for i, ts in enumerate(dates, start=1):
        as_of = ts.date().isoformat()
        latest_prices = _prices_as_of(price_history, as_of)
        if "SPY" not in latest_prices:
            continue
        portfolio.mark_to_market(latest_prices)
        daily_universe = _universe_as_of(universe_payload, price_history, as_of, list(portfolio.positions))
        rolling = _learn_rolling_weights(
            learning_rows=learning_rows,
            as_of=as_of,
            earliest_train_start=train_start,
            rolling_years=rolling_train_years,
        )
        latest_stock_learning = rolling["stock_learning"]
        latest_etf_learning = rolling["etf_learning"]
        stock_weights = latest_stock_learning.get("weights")
        etf_weights = latest_etf_learning.get("weights")
        weight_history.append(rolling["snapshot"])

        feature_payload = compute_features(daily_universe, price_history, as_of, portfolio.weights())
        regime_payload = determine_regime(price_history, feature_payload, loop_health, as_of)
        score_payload = score_candidates(feature_payload, regime_payload, stock_weights=stock_weights, etf_weights=etf_weights, as_of=as_of)
        etf_payload = select_dynamic_etfs(score_payload, feature_payload, regime_payload, as_of)
        target_payload = allocate_targets(
            score_payload,
            feature_payload,
            etf_payload,
            regime_payload,
            as_of,
            budget_overrides=budget_overrides,
        )
        risk_payload = evaluate_risk(portfolio.snapshot(), target_payload, loop_health, regime_payload, as_of)
        execution_payload = decide_execution(portfolio.snapshot(), target_payload, risk_payload, decision_history, as_of)
        orders = portfolio.rebalance_to_targets(target_payload.get("target_allocations", []), latest_prices, execution_payload, as_of)
        if orders:
            execution_payload["execution_decision"]["orders"] = orders
        agent_payload = build_agent_led_decision(target_payload, score_payload, risk_payload, as_of)
        portfolio.mark_to_market(latest_prices)
        _update_relative_state(portfolio, price_history, as_of)
        equity_rows.append({"date": as_of, "equity": portfolio.nav()})
        agent_equity_rows.append({"date": as_of, "equity": portfolio.nav()})
        if ai_memo_mode != "off":
            strategy_equity_so_far = _equity_series(equity_rows)
            agent_equity_so_far = _equity_series(agent_equity_rows)
            latest_benchmarks = run_benchmarks(
                _slice_history(price_history, invest_start, as_of),
                strategy_equity=strategy_equity_so_far,
                learned_equity=strategy_equity_so_far,
                agent_equity=agent_equity_so_far,
                as_of=as_of,
            )
        else:
            latest_benchmarks = {}
        decision_log = build_decision_log(
            daily_universe,
            score_payload,
            etf_payload,
            regime_payload,
            target_payload,
            risk_payload,
            execution_payload,
            agent_payload,
            portfolio.snapshot(),
            _benchmark_snapshot(latest_prices, latest_benchmarks),
            as_of,
        )
        decision_history.append(decision_log)
        if ai_memo_mode != "off":
            review = build_systematic_review(decision_log, latest_benchmarks, as_of)
            use_provider = ai_memo_mode == "deepseek" and _should_call_ai_provider(
                as_of,
                i,
                total_invest_dates,
                ai_memo_frequency,
                ai_provider_weeks,
                ai_provider_months,
            )
            memo = build_ai_memo(review, use_provider=use_provider)
            if use_provider and "Provider: DeepSeek" in memo:
                ai_provider_call_count += 1
            ai_review_history.append(
                {
                    "systematic_review": review,
                    "memo": memo,
                    "provider_requested": use_provider,
                    "watermark": AI_GENERATED_MEMO,
                }
            )
        if i == 1 or i % 100 == 0 or i == total_invest_dates:
            print(
                (
                    f"Investment replay {i}/{total_invest_dates}: {as_of} nav={portfolio.nav():.2f} "
                    f"train_rows={rolling['snapshot']['usable_rows']}"
                ),
                flush=True,
            )

    strategy_equity = _equity_series(equity_rows)
    agent_equity = _equity_series(agent_equity_rows)
    benchmark_history = _slice_history(price_history, invest_start, end_date)
    benchmarks = run_benchmarks(
        benchmark_history,
        strategy_equity=strategy_equity,
        learned_equity=strategy_equity,
        agent_equity=agent_equity,
        as_of=end_date,
    )
    write_benchmark_outputs(benchmarks)
    write_comparison_report(benchmarks)
    write_learning_report(latest_stock_learning, latest_etf_learning)
    review_candidate_weights(latest_stock_learning, end_date)
    write_json(DATA_DIR / "ai_reviews.json", add_watermark({"reviews": ai_review_history[-50:]}, SYSTEMATIC_TEMPLATE_OUTPUT))

    public_decision_history = [_public_decision_log(row) for row in decision_history]

    payload = add_watermark(
        {
            "start_date": start_date,
            "end_date": end_date,
            "train_start": train_start,
            "initial_train_end": train_end,
            "invest_start": invest_start,
            "rolling_training": {
                "enabled": True,
                "window_years": rolling_train_years,
                "updated_every_replay_day": True,
                "initial_window": [train_start, train_end],
                "final_window": weight_history[-1]["window"] if weight_history else None,
                "updates": len(weight_history),
            },
            "latest_learned_weights": {
                "stock": latest_stock_learning.get("weights"),
                "etf": latest_etf_learning.get("weights"),
            },
            "learning_row_pool": {
                "total": len(learning_rows),
                "stock": len([row for row in learning_rows if row["asset_type"] == "stock"]),
                "etf": len([row for row in learning_rows if row["asset_type"] == "etf"]),
            },
            "weight_history": weight_history[-250:],
            "research_windows": {
                "full": ["2009-01-01", end_date],
                "initial_train": [train_start, train_end],
                "investment_test": [invest_start, end_date],
                "walk_forward": "rolling daily retraining; rows are allowed only when label_end_date < replay date",
            },
            "allow_synthetic_trading": allow_synthetic_trading,
            "use_secondary_price_fallback": use_secondary_price_fallback,
            "ai_memo_mode": ai_memo_mode,
            "ai_memo_frequency": ai_memo_frequency,
            "budget_preset": budget_preset,
            "ai_review_count": len(ai_review_history),
            "ai_provider_call_count": ai_provider_call_count,
            "data_health": data_health,
            "equity_curve": [{"date": row["date"], "equity": round(row["equity"], 4)} for row in equity_rows],
            "decision_logs": public_decision_history[-250:],
            "benchmark_verdict": benchmarks.get("verdict", {}),
            "no_lookahead": (
                "daily features are sliced to date <= as_of; rolling training rows require "
                "label_end_date before the replay date"
            ),
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )
    write_json(DATA_DIR / "backtest_results.json", payload)
    write_json(DATA_DIR / "backtest_decision_logs.json", add_watermark({"logs": public_decision_history[-1000:]}, SYSTEMATIC_TEMPLATE_OUTPUT))
    return payload


def _public_decision_log(row: dict[str, Any]) -> dict[str, Any]:
    """Keep published replay logs readable and small enough for GitHub Pages."""
    def top_score(item: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "symbol",
            "asset_type",
            "final_score",
            "information_score",
            "leadership_score",
            "timing_score",
            "risk_penalty",
            "wait_flag",
        )
        return {key: item.get(key) for key in keys if key in item}

    def etf(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": item.get("symbol"),
            "score": item.get("score"),
            "category": item.get("category"),
            "sector": item.get("sector"),
            "theme": item.get("theme"),
            "reasons": (item.get("reasons") or [])[:3],
        }

    health = row.get("data_health") or {}
    data_health_summary = {
        "ok": health.get("ok"),
        "source": health.get("source"),
        "synthetic": health.get("synthetic", False),
        "fallback": health.get("fallback", False),
        "secondary_source_symbols": health.get("secondary_source_symbols", []),
        "unavailable_endpoint_count": len(
            [
                meta
                for meta in (health.get("endpoint_availability") or {}).values()
                if isinstance(meta, dict) and not meta.get("available", False)
            ]
        ),
    }

    agent = row.get("agent_led_decision") or {}
    agent_summary = {
        "watermark": agent.get("watermark"),
        "confidence": agent.get("confidence"),
        "risks": (agent.get("risks") or [])[:5],
        "allowed_for_execution": agent.get("allowed_for_execution", False),
    }
    systematic = row.get("systematic_decision") or {}
    systematic_summary = {
        "decision": systematic.get("decision") or row.get("execution_decision"),
        "reason": systematic.get("reason") or row.get("execution_reason"),
    }
    return {
        "date": row.get("date"),
        "market_regime": row.get("market_regime"),
        "risk_light": row.get("risk_light"),
        "data_health": data_health_summary,
        "universe_size": row.get("universe_size"),
        "candidate_score_summary": row.get("candidate_score_summary"),
        "current_allocation": row.get("current_allocation"),
        "target_allocation": row.get("target_allocation"),
        "selected_etfs": [etf(item) for item in row.get("selected_etfs", [])[:8]],
        "rejected_etfs": [etf(item) for item in row.get("rejected_etfs", [])[:20]],
        "top_stock_candidates": [top_score(item) for item in row.get("top_stock_candidates", [])[:12]],
        "systematic_decision": systematic_summary,
        "agent_led_decision": agent_summary,
        "execution_decision": row.get("execution_decision"),
        "execution_reason": row.get("execution_reason"),
        "orders": row.get("orders") or [],
        "portfolio_snapshot": {
            key: row.get("portfolio_snapshot", {}).get(key)
            for key in ("nav", "cash", "peak_nav", "relative_drawdown_pct", "last_rebalance_date")
        },
        "benchmark_snapshot": row.get("benchmark_snapshot"),
        "watermarks": row.get("watermarks", []),
    }


def _collect_training_rows(
    universe_payload: dict[str, Any],
    price_history: dict[str, pd.DataFrame],
    data_health: dict[str, Any],
    train_start: str,
    train_end: str,
    step_days: int,
) -> list[dict[str, Any]]:
    learning_rows: list[dict[str, Any]] = []
    dates = pd.bdate_range(train_start, train_end)
    dates = dates[:: max(1, step_days)]
    total_dates = len(dates)
    print(f"Training scan dates: {total_dates}", flush=True)
    for i, ts in enumerate(dates, start=1):
        as_of = ts.date().isoformat()
        latest_prices = _prices_as_of(price_history, as_of)
        if "SPY" not in latest_prices:
            continue
        feature_payload = compute_features(universe_payload, price_history, as_of, {})
        regime_payload = determine_regime(price_history, feature_payload, data_health, as_of)
        score_payload = score_candidates(feature_payload, regime_payload, as_of=as_of)
        learning_rows.extend(_learning_rows(score_payload, price_history, as_of))
        if i == 1 or i % 100 == 0 or i == total_dates:
            print(f"Training scan {i}/{total_dates}: {as_of}, rows={len(learning_rows)}", flush=True)
    return learning_rows


def _learn_rolling_weights(
    learning_rows: list[dict[str, Any]],
    as_of: str,
    earliest_train_start: str,
    rolling_years: int,
) -> dict[str, Any]:
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=1)
    window_start = max(pd.Timestamp(earliest_train_start), cutoff - pd.DateOffset(years=rolling_years))
    rows = [
        row
        for row in learning_rows
        if window_start <= pd.Timestamp(row["as_of"]) <= cutoff
        and pd.Timestamp(row.get("label_end_date", row["as_of"])) <= cutoff
    ]
    stock_rows = [row for row in rows if row["asset_type"] == "stock"]
    etf_rows = [row for row in rows if row["asset_type"] == "etf"]
    stock_learning = learn_weights(stock_rows, "stock", as_of=as_of)
    etf_learning = learn_weights(etf_rows, "etf", as_of=as_of)
    snapshot = {
        "date": as_of,
        "window": [window_start.date().isoformat(), cutoff.date().isoformat()],
        "usable_rows": len(rows),
        "stock_rows": len(stock_rows),
        "etf_rows": len(etf_rows),
        "stock_weights": stock_learning.get("weights"),
        "etf_weights": etf_learning.get("weights"),
        "watermark": "ML_ESTIMATED_OUTPUT",
    }
    return {"stock_learning": stock_learning, "etf_learning": etf_learning, "snapshot": snapshot}


def _universe_as_of(
    universe_payload: dict[str, Any],
    price_history: dict[str, pd.DataFrame],
    as_of: str,
    current_holdings: list[str] | None = None,
) -> dict[str, Any]:
    current_holdings = current_holdings or []
    always_include = {MANDATE.benchmark, MANDATE.secondary_growth_anchor, MANDATE.defensive_anchor, *current_holdings}
    candidates = []
    for row in universe_payload.get("candidates", []):
        symbol = row.get("symbol")
        if symbol in always_include or _has_history_as_of(price_history.get(symbol), as_of):
            candidates.append(dict(row))
    payload = dict(universe_payload)
    payload["as_of"] = as_of
    payload["candidates"] = candidates
    payload["replay_filter"] = {
        "source_pool_size": len(universe_payload.get("candidates", [])),
        "daily_size": len(candidates),
        "rule": "candidate must have price history available by replay date, except anchors/current holdings",
    }
    return payload


def _has_history_as_of(frame: pd.DataFrame | None, as_of: str, min_bars: int = 20) -> bool:
    if frame is None or frame.empty:
        return False
    idx = frame.index.searchsorted(pd.Timestamp(as_of), side="right")
    return idx >= min_bars


def _benchmark_snapshot(latest_prices: dict[str, float], benchmark_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "SPY": {"close": latest_prices.get("SPY")},
        "QQQ": {"close": latest_prices.get("QQQ")},
        "verdict": benchmark_payload.get("verdict", {}),
        "watermark": SYSTEMATIC_TEMPLATE_OUTPUT,
    }


def _should_call_ai_provider(
    as_of: str,
    index: int,
    total_dates: int,
    frequency: str,
    seen_weeks: set[tuple[int, int]],
    seen_months: set[tuple[int, int]],
) -> bool:
    if frequency == "daily":
        return True
    if frequency == "final":
        return index == total_dates
    if frequency == "monthly":
        ts = pd.Timestamp(as_of)
        key = (int(ts.year), int(ts.month))
        if key in seen_months:
            return False
        seen_months.add(key)
        return True
    if frequency == "weekly":
        iso = pd.Timestamp(as_of).isocalendar()
        key = (int(iso.year), int(iso.week))
        if key in seen_weeks:
            return False
        seen_weeks.add(key)
        return True
    return False


def _prices_as_of(price_history: dict[str, pd.DataFrame], as_of: str) -> dict[str, float]:
    prices = {}
    ts = pd.Timestamp(as_of)
    for symbol, frame in price_history.items():
        if frame is None or frame.empty:
            continue
        idx = frame.index.searchsorted(ts, side="right")
        if idx > 0:
            prices[symbol] = float(frame["close"].iloc[idx - 1])
    return prices


def _slice_history(price_history: dict[str, pd.DataFrame], start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return {
        symbol: frame.loc[(frame.index >= start) & (frame.index <= end)].copy()
        for symbol, frame in price_history.items()
        if frame is not None and not frame.empty
    }


def _equity_series(rows: list[dict[str, Any]]) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")["equity"].astype(float)


def _update_relative_state(portfolio: PaperPortfolio, price_history: dict[str, pd.DataFrame], as_of: str) -> None:
    spy = price_history.get("SPY")
    if spy is None:
        return
    sliced = spy.loc[spy.index <= pd.Timestamp(as_of)]
    if len(sliced) < 2:
        return
    daily_return = float(sliced["close"].iloc[-1] / sliced["close"].iloc[-2] - 1)
    portfolio.benchmark_equity *= 1 + daily_return
    relative = portfolio.nav() / MANDATE.starting_capital - portfolio.benchmark_equity / MANDATE.starting_capital
    portfolio.peak_relative_outperformance = max(portfolio.peak_relative_outperformance, relative)
    portfolio.relative_drawdown_pct = max(0.0, portfolio.peak_relative_outperformance - relative)


def _learning_rows(score_payload: dict[str, Any], price_history: dict[str, pd.DataFrame], as_of: str) -> list[dict[str, Any]]:
    out = []
    ts = pd.Timestamp(as_of)
    spy = price_history.get("SPY")
    if spy is None or spy.empty:
        return out
    spy_future = _forward_return(spy, ts, 20)
    if spy_future is None:
        return out
    for score in score_payload.get("scores", [])[:20]:
        frame = price_history.get(score["symbol"])
        future = _forward_return(frame, ts, 20)
        if future is None:
            continue
        out.append(
            {
                "as_of": as_of,
                "label_end_date": frame.index[frame.index.searchsorted(ts) + 20].date().isoformat(),
                "symbol": score["symbol"],
                "asset_type": "etf" if score.get("asset_type") == "etf" else "stock",
                "information": score.get("information_score", 0.0),
                "leadership": score.get("leadership_score", 0.0),
                "timing": score.get("timing_score", 0.0),
                "regime_fit": score.get("regime_fit_score", 0.0),
                "diversification": score.get("diversification_score", 0.0),
                "forward_20d_alpha_vs_spy": future - spy_future,
            }
        )
    return out


def _forward_return(frame: pd.DataFrame | None, ts: pd.Timestamp, days: int) -> float | None:
    if frame is None or frame.empty:
        return None
    idx = frame.index.searchsorted(ts)
    if idx >= len(frame) or idx + days >= len(frame):
        return None
    start = float(frame["close"].iloc[idx])
    end = float(frame["close"].iloc[idx + days])
    return end / start - 1 if start > 0 else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2009-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--train-start", default=None)
    parser.add_argument("--train-end", default="2020-12-31")
    parser.add_argument("--invest-start", default="2021-01-01")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--allow-synthetic-trading", action="store_true")
    parser.add_argument("--no-secondary-price-fallback", action="store_true")
    parser.add_argument("--rolling-train-years", type=int, default=12)
    parser.add_argument("--ai-memo-mode", choices=("off", "template", "deepseek"), default="template")
    parser.add_argument("--ai-memo-frequency", choices=("daily", "weekly", "monthly", "final"), default="weekly")
    parser.add_argument("--budget-preset", choices=tuple(BUDGET_PRESETS), default="default")
    parser.add_argument("--step-days", type=int, default=1)
    parser.add_argument("--train-step-days", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        train_start=args.train_start,
        train_end=args.train_end,
        invest_start=args.invest_start,
        max_symbols=args.max_symbols,
        allow_synthetic_trading=args.allow_synthetic_trading,
        use_secondary_price_fallback=not args.no_secondary_price_fallback,
        rolling_train_years=args.rolling_train_years,
        ai_memo_mode=args.ai_memo_mode,
        ai_memo_frequency=args.ai_memo_frequency,
        budget_preset=args.budget_preset,
        step_days=args.step_days,
        train_step_days=args.train_step_days,
    )
