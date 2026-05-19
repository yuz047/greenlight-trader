"""20-day breakout with volume confirmation, regime filter, and sentiment gate."""
from __future__ import annotations
import math
from typing import Optional
import pandas as pd

from ._types import Signal


MANIFEST = {
    "id": "momentum_breakout_v1",
    "version": "1.0",
    "kind": "signal",
    "params": {
        "breakout_window": 20,
        "volume_mult": 1.5,
        "atr_window": 14,
        "stop_atr": 1.0,
        "target_atr": 2.0,
        "max_hold_days": 5,
    },
    "rules": (
        "Close > 20d high; volume > 1.5x 20d avg vol; "
        "SPY 50d > 200d; news sentiment >= 0. "
        "Stop=1 ATR, target=2 ATR, max hold 5 days."
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
    needed = ["close", "high20", "vol_ratio20", "atr14", "sma50", "sma200"]
    if any(c not in df.columns or pd.isna(last[c]) for c in needed):
        return None
    if regime in ("risk_off", "distressed"):
        return None
    if sentiment < 0:
        return None
    if last["close"] <= last["high20"]:
        return None
    if last["vol_ratio20"] < params["volume_mult"]:
        return None
    atr_v = float(last["atr14"])
    if atr_v <= 0 or math.isnan(atr_v):
        return None
    breakout_pct = (last["close"] - last["high20"]) / last["high20"]
    score = min(1.0, 0.5 + 5 * breakout_pct + 0.1 * (last["vol_ratio20"] - params["volume_mult"]))
    return Signal(
        symbol=symbol,
        strategy_id=MANIFEST["id"],
        side="long",
        rationale=(
            f"Close ${last['close']:.2f} broke above 20d high ${last['high20']:.2f} "
            f"on volume {last['vol_ratio20']:.2f}x 20d avg; regime={regime}, "
            f"sentiment={sentiment:+.2f}."
        ),
        stop_distance=params["stop_atr"] * atr_v,
        target_distance=params["target_atr"] * atr_v,
        max_hold_days=int(params["max_hold_days"]),
        score=float(score),
    )
