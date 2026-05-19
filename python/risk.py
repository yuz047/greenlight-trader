"""Risk engine.

Two responsibilities:

1. ``size_position(signal, price, nav, cash)`` -> shares (int) or 0 if
   the trade would violate any account-level cap.
2. ``account_status(...)`` -> a traffic-light dict used by the dashboard.

All caps come from ``config.RISK``.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from config import RISK


@dataclass
class SizingResult:
    shares: int
    dollar_risk: float
    notional: float
    reason: str           # populated whether or not we sized

    @property
    def took(self) -> bool:
        return self.shares > 0


def size_position(
    *, entry_price: float, stop_distance: float,
    nav: float, cash: float, open_positions: int,
    existing_symbol_exposure: float,
) -> SizingResult:
    """Compute share count for a candidate trade given risk caps.

    Returns SizingResult with shares=0 (and a `reason`) when any cap blocks the trade.
    """
    if entry_price <= 0 or stop_distance <= 0:
        return SizingResult(0, 0.0, 0.0, "invalid price or stop")
    if open_positions >= RISK.max_open_positions:
        return SizingResult(0, 0.0, 0.0,
            f"max_open_positions cap ({RISK.max_open_positions}) reached")

    dollar_risk = nav * RISK.max_risk_per_trade_pct
    shares = int(dollar_risk // stop_distance)
    if shares <= 0:
        return SizingResult(0, 0.0, 0.0,
            f"stop {stop_distance:.2f} too wide for ${dollar_risk:.2f} per-trade risk")

    notional = shares * entry_price
    # Per-name exposure cap
    name_cap = RISK.max_single_position_pct * nav
    while shares > 0 and (notional + existing_symbol_exposure) > name_cap:
        shares -= 1
        notional = shares * entry_price
    if shares <= 0:
        return SizingResult(0, 0.0, 0.0,
            f"single-position cap ({RISK.max_single_position_pct:.0%}) blocked entry")

    # Cash cap (no leverage in V1)
    if notional > cash:
        shares = int(cash // entry_price)
        notional = shares * entry_price
        if shares <= 0:
            return SizingResult(0, 0.0, 0.0, "insufficient cash")

    if notional < RISK.min_dollar_position:
        return SizingResult(0, 0.0, 0.0,
            f"min position ${RISK.min_dollar_position:.0f} not met")

    return SizingResult(
        shares=shares,
        dollar_risk=shares * stop_distance,
        notional=notional,
        reason=(
            f"size={shares} @ ${entry_price:.2f}; risk ${shares * stop_distance:.2f} "
            f"({(shares * stop_distance) / nav * 100:.2f}% NAV)"
        ),
    )


def account_status(
    *, nav: float, day_pnl: float, peak_nav: float,
    data_feed_ok: bool, synthetic_data: bool,
) -> dict:
    """Compute the system traffic light.

    - black: data feed failure
    - red: daily loss or drawdown breach
    - yellow: approaching either cap
    - green: normal
    """
    daily_loss_pct = -day_pnl / max(nav - day_pnl, 1e-9) if day_pnl < 0 else 0.0
    drawdown_pct = max(0.0, 1 - nav / peak_nav) if peak_nav > 0 else 0.0

    if not data_feed_ok:
        light = "black"
        reason = "Data feed failure — trading halted."
    elif drawdown_pct >= RISK.max_drawdown_pct:
        light = "red"
        reason = (f"Drawdown {drawdown_pct*100:.1f}% >= cap "
                  f"{RISK.max_drawdown_pct*100:.1f}% — trading paused.")
    elif daily_loss_pct >= RISK.max_daily_loss_pct:
        light = "red"
        reason = (f"Daily loss {daily_loss_pct*100:.1f}% >= cap "
                  f"{RISK.max_daily_loss_pct*100:.1f}% — trading paused.")
    elif (drawdown_pct >= 0.7 * RISK.max_drawdown_pct or
          daily_loss_pct >= 0.7 * RISK.max_daily_loss_pct):
        light = "yellow"
        reason = "Approaching daily loss or drawdown cap — size down."
    else:
        light = "green"
        reason = "Risk within limits."

    if synthetic_data and light != "black":
        # Don't mask a real risk-off state, but flag the data source.
        reason = reason + " (data: synthetic fallback)"

    return {
        "light": light,
        "reason": reason,
        "daily_loss_pct": daily_loss_pct,
        "drawdown_pct": drawdown_pct,
        "peak_nav": peak_nav,
    }
