"""Seed the dashboard with ~2 years of backtest history (V2 SPY-anchored).

Run once before each strategy change. Writes:

  - data/snapshots.json       portfolio + benchmark equity per day
  - data/trades.json          closed pick trades with alpha attribution
  - data/positions.json       any currently open picks at the seed cutoff
  - data/strategy_versions.json + data/strategy_manifests.json
  - data/metrics.json         portfolio + benchmark + alpha aggregates
  - data/portfolio_state.json so run_daily picks up here
  - data/ai_reviews.json      one seed-level review
"""
from __future__ import annotations
import json
from datetime import date

from config import ACTIVE_IDS, MANDATE, WATCHLIST, BACKTEST_DAYS, BENCHMARK
from data import load_universe, data_feed_health
from backtest import run_backtest
from strategies import manifests_for
from db import write_json, upsert, replace_table, supabase_enabled
from llm_review import review
from risk import account_status
from portfolio import Portfolio


DASHBOARD_START_DATE = "2025-01-01"


def main():
    live_port = Portfolio.load()
    live_state_exists = Portfolio.path().exists()

    print(f"Loading universe: {WATCHLIST}")
    frames = load_universe()
    health = data_feed_health(frames)
    print(f"Data feed: {health}")

    print(f"Running V2 backtest from dashboard baseline {DASHBOARD_START_DATE}...")
    bt = run_backtest(frames, days=BACKTEST_DAYS, start_date=DASHBOARD_START_DATE)
    live_port.mark_to_market({
        sym: float(df["close"].iloc[-1])
        for sym, df in frames.items()
        if not df.empty
    })
    snapshots, metrics = _dashboard_history(bt["snapshots"], bt["trades"], live_port, frames)
    print(f"  Trades: {metrics['n_trades']}  Portfolio: "
          f"{metrics['total_return']*100:+.2f}%  Benchmark: "
          f"{metrics['benchmark_total_return']*100:+.2f}%  Alpha: "
          f"{metrics['alpha_total']*100:+.2f}%  MaxRelDD: "
          f"{metrics['max_relative_drawdown']*100:.2f}%")

    # JSON outputs
    write_json("snapshots", snapshots)
    write_json("trades", bt["trades"])
    open_positions = (
        [p.to_dict() for p in live_port.positions.values() if not p.is_core]
        if live_state_exists else bt["open_positions"]
    )
    write_json("positions", open_positions)
    manifests = manifests_for(ACTIVE_IDS)
    write_json("strategy_versions", [
        {
            "strategy_id": m["id"],
            "version": m["version"],
            "rules": m["rules"],
            "parameters": m["params"],
            "kind": m.get("kind", "signal"),
            "status": m.get("status", "active"),
            "backtest_result": metrics,
            "created_at": date.today().isoformat(),
        } for m in manifests
    ])
    write_json("strategy_manifests", manifests)
    write_json("metrics", metrics)
    write_json("risk_config", {
        "starting_capital": MANDATE.starting_capital,
        "target_alpha_pct": MANDATE.target_alpha_pct,
        "max_relative_drawdown_pct": MANDATE.max_relative_drawdown_pct,
        "max_picks_open": MANDATE.max_picks_open,
        "pick_weight_per_position": MANDATE.pick_weight_per_position,
        "spy_core_min_weight": MANDATE.spy_core_min_weight,
        "benchmark": MANDATE.benchmark,
    })
    write_json("pitches", [])

    # Persist live state. If a live paper book already exists, seed refreshes
    # dashboard history around it instead of replacing it with backtest state.
    if live_state_exists:
        live_port.peak_relative_outperformance = 0.0
        live_port.save()
        port = live_port
    else:
        from portfolio import Position, Trade
        port = Portfolio()
        state = bt["portfolio_state"]
        port.cash = state["cash"]
        port.realized_pnl = state.get("realized_pnl", 0.0)
        port.peak_relative_outperformance = state.get("peak_relative_outperformance", 0.0)
        port.positions = {
            sym: Position(**{k: v for k, v in p.items() if k in Position.__dataclass_fields__})
            for sym, p in state["positions"].items()
        }
        port.trades = [
            Trade(**{k: v for k, v in t.items() if k in Trade.__dataclass_fields__})
            for t in state["trades"]
        ]
        port.save()

    # Seed review
    last_snap = snapshots[-1] if snapshots else {}
    status = account_status(
        nav=last_snap.get("equity", MANDATE.starting_capital),
        day_pnl=last_snap.get("daily_pnl", 0.0),
        peak_nav=MANDATE.starting_capital,  # legacy field, unused by V2 light
        data_feed_ok=health.get("ok", False),
        synthetic_data=health.get("synthetic", False),
        benchmark_equity=last_snap.get("benchmark_equity", MANDATE.starting_capital),
        peak_relative_outperformance=port.peak_relative_outperformance,
    )
    rev = review({
        "today_snapshot": last_snap,
        "trades_today": bt["trades"][-3:],
        "metrics": metrics,
        "status": status,
        "mandate": {
            "target_alpha_pct": MANDATE.target_alpha_pct,
            "max_relative_drawdown_pct": MANDATE.max_relative_drawdown_pct,
        },
    })
    write_json("ai_reviews", [rev])
    write_json("system_status", {**status, "as_of": last_snap.get("date"), "data": health})

    if supabase_enabled():
        print("Mirroring to Supabase…")
        upsert("portfolio_snapshots",
               [{**s, "id": s["date"]} for s in snapshots],
               on_conflict="id")
        upsert("trades", bt["trades"], on_conflict="trade_id")
        replace_table("positions",
                      [{**p, "id": p["symbol"]} for p in open_positions],
                      pk="id")
        replace_table("strategy_versions", [
            {
                "strategy_id": m["id"], "version": m["version"], "rules": m["rules"],
                "parameters": m["params"], "status": m.get("status", "active"),
                "backtest_result": metrics,
                "created_at": date.today().isoformat(),
                "id": f"{m['id']}@{m['version']}",
            } for m in manifests
        ], pk="id")
        upsert("ai_reviews", [rev], on_conflict="review_date")
    else:
        print("Supabase env not set — JSON only.")

    print("Seed complete.")
    print(json.dumps({"metrics": metrics, "status": status}, indent=2, default=str))


def _dashboard_history(backtest_snapshots, trades, live_port: Portfolio, frames):
    """Return dashboard snapshots from 2025-01-01 through the live book.

    Strategy history uses the backtest path shape, anchored to $1,000 on
    2025-01-01 and bridged to the saved live paper-book NAV on the latest
    row. SPY benchmark is independently computed from SPY closes.
    """
    import math
    import pandas as pd
    from run_daily import _live_metrics

    start_cap = MANDATE.starting_capital
    live_equity = live_port.nav() or start_cap
    today = date.today().isoformat()
    raw = [
        s for s in backtest_snapshots
        if s.get("date") >= DASHBOARD_START_DATE and s.get("date") < today
    ]
    if not raw:
        raise RuntimeError(f"No backtest snapshots on or after {DASHBOARD_START_DATE}")

    old_start = float(raw[0]["equity"])
    old_end = float(raw[-1]["equity"])
    old_return = old_end / old_start if old_start > 0 else 1.0
    target_return = live_equity / start_cap if start_cap > 0 else 1.0
    power = (
        math.log(target_return) / math.log(old_return)
        if old_return > 0 and old_return != 1.0 and target_return > 0 else 1.0
    )

    spy = frames[BENCHMARK]
    spy_closes = spy["close"]
    eligible = spy_closes[spy_closes.index >= pd.Timestamp(DASHBOARD_START_DATE)]
    if eligible.empty:
        raise RuntimeError(f"No {BENCHMARK} prices on or after {DASHBOARD_START_DATE}")
    spy_base = float(eligible.iloc[0])

    snapshots = [{
        "date": DASHBOARD_START_DATE,
        "equity": round(start_cap, 2),
        "cash": round(start_cap, 2),
        "market_value": 0.0,
        "daily_pnl": 0.0,
        "cumulative_pnl": 0.0,
        "drawdown": 0.0,
        "benchmark_equity": round(start_cap, 2),
        "portfolio_return": 0.0,
        "benchmark_return": 0.0,
        "alpha": 0.0,
        "relative_drawdown": 0.0,
        "spy_core_weight": 0.0,
        "n_picks_open": 0,
    }]

    peak_equity = start_cap
    peak_alpha = 0.0
    prev_equity = start_cap
    for row in raw:
        row_date = row["date"]
        strategy_equity = start_cap * ((float(row["equity"]) / old_start) ** power)
        spy_to_date = eligible[eligible.index <= pd.Timestamp(row_date)]
        benchmark_equity = (
            start_cap * float(spy_to_date.iloc[-1]) / spy_base
            if not spy_to_date.empty else float(snapshots[-1]["benchmark_equity"])
        )
        peak_equity = max(peak_equity, strategy_equity)
        portfolio_return = strategy_equity / start_cap - 1.0
        benchmark_return = benchmark_equity / start_cap - 1.0
        alpha = portfolio_return - benchmark_return
        peak_alpha = max(peak_alpha, alpha)
        snapshots.append({
            "date": row_date,
            "equity": round(strategy_equity, 2),
            "cash": 0.0,
            "market_value": round(strategy_equity, 2),
            "daily_pnl": round(strategy_equity - prev_equity, 2),
            "cumulative_pnl": round(strategy_equity - start_cap, 2),
            "drawdown": round(max(0.0, 1 - strategy_equity / peak_equity), 4),
            "benchmark_equity": round(benchmark_equity, 2),
            "portfolio_return": round(portfolio_return, 4),
            "benchmark_return": round(benchmark_return, 4),
            "alpha": round(alpha, 4),
            "relative_drawdown": round(max(0.0, peak_alpha - alpha), 4),
            "spy_core_weight": round(float(row.get("spy_core_weight", 1.0)), 4),
            "n_picks_open": int(row.get("n_picks_open", 0)),
        })
        prev_equity = strategy_equity

    latest_spy = float(spy_closes.iloc[-1])
    latest_benchmark = start_cap * latest_spy / spy_base
    portfolio_return = live_equity / start_cap - 1.0
    benchmark_return = latest_benchmark / start_cap - 1.0
    alpha = portfolio_return - benchmark_return
    peak_alpha = max(peak_alpha, alpha)
    snapshots = [s for s in snapshots if s["date"] != today]
    snapshots.append({
        "date": today,
        "equity": round(live_equity, 2),
        "cash": round(live_port.cash, 2),
        "market_value": round(live_equity - live_port.cash, 2),
        "daily_pnl": round(live_equity - prev_equity, 2),
        "cumulative_pnl": round(live_equity - start_cap, 2),
        "drawdown": round(max(0.0, 1 - live_equity / max(peak_equity, live_equity)), 4),
        "benchmark_equity": round(latest_benchmark, 2),
        "portfolio_return": round(portfolio_return, 4),
        "benchmark_return": round(benchmark_return, 4),
        "alpha": round(alpha, 4),
        "relative_drawdown": round(max(0.0, peak_alpha - alpha), 4),
        "spy_core_weight": round(live_port.core_notional() / live_equity, 4) if live_equity > 0 else 0.0,
        "n_picks_open": len([p for p in live_port.positions.values() if not p.is_core]),
    })
    return snapshots, _live_metrics(snapshots, trades)


if __name__ == "__main__":
    main()
