"""Daily orchestrator — V2 SPY-anchored.

Run by GitHub Actions after the US close, or locally via:

    python run_daily.py

Loads portfolio state, refreshes data, marks positions to market,
applies pick exits (stop / target / max-hold / signal decay /
relative-DD breach), opens new picks where conviction allows,
rebalances residual cash back into SPY, snapshots, and writes JSON.
"""
from __future__ import annotations
import json, math
from datetime import date
import importlib
import pandas as pd

from config import ACTIVE_IDS, MANDATE, WATCHLIST, BENCHMARK
from data import load_universe, data_feed_health
from signals import enrich, market_regime
from strategies import fire_all, manifests_for, REGISTRY
from risk import compute_relative_status, account_status
from portfolio import Portfolio
from news import sentiment_for_universe
from llm_review import review
from db import write_json, read_json, upsert, replace_table, supabase_enabled


def main():
    today = date.today().isoformat()
    snapshots_history = read_json("snapshots", default=[])
    if snapshots_history and not Portfolio.path().exists():
        raise RuntimeError(
            "Missing data/portfolio_state.json while snapshots already exist. "
            "Refusing to cold-start the paper book at $1,000; run seed mode or "
            "restore/commit the portfolio state file first."
        )
    continuity_snapshots = [
        s for s in snapshots_history if s.get("date") != today
    ]

    port = Portfolio.load()
    prev_equity = port.nav() or MANDATE.starting_capital
    history_compatible = _history_matches_live_book(continuity_snapshots, prev_equity)
    if not history_compatible:
        raise RuntimeError(
            "Persisted snapshot history is incompatible with data/portfolio_state.json. "
            "Refusing to reset or truncate dashboard history; run seed_history.py to rebuild it."
        )

    frames = load_universe()
    health = data_feed_health(frames)
    data_safe_for_trading = health.get("ok", False) and not health.get("synthetic", False)
    enriched = {sym: enrich(df) for sym, df in frames.items()}

    try:
        sent_pair = sentiment_for_universe(WATCHLIST)
        sent = sent_pair[0] if isinstance(sent_pair, tuple) else sent_pair
    except Exception:
        sent = {s: 0.0 for s in WATCHLIST}

    # Mark to market on latest close
    close_prices, bars = {}, {}
    for sym, df in frames.items():
        if df.empty: continue
        row = df.iloc[-1]
        close_prices[sym] = float(row["close"])
        bars[sym] = {"open": float(row["open"]), "high": float(row["high"]),
                     "low": float(row["low"]), "close": float(row["close"])}
    port.mark_to_market(close_prices)
    spy_close = close_prices.get(BENCHMARK, 0.0)
    regime = market_regime(frames[BENCHMARK])

    allocation_targets = {}
    allocation_strategy_id = None
    for sid in ACTIVE_IDS:
        entry = REGISTRY.get(sid, {})
        module_name = entry.get("module")
        if not module_name:
            continue
        try:
            mod = importlib.import_module(f"strategies.{module_name}")
            if hasattr(mod, "target_weights"):
                allocation_targets = mod.target_weights(enriched, entry.get("manifest", {}).get("params", {}))
                allocation_strategy_id = sid
                break
        except Exception as e:
            print(f"target allocation failed: {e}")

    if allocation_targets and data_safe_for_trading:
        port.rebalance_to_targets(
            allocation_targets, close_prices,
            strategy_id=allocation_strategy_id or "allocation",
            thesis=f"Target allocation for {regime}: {allocation_targets}",
        )
    elif data_safe_for_trading and BENCHMARK not in port.positions and spy_close > 0:
        port.rebalance_to_core(spy_close)

    # Compute current strategy ranks for exit-decay + new entries.
    rank_lookup = {}
    decay_z = 0.5
    if not allocation_targets:
        for sid in ACTIVE_IDS:
            entry = REGISTRY.get(sid, {})
            m = entry.get("manifest", {})
            decay_z = m.get("params", {}).get("decay_zscore_exit", decay_z)
            module_name = entry.get("module")
            if module_name:
                try:
                    mod = importlib.import_module(f"strategies.{module_name}")
                    if hasattr(mod, "compute_ranks"):
                        rank_lookup.update(mod.compute_ranks(enriched, m["params"]))
                except Exception as e:
                    print(f"rank computation failed: {e}")

    # Apply exits
    closed_today = []
    if data_safe_for_trading and not allocation_targets:
        closed_today = port.apply_exits(bars, rank_lookup=rank_lookup,
                                        decay_z=decay_z, spy_price=spy_close)

    # Regime + signals
    signals = [] if allocation_targets else fire_all(
        enriched, regime=regime, sentiment=sent,
        active_ids=ACTIVE_IDS, universe=enriched,
    )

    # Pitches output (for the dashboard's "Pitches for tomorrow")
    pitches = []
    for sig in signals:
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
    if allocation_targets:
        for sym, weight in allocation_targets.items():
            pitches.append({
                "symbol": sym,
                "strategy_id": allocation_strategy_id,
                "rationale": f"Target allocation weight {weight*100:.1f}% in {regime}.",
                "stop_distance": 0,
                "target_distance": 0,
                "max_hold_days": 0,
                "score": round(weight, 3),
                "target_weight": weight,
            })

    # Pre-check relative status BEFORE adding new picks
    nav_now = port.nav()
    bench_eq_now = nav_now  # gets filled below from compatible snapshots history if available
    if continuity_snapshots:
        last = continuity_snapshots[-1]
        if last.get("benchmark_equity"):
            # Re-derive today's benchmark equity by scaling yesterday's by SPY's daily ret
            try:
                spy_df = frames[BENCHMARK]
                latest_data_date = spy_df.index[-1].date().isoformat()
                if last.get("date") == latest_data_date:
                    bench_eq_now = float(last["benchmark_equity"])
                else:
                    spy_yesterday = float(spy_df["close"].iloc[-2])
                    bench_eq_now = float(last["benchmark_equity"]) * (spy_close / spy_yesterday)
            except Exception:
                bench_eq_now = last["benchmark_equity"]
    status_pre = compute_relative_status(
        equity=nav_now, benchmark_equity=bench_eq_now,
        starting_capital=MANDATE.starting_capital,
        peak_relative_outperformance=port.peak_relative_outperformance,
        data_feed_ok=health.get("ok", False),
        synthetic_data=health.get("synthetic", False),
    )

    # Open new picks unless red / black
    rejections = []
    max_picks = MANDATE.max_picks_open
    if status_pre.light == "yellow":
        max_picks = min(max_picks, 1)
    if status_pre.light in ("red", "black") or not data_safe_for_trading or allocation_targets:
        max_picks = 0
    if status_pre.light == "red" and not allocation_targets:
        # Force close any remaining picks
        for sym in list(port.positions.keys()):
            pos = port.positions[sym]
            if pos.is_core or sym == BENCHMARK: continue
            price = close_prices.get(sym)
            if price:
                t = port.close_pick(sym, price, "relative_dd_breach", spy_close)
                if t: closed_today.append(t)

    open_picks_count = len([p for p in port.positions.values() if not p.is_core])
    for sig in signals:
        if sig.symbol == BENCHMARK or sig.symbol in port.positions:
            continue
        if open_picks_count >= max_picks:
            rejections.append({"signal": sig.to_dict(), "reason": "max_picks"})
            break
        entry_price = close_prices.get(sig.symbol)
        if entry_price is None or math.isnan(entry_price):
            continue
        opened = port.open_pick(
            symbol=sig.symbol, entry_price=entry_price,
            stop_distance=sig.stop_distance, target_distance=sig.target_distance,
            max_hold_days=sig.max_hold_days, strategy_id=sig.strategy_id,
            thesis=sig.rationale, spy_price_at_entry=spy_close,
            target_weight=sig.extras.get("target_weight"),
        )
        if opened:
            open_picks_count += 1
        else:
            rejections.append({"signal": sig.to_dict(), "reason": "open_pick refused"})

    # Top up SPY core with any residual cash
    if data_safe_for_trading and spy_close > 0 and not allocation_targets:
        port.rebalance_to_core(spy_close)

    port.age_positions()
    equity = port.nav()

    # Final relative status now that today's PnL is settled
    status = compute_relative_status(
        equity=equity, benchmark_equity=bench_eq_now,
        starting_capital=MANDATE.starting_capital,
        peak_relative_outperformance=port.peak_relative_outperformance,
        data_feed_ok=health.get("ok", False),
        synthetic_data=health.get("synthetic", False),
    )
    port.peak_relative_outperformance = status.peak_relative_pnl_pct

    # Snapshot
    snap = {
        "date": today,
        "equity": round(equity, 2),
        "cash": round(port.cash, 2),
        "market_value": round(equity - port.cash, 2),
        "daily_pnl": round(equity - prev_equity, 2),
        "cumulative_pnl": round(equity - MANDATE.starting_capital, 2),
        "drawdown": round(max(0.0, 1 - equity / MANDATE.starting_capital), 4),
        "benchmark_equity": round(bench_eq_now, 2),
        "portfolio_return": round(status.portfolio_return, 4),
        "benchmark_return": round(status.benchmark_return, 4),
        "alpha": round(status.relative_pnl_pct, 4),
        "relative_drawdown": round(status.relative_drawdown_pct, 4),
        "spy_core_weight": round(port.core_notional() / equity, 4) if equity > 0 else 0.0,
        "n_picks_open": len([p for s, p in port.positions.items() if s != BENCHMARK]),
    }
    snapshots = [s for s in snapshots_history if s.get("date") != today] + [snap]
    write_json("snapshots", snapshots)

    all_trades = read_json("trades", default=[])
    all_trades.extend([t.to_dict() for t in closed_today])
    write_json("trades", all_trades)
    write_json("positions", [p.to_dict() for s, p in port.positions.items() if s != BENCHMARK])

    metrics = _live_metrics(snapshots, all_trades)
    write_json("metrics", metrics)
    write_json("pitches", pitches)
    write_json("strategy_manifests", manifests_for(ACTIVE_IDS))

    rev = review({
        "today_snapshot": snap,
        "trades_today": [t.to_dict() for t in closed_today],
        "metrics": metrics,
        "status": {
            "light": status.light, "reason": status.reason,
            "relative_pnl_pct": status.relative_pnl_pct,
            "relative_drawdown_pct": status.relative_drawdown_pct,
        },
        "regime": regime,
        "rejected_signals": rejections,
        "mandate": {
            "target_alpha_pct": MANDATE.target_alpha_pct,
            "max_relative_drawdown_pct": MANDATE.max_relative_drawdown_pct,
        },
    })
    reviews = read_json("ai_reviews", default=[])
    reviews = [r for r in reviews if r.get("review_date") != today] + [rev]
    write_json("ai_reviews", reviews)

    write_json("system_status", {
        "light": status.light, "reason": status.reason,
        "portfolio_return": status.portfolio_return,
        "benchmark_return": status.benchmark_return,
        "relative_pnl_pct": status.relative_pnl_pct,
        "relative_drawdown_pct": status.relative_drawdown_pct,
        "peak_relative_pnl_pct": status.peak_relative_pnl_pct,
        "as_of": today, "data": health, "regime": regime,
    })

    port.save()

    if supabase_enabled():
        upsert("portfolio_snapshots",
               [{**s, "id": s["date"]} for s in snapshots[-30:]],
               on_conflict="id")
        upsert("trades", [t.to_dict() for t in closed_today], on_conflict="trade_id")
        replace_table("positions",
                      [{**p.to_dict(), "id": p.symbol} for s, p in port.positions.items() if s != BENCHMARK],
                      pk="id")
        upsert("ai_reviews", [rev], on_conflict="review_date")

    print(json.dumps({
        "date": today, "equity": equity,
        "benchmark_equity": bench_eq_now,
        "alpha_pct": round(status.relative_pnl_pct * 100, 3),
        "light": status.light, "signals": len(signals),
        "closed_today": len(closed_today),
        "open_picks": [p.symbol for s, p in port.positions.items() if s != BENCHMARK],
    }, indent=2, default=str))


def _live_metrics(snapshots, trades):
    import numpy as np
    if not snapshots: return {}
    eq = pd.Series([s["equity"] for s in snapshots])
    bench = pd.Series([s.get("benchmark_equity", s["equity"]) for s in snapshots])
    rets = eq.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    ann = 252
    sharpe = float(rets.mean() / rets.std() * np.sqrt(ann)) if rets.std() > 0 else 0.0
    bench_sharpe = float(bench_rets.mean() / bench_rets.std() * np.sqrt(ann)) if bench_rets.std() > 0 else 0.0
    excess = rets - bench_rets
    info_ratio = float(excess.mean() / excess.std() * np.sqrt(ann)) if excess.std() > 0 else 0.0
    max_rel_dd = max((s.get("relative_drawdown", 0) for s in snapshots), default=0.0)
    pnls = [t["pnl"] for t in trades if t.get("exit_price") is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = (len(wins) / len(pnls)) if pnls else 0.0
    pf = (sum(wins) / abs(sum(losses))) if losses else (None if not wins else None)
    alphas = [t.get("alpha_vs_spy") for t in trades if t.get("alpha_vs_spy") is not None]
    avg_pick_alpha = float(np.mean(alphas)) if alphas else 0.0
    total_return = float(eq.iloc[-1] / MANDATE.starting_capital - 1.0)
    bench_total = float(bench.iloc[-1] / MANDATE.starting_capital - 1.0)
    n_years = len(snapshots) / 252
    cagr = (
        float((eq.iloc[-1] / MANDATE.starting_capital) ** (1 / n_years) - 1.0)
        if n_years >= 0.25 else 0.0
    )
    return {
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "benchmark_total_return": round(bench_total, 4),
        "alpha_total": round(total_return - bench_total, 4),
        "sharpe": round(sharpe, 3),
        "benchmark_sharpe": round(bench_sharpe, 3),
        "info_ratio": round(info_ratio, 3),
        "max_relative_drawdown": round(float(max_rel_dd), 4),
        "win_rate": round(win_rate, 3),
        "profit_factor": round(pf, 3) if pf else None,
        "n_trades": len(pnls),
        "avg_win": round(float(np.mean(wins)), 2) if wins else 0.0,
        "avg_loss": round(float(np.mean(losses)), 2) if losses else 0.0,
        "largest_loss": round(float(min(pnls)), 2) if pnls else 0.0,
        "avg_pick_alpha": round(avg_pick_alpha, 4),
        "target_alpha_pct": MANDATE.target_alpha_pct,
        "max_relative_drawdown_pct": MANDATE.max_relative_drawdown_pct,
    }


def _history_matches_live_book(snapshots, live_equity: float) -> bool:
    """Return False when backtest/reset history is on another baseline.

    GitHub Actions can only continue the live paper book safely when the
    latest persisted snapshot and benchmark series are compatible with
    ``portfolio_state.json``. If a prior bad run cold-started at $1,000, or
    if a backtest history is mixed with a restored live book, the dashboard
    should restart its live series from the actual portfolio state instead
    of showing a bogus relative drawdown.
    """
    if not snapshots or live_equity <= 0:
        return True
    last = snapshots[-1]
    try:
        equity = float(last.get("equity", 0.0))
        benchmark = float(last.get("benchmark_equity", equity))
    except (TypeError, ValueError):
        return False
    if equity <= 0 or benchmark <= 0:
        return False

    equity_gap = abs(equity - live_equity) / live_equity
    # The benchmark is allowed to diverge from strategy equity; that is the
    # point of plotting SPY independently. Compatibility only checks that the
    # persisted strategy equity lines up with the saved live paper book.
    return equity_gap <= 0.10


if __name__ == "__main__":
    main()
