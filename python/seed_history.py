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

from config import ACTIVE_IDS, MANDATE, WATCHLIST, BACKTEST_DAYS
from data import load_universe, data_feed_health
from backtest import run_backtest
from strategies import manifests_for
from db import write_json, upsert, replace_table, supabase_enabled
from llm_review import review
from risk import account_status


def main():
    print(f"Loading universe: {WATCHLIST}")
    frames = load_universe()
    health = data_feed_health(frames)
    print(f"Data feed: {health}")

    print(f"Running V2 backtest over last {BACKTEST_DAYS} trading days...")
    bt = run_backtest(frames, days=BACKTEST_DAYS)
    metrics = bt["metrics"]
    print(f"  Trades: {metrics['n_trades']}  Portfolio: "
          f"{metrics['total_return']*100:+.2f}%  Benchmark: "
          f"{metrics['benchmark_total_return']*100:+.2f}%  Alpha: "
          f"{metrics['alpha_total']*100:+.2f}%  MaxRelDD: "
          f"{metrics['max_relative_drawdown']*100:.2f}%")

    # JSON outputs
    write_json("snapshots", bt["snapshots"])
    write_json("trades", bt["trades"])
    write_json("positions", bt["open_positions"])
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

    # Persist live state
    from portfolio import Portfolio, Position, Trade
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
    last_snap = bt["snapshots"][-1] if bt["snapshots"] else {}
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
               [{**s, "id": s["date"]} for s in bt["snapshots"]],
               on_conflict="id")
        upsert("trades", bt["trades"], on_conflict="trade_id")
        replace_table("positions",
                      [{**p, "id": p["symbol"]} for p in bt["open_positions"]],
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


if __name__ == "__main__":
    main()
