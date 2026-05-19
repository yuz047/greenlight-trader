"""Market data layer.

Primary source is yfinance. We persist a CSV per ticker under data/cache/
so that re-runs do not re-download the full history. If yfinance is
unavailable (no network in CI sandbox, etc.) and no cache is present, we
fall back to a deterministic synthetic OHLCV generator so the rest of
the pipeline still produces something demonstrable.

The synthetic fallback is clearly marked on every row via the `synthetic`
column so it can never silently mix with real data.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict
import numpy as np
import pandas as pd

from config import CACHE_DIR, WATCHLIST

_MAX_AGE_DAYS = 1  # refresh cache once a day


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}.csv"


def _read_cache(ticker: str) -> pd.DataFrame | None:
    p = _cache_path(ticker)
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"], index_col="date")
    return df


def _write_cache(ticker: str, df: pd.DataFrame) -> None:
    out = df.copy()
    out.index.name = "date"
    out.to_csv(_cache_path(ticker))


def _try_yfinance(ticker: str, period: str = "3y") -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except Exception:
        return None
    try:
        df = yf.download(
            ticker, period=period, interval="1d",
            progress=False, auto_adjust=True, threads=False,
        )
        if df is None or df.empty:
            return None
        # yfinance may return a MultiIndex columns frame for a single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df["synthetic"] = False
        return df
    except Exception:
        return None


def _synthetic(ticker: str, days: int = 750) -> pd.DataFrame:
    """Deterministic geometric Brownian motion per ticker.

    Seeded by the ticker string so each name has a stable price history
    across runs. This is for offline / CI demo only.
    """
    rng = np.random.default_rng(abs(hash(ticker)) % (2**32))
    # Per-ticker drift/vol so the watchlist behaves differently
    drift = 0.0004 + (abs(hash(ticker + "d")) % 7) * 1e-4
    vol = 0.012 + (abs(hash(ticker + "v")) % 9) * 0.001
    start_price = 50.0 + (abs(hash(ticker + "p")) % 250)

    # Trading days only (Mon-Fri), ending today.
    end = pd.Timestamp.today().normalize()
    idx = pd.bdate_range(end=end, periods=days)
    rets = rng.normal(loc=drift, scale=vol, size=days)
    # Occasional shocks for realism
    shocks = rng.choice([0.0, 0.0, 0.0, -0.04, 0.04], size=days)
    rets = rets + shocks
    close = start_price * np.exp(np.cumsum(rets))

    open_ = close * (1 + rng.normal(0, vol / 3, size=days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 3, size=days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 3, size=days)))
    volume = rng.integers(5_000_000, 50_000_000, size=days).astype(float)
    # Sprinkle volume spikes
    spike_idx = rng.choice(days, size=days // 25, replace=False)
    volume[spike_idx] *= rng.uniform(1.8, 3.5, size=spike_idx.shape)

    df = pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
        "synthetic": True,
    }, index=idx)
    df.index.name = "date"
    return df


def load_ticker(ticker: str, force_refresh: bool = False) -> pd.DataFrame:
    """Return OHLCV for ``ticker`` as a daily DataFrame."""
    cached = None if force_refresh else _read_cache(ticker)
    if cached is not None and not cached.empty:
        age_days = (pd.Timestamp.now() - cached.index.max()).days
        if age_days <= _MAX_AGE_DAYS:
            return cached

    fresh = _try_yfinance(ticker)
    if fresh is not None and not fresh.empty:
        _write_cache(ticker, fresh)
        return fresh

    if cached is not None and not cached.empty:
        return cached

    syn = _synthetic(ticker)
    _write_cache(ticker, syn)
    return syn


def load_universe(tickers=None, force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    tickers = tickers or WATCHLIST
    return {t: load_ticker(t, force_refresh=force_refresh) for t in tickers}


def data_feed_health(frames: Dict[str, pd.DataFrame]) -> dict:
    """Quick health check used by the traffic-light status."""
    if not frames:
        return {"ok": False, "reason": "no data", "synthetic": False}
    synthetic = any(bool(df.get("synthetic", pd.Series([False])).iloc[-1]) for df in frames.values())
    stale = 0
    today = pd.Timestamp.today().normalize()
    for t, df in frames.items():
        if df.empty or (today - df.index.max()).days > 5:
            stale += 1
    return {
        "ok": stale == 0,
        "stale_tickers": stale,
        "synthetic": synthetic,
        "as_of": str(max(df.index.max() for df in frames.values()).date()),
    }


if __name__ == "__main__":
    frames = load_universe()
    for t, df in frames.items():
        print(f"{t}: {len(df)} rows, last close {df['close'].iloc[-1]:.2f}, "
              f"synthetic={bool(df['synthetic'].iloc[-1])}")
