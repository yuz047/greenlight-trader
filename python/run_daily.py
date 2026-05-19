"""Daily orchestrator.

Run by GitHub Actions after 8pm ET on weekdays, or locally via:

    python run_daily.py

Loads portfolio state, refreshes data, applies stops/targets, opens new
trades that survive the risk caps, appends today's snapshot, generates
an EOD review, and mirrors everything to Supabase (or JSON if Supabase
env is not set).
"""
from __future__ import annotations
import json
from datetime import date
import math
import pandas as pd

from config import ACTIVE_IDS, RISK, WATCHLIST, BENCHMARK
from data import load_universe, data_feed_health
from signals import enrich, market_regime
from strategies import fire_all, manifests_for
from risk import size_position, account_status
from portfolio import Portfolio
from news import sentiment_for_universe
from llm_review import review
from db import write_json, read_json, upsert, replace_table, supabase_enabled


def main():
    port = Portfolio.load()
    prev_equity = port.nav() or RISK.starting_capital

    frames = load_universe()
    health = data_feed_health(frames)
    enriched = {sym: enrich(df) for sym, df in frames.items()}

    # --- news/sentiment (graceful failure) -----------------------------
    try:
        sent, headlines = sentiment_for_universe(WATCHLIST)
    except Exception:
        sent, headlines = ({s: 0.0 for s in WATCHLIST}, {s: [] for s in WATCHLIST})

    # --- mark to market on latest close -------------------------------
    close_prices, bars = {}, {}
    for sym, df in frames.items():
        if df.empty:
            continue
        row = df.iloc[-1]
        close_prices[sym] = float(row["close"])
        bars[sym] = {"open": float(row["open"]), "high": float(row["high"]),
                     "low": float(row["low"]), "close": float(row["close"])}
    port.mark_to_market(close_prices)

    # --- apply stops, targets, max-hold on today's bar -----------------
    closed_today = port.apply_stops_and_targets(bars)

    # --- regime + signals --------------------------------------------
    regime = market_regime(frames[BENCHMARK])
    signals = fire_all(enriched, regime=regime, sentiment=sent,
                       active_ids=ACTIVE_IDS, universe=enriched)

    # Persist tomorrow's candidate pitches for the dashboard's
    # "Pitches for tomorrow" panel.
    pitches = []
    for sig in signals:
        if sig.strategy_id == "stock_pitcher_v1":
            pitches.append({
                "symbol": sig.symbol,
                "strategy_id": sig.strategy_id,
                "rationale": sig.rationale,
                "stop_distance": round(sig.stop_distance, 2),
                "target_distance": round(sig.target_distance, 2),
                "max_hold_days": sig.max_hold_days,
                "score": round(sig.score, 3),
                **sig.extras,
            })

    # --- entry decisions (only if data feed is healthy & light != red/black)
    status_pre = account_status(
        nav=port.nav(), day_pnl=port.nav() - prev_equity,
        peak_nav=port.peak_nav,
        data_feed_ok=health.get("ok", False),
        synthetic_data=health.get("synthetic", False),
    )

    rejections = []
    if status_pre["light"] in ("green", "yellow"):
        for sig in signals:
            if sig.symbol in port.positions:
                continue
            if len(port.positions) >= RISK.max_open_positions:
                rejections.append({"signal": sig.to_dict(), "reason": "max_open_positions"})
                break
            entry_price = close_prices.get(sig.symbol)
            if entry_price is None or math.isnan(entry_price):
                continue
            nav = port.nav()
            sz = size_position(
                entry_price=entry_price, stop_distance=sig.stop_distance,
                nav=nav, cash=port.cash,
                open_positions=len(port.positions),
                existing_symbol_exposure=port.open_position_exposure(sig.symbol),
            )
            if not sz.took:
                rejections.append({"signal": sig.to_dict(), "reason": sz.reason})
                continue
            port.open_trade(
                symbol=sig.symbol, quantity=sz.shares, entry_price=entry_price,
                stop_distance=sig.stop_distance, target_distance=sig.target_distance,
                max_hold_days=sig.max_hold_days, strategy_id=sig.strategy_id,
                thesis=sig.rationale,
            )
    else:
        # Trading paused — record why
        for sig in signals:
            rejections.append({"signal": sig.to_dict(),
                               "reason": f"system light={status_pre['light']}"})

    port.age_positions()
    port.update_peak()
    equity = port.nav()

    # --- snapshot ------------------------------------------------------
    today = date.today().isoformat()
    snap = {
        "date": today,
        "equity": round(equity, 2),
        "cash": round(port.cash, 2),
        "market_value": round(equity - port.cash, 2),
        "daily_pnl": round(equity - prev_equity, 2),
        "cumulative_pnl": round(equity - RISK.starting_capital, 2),
        "drawdown": round(max(0.0, 1 - equity / port.peak_nav), 4),
    }
    snapshots = read_json("snapshots", default=[])
    # If today already present (re-run), replace it
    snapshots = [s for s in snapshots if s.get("date") != today] + [snap]
    write_json("snapshots", snapshots)

    # --- trades & positions -------------------------------------------
    all_trades = read_json("trades", default=[])
    all_trades.extend([t.to_dict() for t in closed_today])
    write_json("trades", all_trades)
    write_json("positions", [p.to_dict() for p in port.positions.values()])

    # --- final status, includes today's pnl ---------------------------
    status = account_status(
        nav=equity, day_pnl=snap["daily_pnl"], peak_nav=port.peak_nav,
        data_feed_ok=health.get("ok", False),
        synthetic_data=health.get("synthetic", False),
    )

    # --- recompute metrics over the live history ----------------------
    metrics = _live_metrics(snapshots, all_trades)
    write_json("metrics", metrics)

    # --- AI review ----------------------------------------------------
    rev = review({
        "today_snapshot": snap,
        "trades_today": [t.to_dict() for t in closed_today],
        "metrics": metrics,
        "status": status,
        "regime": regime,
        "sentiment": sent,
        "rejected_signals": rejections,
    })
    reviews = read_json("ai_reviews", default=[])
    reviews = [r for r in reviews if r.get("review_date") != today] + [rev]
    write_json("ai_reviews", reviews)

    write_json("system_status", {
        **status, "as_of": today, "data": health,
        "regime": regime,
    })

    # Pitches + active strategy manifests for the dashboard
    write_json("pitches", pitches)
    write_json("strategy_manifests", manifests_for(ACTIVE_IDS))

    # --- decision log entry (for the AI Decision Log panel) -----------
    log = read_json("decision_log", default=[])
    log.append({
        "ts": today,
        "regime": regime,
        "signals_fired": len(signals),
        "trades_opened": [s for s in close_prices if s in port.positions and port.positions[s].age_days == 0],
        "trades_closed_today": [t.to_dict() for t in closed_today],
        "rejected_signals": rejections[:10],
        "light": status["light"],
        "light_reason": status["reason"],
    })
    # Trim to last 60 days
    write_json("decision_log", log[-60:])

    # --- persist portfolio state for next run ------------------------
    port.save()

    # --- mirror to Supabase ------------------------------------------
    if supabase_enabled():
        upsert("portfolio_snapshots",
               [{**s, "id": s["date"]} for s in snapshots[-30:]],
               on_conflict="id")
        upsert("trades", [t.to_dict() for t in closed_today], on_conflict="trade_id")
        replace_table("positions",
                      [{**p.to_dict(), "id": p.symbol} for p in port.positions.values()],
                      pk="id")
        upsert("ai_reviews", [rev], on_conflict="review_date")

    print(json.dumps({
        "date": today, "equity": equity, "light": status["light"],
        "signals": len(signals), "closed_today": len(closed_today),
        "open_positions": list(port.positions.keys()),
    }, indent=2, default=str))


def _live_metrics(snapshots, trades):
    """Same shape as backtest metrics; computed from live snapshots."""
    import numpy as np
    if not snapshots:
        return {}
    eq = pd.Series([s["equity"] for s in snapshots])
    rets = eq.pct_change().dropna()
    ann = 252
    sharpe = float(rets.mean() / rets.std() * np.sqrt(ann)) if rets.std() > 0 else 0.0
    downside = rets[rets < 0]
    sortino = float(rets.mean() / downside.std() * np.sqrt(ann)) if len(downside) > 1 and downside.std() > 0 else 0.0
    max_dd = max((s.get("drawdown", 0) for s in snapshots), default=0.0)
    pnls = [t["pnl"] for t in trades if t.get("exit_price") is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = (len(wins) / len(pnls)) if pnls else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (None if not wins else None)
    n_years = max(len(snapshots) / 252, 1e-6)
    total_return = float(eq.iloc[-1] / RISK.starting_capital - 1.0)
    cagr = float((eq.iloc[-1] / RISK.starting_capital) ** (1 / n_years) - 1.0)
    return {
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(float(max_dd), 4),
        "win_rate": round(win_rate, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor else None,
        "n_trades": len(pnls),
        "avg_win": round(float(np.mean(wins)), 2) if wins else 0.0,
        "avg_loss": round(float(np.mean(losses)), 2) if losses else 0.0,
        "largest_loss": round(float(min(pnls)), 2) if pnls else 0.0,
        "vol_annualized": round(float(rets.std() * np.sqrt(ann)), 4) if len(rets) else 0.0,
    }


if __name__ == "__main__":
    main()
