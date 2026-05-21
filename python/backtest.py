"""Walk-forward backtest — V2 SPY-anchored.

Simulates the daily engine over the last ~2 trading years. On every day:

  1. Mark all positions (SPY core + any picks) to today's close.
  2. Apply exits: stop / target / max-hold / signal-decay.
  3. Run the strategy registry to get tomorrow's pick candidates.
  4. If the relative-DD gate is in 'red', skip new entries (hold 100% SPY).
  5. Open up to ``MANDATE.max_picks_open`` picks, each sized to
     ``pick_weight_per_position`` of NAV by selling SPY.
  6. Rebalance any residual cash back into the SPY core.
  7. Append a snapshot containing both portfolio equity and a pure-SPY
     benchmark equity, plus the live relative-DD/alpha numbers.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List
import math
import pandas as pd
import numpy as np

from config import MANDATE, ACTIVE_IDS, WATCHLIST, BENCHMARK, BACKTEST_DAYS
from signals import enrich, market_regime
from strategies import fire_all, REGISTRY
from risk import compute_relative_status
from portfolio import Portfolio


@dataclass
class Snapshot:
    date: str
    equity: float
    cash: float
    market_value: float
    daily_pnl: float
    cumulative_pnl: float
    drawdown: float
    # benchmark + relative
    benchmark_equity: float
    portfolio_return: float
    benchmark_return: float
    alpha: float                # portfolio - benchmark, in % of starting cap
    relative_drawdown: float
    spy_core_weight: float
    n_picks_open: int

    def to_dict(self) -> dict: return asdict(self)


def _bar(df: pd.DataFrame, dt) -> dict | None:
    if dt not in df.index: return None
    row = df.loc[dt]
    return {"open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"])}


def run_backtest(
    frames: Dict[str, pd.DataFrame],
    days: int = BACKTEST_DAYS,
    start_date: str | None = None,
    sentiment_provider=None,
) -> dict:
    enriched = {sym: enrich(df) for sym, df in frames.items()}
    spy = frames[BENCHMARK]
    timeline = spy.index[-days:]
    if start_date is not None:
        timeline = timeline[timeline >= pd.Timestamp(start_date)]
    if len(timeline) == 0:
        raise RuntimeError(f"No benchmark bars available for backtest start_date={start_date!r}")

    port = Portfolio()
    snapshots: List[Snapshot] = []
    prev_equity = port.nav()

    # Establish the SPY baseline on day one.
    first_dt = timeline[0]
    spy_open0 = float(spy.loc[first_dt, "open"])
    # Buy SPY with all starting cash at the first open
    initial_shares = port.cash / spy_open0
    from portfolio import Position
    from datetime import datetime
    port.positions[BENCHMARK] = Position(
        symbol=BENCHMARK, side="long", quantity=initial_shares,
        entry_price=spy_open0, entry_time=datetime.utcnow().isoformat() + "Z",
        stop_price=0.0, target_price=0.0, max_hold_days=10_000,
        strategy_id="spy_core_baseline",
        thesis="SPY baseline.",
        last_price=spy_open0, age_days=0, is_core=True,
    )
    port.cash -= initial_shares * spy_open0
    benchmark_shares = initial_shares  # parallel pure-SPY benchmark
    starting_cap = MANDATE.starting_capital

    # State for relative-DD gate
    peak_rel = 0.0
    red_cooldown_until_idx = -1   # while i < this, no new picks

    for i, dt in enumerate(timeline):
        # 1. Mark to market
        close_prices = {}
        bars = {}
        for sym, df in frames.items():
            if dt in df.index:
                row = df.loc[dt]
                close_prices[sym] = float(row["close"])
                bars[sym] = {"open": float(row["open"]), "high": float(row["high"]),
                             "low": float(row["low"]), "close": float(row["close"])}
        port.mark_to_market(close_prices)
        spy_close = close_prices.get(BENCHMARK, 0.0)

        # 2. Recompute ranks once per day for exit / entry decisions
        regime = market_regime(spy.loc[:dt])
        sym_enriched_to_date = {s: e.loc[:dt] for s, e in enriched.items()}
        # Pull the pitcher v2 manifest's exit-z threshold
        decay_z = 0.5
        for sid in ACTIVE_IDS:
            m = REGISTRY.get(sid, {}).get("manifest", {})
            if "decay_zscore_exit" in m.get("params", {}):
                decay_z = m["params"]["decay_zscore_exit"]
                break
        # Compute current pitcher ranks for exit-decay decisions
        rank_lookup = {}
        try:
            from strategies.stock_pitcher_v2 import compute_ranks
            for sid in ACTIVE_IDS:
                m = REGISTRY.get(sid, {}).get("manifest", {})
                if m.get("id") == "stock_pitcher_v2":
                    rank_lookup = compute_ranks(sym_enriched_to_date, m["params"])
                    break
        except Exception:
            pass

        # 3. Exits
        port.apply_exits(bars, rank_lookup=rank_lookup,
                         decay_z=decay_z, spy_price=spy_close)

        # 4. Generate signals
        sent = sentiment_provider(dt) if sentiment_provider else {}
        signals = fire_all(sym_enriched_to_date, regime=regime,
                           sentiment=sent, active_ids=ACTIVE_IDS,
                           universe=sym_enriched_to_date)

        # 5. Relative-DD gate
        nav_now = port.nav()
        bench_eq = benchmark_shares * spy_close if spy_close > 0 else starting_cap
        rs = compute_relative_status(
            equity=nav_now, benchmark_equity=bench_eq,
            starting_capital=starting_cap,
            peak_relative_outperformance=peak_rel,
            data_feed_ok=True, synthetic_data=False,
        )
        peak_rel = rs.peak_relative_pnl_pct
        if rs.light == "red":
            # Force close all picks today; cool down for 20 trading days.
            for sym in list(port.positions.keys()):
                pos = port.positions[sym]
                if pos.is_core or sym == BENCHMARK: continue
                price = close_prices.get(sym)
                if price:
                    port.close_pick(sym, price, "relative_dd_breach", spy_close)
            red_cooldown_until_idx = i + 20

        max_picks_today = (
            0 if i < red_cooldown_until_idx else MANDATE.max_picks_open
        )
        if rs.light == "yellow":
            max_picks_today = min(max_picks_today, 1)

        # 6. Open new picks at TOMORROW's open
        next_dt = timeline[i + 1] if i + 1 < len(timeline) else None
        for sig in signals:
            if sig.symbol == BENCHMARK or sig.symbol in port.positions:
                continue
            if len([p for p in port.positions.values() if not p.is_core]) >= max_picks_today:
                break
            entry_price = None
            if next_dt is not None and next_dt in frames[sig.symbol].index:
                entry_price = float(frames[sig.symbol].loc[next_dt, "open"])
            else:
                entry_price = close_prices.get(sig.symbol)
            if entry_price is None or math.isnan(entry_price):
                continue
            spy_for_swap = (float(frames[BENCHMARK].loc[next_dt, "open"])
                            if next_dt is not None and next_dt in frames[BENCHMARK].index
                            else spy_close)
            port.open_pick(
                symbol=sig.symbol, entry_price=entry_price,
                stop_distance=sig.stop_distance, target_distance=sig.target_distance,
                max_hold_days=sig.max_hold_days, strategy_id=sig.strategy_id,
                thesis=sig.rationale, spy_price_at_entry=spy_for_swap,
            )

        # 7. Rebalance leftover cash into SPY core
        if spy_close > 0:
            port.rebalance_to_core(spy_close)

        # 8. Age picks
        port.age_positions()

        # 9. Snapshot
        equity = port.nav()
        bench_eq = benchmark_shares * spy_close if spy_close > 0 else starting_cap
        rs2 = compute_relative_status(
            equity=equity, benchmark_equity=bench_eq,
            starting_capital=starting_cap,
            peak_relative_outperformance=peak_rel,
            data_feed_ok=True, synthetic_data=False,
        )
        peak_rel = rs2.peak_relative_pnl_pct
        n_picks = len([p for p in port.positions.values() if not p.is_core])
        spy_weight = (port.core_notional() / equity) if equity > 0 else 0.0
        snap = Snapshot(
            date=str(dt.date()),
            equity=round(equity, 2),
            cash=round(port.cash, 2),
            market_value=round(equity - port.cash, 2),
            daily_pnl=round(equity - prev_equity, 2),
            cumulative_pnl=round(equity - starting_cap, 2),
            drawdown=round(max(0.0, 1 - equity / max(starting_cap, equity)), 4),
            benchmark_equity=round(bench_eq, 2),
            portfolio_return=round(rs2.portfolio_return, 4),
            benchmark_return=round(rs2.benchmark_return, 4),
            alpha=round(rs2.relative_pnl_pct, 4),
            relative_drawdown=round(rs2.relative_drawdown_pct, 4),
            spy_core_weight=round(spy_weight, 4),
            n_picks_open=n_picks,
        )
        snapshots.append(snap)
        port.peak_relative_outperformance = peak_rel
        prev_equity = equity

    metrics = _compute_metrics(snapshots, port.trades, starting_cap)
    return {
        "snapshots": [s.to_dict() for s in snapshots],
        "trades": [t.to_dict() for t in port.trades],
        "open_positions": [p.to_dict() for p in port.positions.values() if not p.is_core],
        "portfolio_state": {
            "cash": port.cash,
            "realized_pnl": port.realized_pnl,
            "peak_relative_outperformance": peak_rel,
            "inception": port.inception,
            "positions": {s: p.to_dict() for s, p in port.positions.items()},
            "trades": [t.to_dict() for t in port.trades],
        },
        "metrics": metrics,
    }


def _compute_metrics(snapshots: List[Snapshot], trades: list, start_cap: float) -> dict:
    if not snapshots:
        return {}
    eq = pd.Series([s.equity for s in snapshots])
    bench = pd.Series([s.benchmark_equity for s in snapshots])
    rets = eq.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    ann = 252
    sharpe = float(rets.mean() / rets.std() * np.sqrt(ann)) if rets.std() > 0 else 0.0
    bench_sharpe = float(bench_rets.mean() / bench_rets.std() * np.sqrt(ann)) if bench_rets.std() > 0 else 0.0
    downside = rets[rets < 0]
    sortino = float(rets.mean() / downside.std() * np.sqrt(ann)) if len(downside) > 1 and downside.std() > 0 else 0.0
    max_dd = float(max((s.drawdown for s in snapshots), default=0.0))
    max_rel_dd = float(max((s.relative_drawdown for s in snapshots), default=0.0))
    total_return = float(eq.iloc[-1] / start_cap - 1.0)
    bench_total = float(bench.iloc[-1] / start_cap - 1.0)
    n_years = max(len(snapshots) / 252, 1e-6)
    cagr = float((eq.iloc[-1] / start_cap) ** (1 / n_years) - 1.0)
    bench_cagr = float((bench.iloc[-1] / start_cap) ** (1 / n_years) - 1.0)

    excess_rets = rets - bench_rets
    info_ratio = float(excess_rets.mean() / excess_rets.std() * np.sqrt(ann)) if excess_rets.std() > 0 else 0.0

    closed_pnls = [
        (t["pnl"] if isinstance(t, dict) else t.pnl)
        for t in trades
        if (isinstance(t, dict) and t.get("exit_price") is not None)
        or (hasattr(t, "exit_price") and t.exit_price is not None)
    ]
    wins = [p for p in closed_pnls if p > 0]
    losses = [p for p in closed_pnls if p < 0]
    win_rate = float(len(wins) / len(closed_pnls)) if closed_pnls else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (None if not wins else None)

    # Alpha attribution: sum of alpha_vs_spy across closed picks
    alphas = []
    for t in trades:
        v = (t.get("alpha_vs_spy") if isinstance(t, dict) else t.alpha_vs_spy)
        if v is not None:
            alphas.append(float(v))
    avg_pick_alpha = float(np.mean(alphas)) if alphas else 0.0

    return {
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "benchmark_total_return": round(bench_total, 4),
        "benchmark_cagr": round(bench_cagr, 4),
        "alpha_total": round(total_return - bench_total, 4),
        "sharpe": round(sharpe, 3),
        "benchmark_sharpe": round(bench_sharpe, 3),
        "info_ratio": round(info_ratio, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(max_dd, 4),
        "max_relative_drawdown": round(max_rel_dd, 4),
        "win_rate": round(win_rate, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor else None,
        "n_trades": len(closed_pnls),
        "avg_win": round(float(np.mean(wins)), 2) if wins else 0.0,
        "avg_loss": round(float(np.mean(losses)), 2) if losses else 0.0,
        "largest_loss": round(float(min(closed_pnls)), 2) if closed_pnls else 0.0,
        "vol_annualized": round(float(rets.std() * np.sqrt(ann)), 4) if len(rets) else 0.0,
        "avg_pick_alpha": round(avg_pick_alpha, 4),
        "target_alpha_pct": MANDATE.target_alpha_pct,
        "max_relative_drawdown_pct": MANDATE.max_relative_drawdown_pct,
    }
