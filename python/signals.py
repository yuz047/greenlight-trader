"""Technical signal computation.

Keep this layer dependency-free so the strategy layer can stay
declarative: strategies pull signals off the DataFrame by name and
combine them with rule logic.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / window, adjust=False).mean()
    roll_down = down.ewm(alpha=1.0 / window, adjust=False).mean()
    rs = roll_up / roll_down.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False).mean()


def rolling_high(close: pd.Series, window: int) -> pd.Series:
    # max of the prior `window` closes, excluding today
    return close.shift(1).rolling(window, min_periods=window).max()


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    avg = volume.rolling(window, min_periods=window).mean()
    return volume / avg


def daily_return(close: pd.Series) -> pd.Series:
    return close.pct_change()


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Attach all signals used by V1 strategies."""
    out = df.copy()
    out["sma20"] = sma(out["close"], 20)
    out["sma50"] = sma(out["close"], 50)
    out["sma200"] = sma(out["close"], 200)
    out["rsi14"] = rsi(out["close"], 14)
    out["atr14"] = atr(out, 14)
    out["high20"] = rolling_high(out["close"], 20)
    out["vol_ratio20"] = volume_ratio(out["volume"], 20)
    out["ret1"] = daily_return(out["close"])
    return out


def market_regime(spy_df: pd.DataFrame) -> str:
    """Coarse regime tag for the benchmark.

    - risk_on: 50d > 200d AND close > 50d
    - neutral: 50d > 200d but close < 50d, or close > 200d only
    - risk_off: 50d < 200d
    - distressed: drawdown from 200d high > 10%
    """
    s = enrich(spy_df).dropna(subset=["sma50", "sma200"])
    if s.empty:
        return "unknown"
    last = s.iloc[-1]
    hi200 = s["close"].rolling(200, min_periods=200).max().iloc[-1]
    dd = 1.0 - last["close"] / hi200 if pd.notna(hi200) else 0.0
    if dd > 0.10:
        return "distressed"
    if last["sma50"] < last["sma200"]:
        return "risk_off"
    if last["close"] > last["sma50"]:
        return "risk_on"
    return "neutral"
