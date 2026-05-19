"""Risk engine — V2.

The mandate is relative to SPY:
  - Target return: SPY + 10% over the test window
  - Max relative drawdown: trail SPY by no more than 5%

So the risk gate's job is:
  1. Compute relative outperformance vs SPY at every step.
  2. Track its all-time peak.
  3. If we've given back ``MANDATE.max_relative_drawdown_pct`` from that
     peak, force a flat alpha sleeve until the breach unwinds.
  4. Emit a traffic light reflecting current relative slack.

Position sizing for new picks is governed by ``MANDATE.pick_weight_per_position``
(default 25% of NAV) rather than a per-trade dollar cap, because the
constraint is *underperformance vs SPY*, not absolute loss.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from config import MANDATE


@dataclass
class RelativeStatus:
    light: str           # green / yellow / red / black
    reason: str
    portfolio_return: float        # cumulative since inception
    benchmark_return: float
    relative_pnl_pct: float        # portfolio - benchmark, in % of starting capital
    relative_drawdown_pct: float   # how far below the relative peak we are
    peak_relative_pnl_pct: float


def compute_relative_status(
    *, equity: float, benchmark_equity: float,
    starting_capital: float, peak_relative_outperformance: float,
    data_feed_ok: bool, synthetic_data: bool,
) -> RelativeStatus:
    if not data_feed_ok:
        return RelativeStatus(
            light="black",
            reason="Data feed failure — trading halted.",
            portfolio_return=0.0, benchmark_return=0.0,
            relative_pnl_pct=0.0, relative_drawdown_pct=0.0,
            peak_relative_pnl_pct=peak_relative_outperformance,
        )

    port_ret = equity / starting_capital - 1.0 if starting_capital > 0 else 0.0
    bench_ret = benchmark_equity / starting_capital - 1.0 if starting_capital > 0 else 0.0
    rel = port_ret - bench_ret

    # Drawdown from the all-time relative peak (in fraction of starting capital).
    peak = max(peak_relative_outperformance, rel)
    rel_dd = max(0.0, peak - rel)

    cap = MANDATE.max_relative_drawdown_pct
    red_floor = MANDATE.red_gate_fraction * cap     # 0.8 × 5% = 4.0%
    yellow_floor = MANDATE.yellow_gate_fraction * cap  # 0.4 × 5% = 2.0%
    if rel_dd >= red_floor:
        light = "red"
        reason = (f"Relative drawdown {rel_dd*100:.2f}% past red gate "
                  f"({red_floor*100:.1f}%) — closing all picks, holding 100% SPY.")
    elif rel_dd >= yellow_floor:
        light = "yellow"
        reason = (f"Relative drawdown {rel_dd*100:.2f}% past yellow gate "
                  f"({yellow_floor*100:.1f}%) — alpha sleeve down to one pick.")
    else:
        target = MANDATE.target_alpha_pct
        if rel >= target:
            reason = f"Above target — beating SPY by {rel*100:+.2f}%."
        elif rel >= 0:
            reason = f"On track — beating SPY by {rel*100:+.2f}%."
        else:
            reason = f"Behind SPY by {-rel*100:.2f}% — within tolerance."
        light = "green"

    if synthetic_data and light != "black":
        reason = reason + " (data: synthetic fallback)"

    return RelativeStatus(
        light=light, reason=reason,
        portfolio_return=port_ret, benchmark_return=bench_ret,
        relative_pnl_pct=rel, relative_drawdown_pct=rel_dd,
        peak_relative_pnl_pct=peak,
    )


# Legacy function name kept for run_daily/seed compatibility — wraps the
# relative status in the old dict shape so the dashboard renders unchanged.
def account_status(
    *, nav: float, day_pnl: float, peak_nav: float,
    data_feed_ok: bool, synthetic_data: bool,
    benchmark_equity: float = 0.0,
    peak_relative_outperformance: float = 0.0,
) -> dict:
    rs = compute_relative_status(
        equity=nav,
        benchmark_equity=benchmark_equity if benchmark_equity > 0 else nav,
        starting_capital=MANDATE.starting_capital,
        peak_relative_outperformance=peak_relative_outperformance,
        data_feed_ok=data_feed_ok,
        synthetic_data=synthetic_data,
    )
    return {
        "light": rs.light,
        "reason": rs.reason,
        "portfolio_return": rs.portfolio_return,
        "benchmark_return": rs.benchmark_return,
        "relative_pnl_pct": rs.relative_pnl_pct,
        "relative_drawdown_pct": rs.relative_drawdown_pct,
        "peak_relative_pnl_pct": rs.peak_relative_pnl_pct,
        # Back-compat fields the dashboard still reads
        "daily_loss_pct": max(0.0, -day_pnl / max(nav - day_pnl, 1e-9)) if day_pnl < 0 else 0.0,
        "drawdown_pct": max(0.0, 1 - nav / peak_nav) if peak_nav > 0 else 0.0,
        "peak_nav": peak_nav,
    }
