"""Walk-forward backtest used by seed_history.py and the EOD review.

Simulates the daily engine over the last ~2 years of OHLCV with the
same risk caps and the same strategy registry that runs live. The
output is a list of portfolio snapshots and a list of trades, which is
exactly what the live engine produces — so the dashboard sees one
continuous history.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List
import math
import pandas as pd
import numpy as np

from config import RISK, ACTIVE_IDS, WATCHLIST, BENCHMARK, BACKTEST_DAYS
from signals import enrich, market_regime
from strategies import fire_all, manifests_for
from risk import size_position
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

    def to_dict(self) -> dict:
        return asdict(self)


def _bar(df: pd.DataFrame, dt) -> dict | None:
    if dt not in df.index:
        return None
    row = df.loc[dt]
    return {"open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"])}


def run_backtest(
    frames: Dict[str, pd.DataFrame],
    days: int = BACKTEST_DAYS,
    sentiment_provider=None,
) -> dict:
    """Run a walk-forward sim over the last ``days`` trading days.

    Returns {snapshots, trades, final_portfolio_dict, metrics}.
    """
    # Pre-enrich every frame once
    enriched = {sym: enrich(df) for sym, df in frames.items()}
    spy = frames[BENCHMARK]

    # Align timeline to the benchmark
    timeline = spy.index[-days:]
    port = Portfolio()
    snapshots: List[Snapshot] = []
    prev_equity = port.nav()

    for i, dt in enumerate(timeline):
        # 1. Mark to today's close to age the book
        close_prices = {}
        bars = {}
        for sym, df in frames.items():
            if dt in df.index:
                row = df.loc[dt]
                close_prices[sym] = float(row["close"])
                bars[sym] = {"open": float(row["open"]), "high": float(row["high"]),
                             "low": float(row["low"]), "close": float(row["close"])}
        port.mark_to_market(close_prices)

        # 2. Apply stops/targets/max-hold on today's bar
        port.apply_stops_and_targets(bars)

        # 3. Compute regime + sentiment as of today
        regime = market_regime(spy.loc[:dt])
        sent = sentiment_provider(dt) if sentiment_provider else {}

        # 4. Generate signals using data up to AND including today's close
        sym_enriched_to_date = {s: e.loc[:dt] for s, e in enriched.items()}
        signals = fire_all(sym_enriched_to_date, regime=regime,
                           sentiment=sent, active_ids=ACTIVE_IDS,
                           universe=sym_enriched_to_date)

        # 5. Open trades at TOMORROW's open if available, else today's close.
        next_dt = timeline[i + 1] if i + 1 < len(timeline) else None
        for sig in signals:
            if sig.symbol in port.positions:
                continue
            if len(port.positions) >= RISK.max_open_positions:
                break
            # Risk gate: skip new entries if drawdown or daily loss breached
            nav = port.nav()
            day_pnl = nav - prev_equity
            if (day_pnl < 0 and (-day_pnl / max(prev_equity, 1e-9)) >= RISK.max_daily_loss_pct):
                break
            dd = 1 - nav / port.peak_nav if port.peak_nav > 0 else 0
            if dd >= RISK.max_drawdown_pct:
                break
            entry_price = None
            if next_dt is not None and next_dt in frames[sig.symbol].index:
                entry_price = float(frames[sig.symbol].loc[next_dt, "open"])
            else:
                entry_price = close_prices.get(sig.symbol)
            if entry_price is None or math.isnan(entry_price):
                continue
            sz = size_position(
                entry_price=entry_price,
                stop_distance=sig.stop_distance,
                nav=nav, cash=port.cash,
                open_positions=len(port.positions),
                existing_symbol_exposure=port.open_position_exposure(sig.symbol),
            )
            if not sz.took:
                continue
            port.open_trade(
                symbol=sig.symbol, quantity=sz.shares, entry_price=entry_price,
                stop_distance=sig.stop_distance, target_distance=sig.target_distance,
                max_hold_days=sig.max_hold_days, strategy_id=sig.strategy_id,
                thesis=sig.rationale,
            )

        # 6. Age positions and snapshot
        port.age_positions()
        port.update_peak()
        equity = port.nav()
        snap = Snapshot(
            date=str(dt.date()),
            equity=round(equity, 2),
            cash=round(port.cash, 2),
            market_value=round(equity - port.cash, 2),
            daily_pnl=round(equity - prev_equity, 2),
            cumulative_pnl=round(equity - RISK.starting_capital, 2),
            drawdown=round(max(0.0, 1 - equity / port.peak_nav), 4),
        )
        snapshots.append(snap)
        prev_equity = equity

    metrics = _compute_metrics(snapshots, port.trades, RISK.starting_capital)
    return {
        "snapshots": [s.to_dict() for s in snapshots],
        "trades": [t.to_dict() for t in port.trades],
        "open_positions": [p.to_dict() for p in port.positions.values()],
        "portfolio_state": {
            "cash": port.cash, "realized_pnl": port.realized_pnl,
            "peak_nav": port.peak_nav, "inception": port.inception,
            "positions": {s: p.to_dict() for s, p in port.positions.items()},
            "trades": [t.to_dict() for t in port.trades],
        },
        "metrics": metrics,
    }


def _compute_metrics(snapshots: List[Snapshot], trades: list, start_cap: float) -> dict:
    if not snapshots:
        return {}
    equity = pd.Series([s.equity for s in snapshots])
    rets = equity.pct_change().dropna()
    ann = 252
    sharpe = float(rets.mean() / rets.std() * np.sqrt(ann)) if rets.std() > 0 else 0.0
    downside = rets[rets < 0]
    sortino = float(rets.mean() / downside.std() * np.sqrt(ann)) if len(downside) > 1 and downside.std() > 0 else 0.0
    max_dd = float(max(s.drawdown for s in snapshots))
    total_return = float(equity.iloc[-1] / start_cap - 1.0)
    n_years = max(len(snapshots) / 252, 1e-6)
    cagr = float((equity.iloc[-1] / start_cap) ** (1 / n_years) - 1.0)

    closed = [t for t in trades if (isinstance(t, dict) and t.get("exit_price") is not None) or
              (hasattr(t, "exit_price") and t.exit_price is not None)]
    pnls = [t["pnl"] if isinstance(t, dict) else t.pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = float(len(wins) / len(pnls)) if pnls else 0.0
    profit_factor = float(sum(wins) / abs(sum(losses))) if losses else (float("inf") if wins else 0.0)

    return {
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        "n_trades": len(pnls),
        "avg_win": round(float(np.mean(wins)), 2) if wins else 0.0,
        "avg_loss": round(float(np.mean(losses)), 2) if losses else 0.0,
        "largest_loss": round(float(min(pnls)), 2) if pnls else 0.0,
        "vol_annualized": round(float(rets.std() * np.sqrt(ann)), 4) if len(rets) else 0.0,
    }
