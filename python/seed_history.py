"""Seed the dashboard with ~2 years of backtest history.

Run once before the first deploy. Writes:
- data/snapshots.json
- data/trades.json
- data/positions.json
- data/strategy_versions.json
- data/portfolio_state.json (so run_daily.py picks up where this leaves off)
"""
from __future__ import annotations
import json
from datetime import date

from config import ACTIVE_IDS, RISK, WATCHLIST, BACKTEST_DAYS
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

    print(f"Running backtest over last {BACKTEST_DAYS} trading days...")
    bt = run_backtest(frames, days=BACKTEST_DAYS)
    metrics = bt["metrics"]
    print(f"  Trades: {metrics['n_trades']}  Sharpe: {metrics['sharpe']}  "
          f"WinRate: {metrics['win_rate']}  MaxDD: {metrics['max_drawdown']}")

    # --- write JSON ----------------------------------------------------
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
    write_json("pitches", [])  # populated by run_daily on each run
    write_json("metrics", metrics)
    write_json("risk_config", {
        "starting_capital": RISK.starting_capital,
        "max_risk_per_trade_pct": RISK.max_risk_per_trade_pct,
        "max_daily_loss_pct": RISK.max_daily_loss_pct,
        "max_drawdown_pct": RISK.max_drawdown_pct,
        "max_open_positions": RISK.max_open_positions,
        "max_single_position_pct": RISK.max_single_position_pct,
    })

    # Persist the live state so run_daily continues from here
    from portfolio import Portfolio, Position, Trade
    port = Portfolio()
    state = bt["portfolio_state"]
    port.cash = state["cash"]
    port.realized_pnl = state["realized_pnl"]
    port.peak_nav = state["peak_nav"]
    port.positions = {sym: Position(**{k: v for k, v in p.items()
                                       if k in Position.__dataclass_fields__})
                      for sym, p in state["positions"].items()}
    port.trades = [Trade(**{k: v for k, v in t.items()
                            if k in Trade.__dataclass_fields__})
                   for t in state["trades"]]
    port.save()

    # --- seed an initial AI review row ---------------------------------
    last_snap = bt["snapshots"][-1] if bt["snapshots"] else {}
    status = account_status(
        nav=last_snap.get("equity", RISK.starting_capital),
        day_pnl=last_snap.get("daily_pnl", 0.0),
        peak_nav=port.peak_nav,
        data_feed_ok=health.get("ok", False),
        synthetic_data=health.get("synthetic", False),
    )
    rev = review({
        "today_snapshot": last_snap,
        "trades_today": bt["trades"][-3:],
        "metrics": metrics,
        "status": status,
    })
    write_json("ai_reviews", [rev])
    write_json("system_status", {
        **status,
        "as_of": last_snap.get("date"),
        "data": health,
    })

    # --- mirror to Supabase if configured ------------------------------
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
