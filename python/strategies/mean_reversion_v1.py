"""RSI oversold within 2% of 50d SMA."""
from __future__ import annotations
import math
from typing import Optional
import pandas as pd

from ._types import Signal


MANIFEST = {
    "id": "mean_reversion_v1",
    "version": "1.0",
    "kind": "signal",
    "params": {
        "rsi_window": 14,
        "rsi_threshold": 30.0,
        "sma_window": 50,
        "max_dist_to_sma": 0.02,
        "atr_window": 14,
        "stop_atr": 1.0,
        "target_atr": 1.0,
        "max_hold_days": 3,
    },
    "rules": (
        "RSI(14) < 30; within 2% of 50d SMA; "
        "SPY not in deep drawdown. Stop=1 ATR, target=1 ATR, max hold 3 days."
    ),
    "status": "active",
}


def run(
    symbol: str, df: pd.DataFrame, params: dict,
    *, regime: str, sentiment: float, universe=None,
) -> Optional[Signal]:
    if df.empty:
        return None
    last = df.iloc[-1]
    needed = ["close", "rsi14", "sma50", "atr14"]
    if any(c not in df.columns or pd.isna(last[c]) for c in needed):
        return None
    if regime == "distressed":
        return None
    if last["rsi14"] >= params["rsi_threshold"]:
        return None
    dist = abs(last["close"] - last["sma50"]) / last["sma50"]
    if dist > params["max_dist_to_sma"]:
        return None
    atr_v = float(last["atr14"])
    if atr_v <= 0 or math.isnan(atr_v):
        return None
    oversold = (params["rsi_threshold"] - last["rsi14"]) / params["rsi_threshold"]
    score = min(1.0, 0.4 + 0.6 * oversold)
    return Signal(
        symbol=symbol,
        strategy_id=MANIFEST["id"],
        side="long",
        rationale=(
            f"RSI14={last['rsi14']:.1f} below {params['rsi_threshold']:.0f} and price "
            f"${last['close']:.2f} within {dist*100:.1f}% of 50d SMA "
            f"${last['sma50']:.2f}; regime={regime}."
        ),
        stop_distance=params["stop_atr"] * atr_v,
        target_distance=params["target_atr"] * atr_v,
        max_hold_days=int(params["max_hold_days"]),
        score=float(score),
    )
