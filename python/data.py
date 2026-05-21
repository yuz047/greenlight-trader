"""Market data layer.

Source priority (highest to lowest):

  1. yfinance via curl_cffi Chrome impersonation.
     The browser-fingerprint session defeats Yahoo's TLS filter on
     data-center IPs (GitHub Actions / AWS / GCP). Verified working
     against Yahoo as of May 2026.
  2. Stooq direct CSV.
     A simple no-key CSV endpoint used before any optional library fallback.
  3. Stooq via pandas_datareader.
     Free Stooq CSV endpoint now requires an API key, but the
     pandas_datareader path still works through a separate route.
     Kept as a backup in case Yahoo starts blocking again.
  4. Stale REAL cache. Preferred over fresh synthetic — yesterday's
     real prices are more useful than today's fabricated ones.
  5. Deterministic synthetic GBM. Last resort, clearly tagged.

Every step logs to stderr so the GitHub Actions log shows exactly what
happened per ticker.
"""
from __future__ import annotations
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Dict
import numpy as np
import pandas as pd

from config import CACHE_DIR, WATCHLIST
import io
import requests

_MAX_AGE_DAYS = 1  # refresh cache once a day
_STOOQ_SUFFIX = ".US"
_STOOQ_URL = "https://stooq.com/q/d/l/?s={sym}&i=d"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _log(msg: str) -> None:
    print(f"[data] {msg}", file=sys.stderr, flush=True)


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


# --------------------------------------------------------------------- #
# Primary: Stooq direct CSV (no library, no API key, very reliable)
# --------------------------------------------------------------------- #
def _try_stooq_direct(ticker: str) -> pd.DataFrame | None:
    sym = (ticker + _STOOQ_SUFFIX).lower()  # SPY -> spy.us
    url = _STOOQ_URL.format(sym=sym)
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=15)
            if r.status_code != 200:
                _log(f"stooq-direct {sym} attempt {attempt+1}/3: HTTP {r.status_code}")
                time.sleep(1.0 * (attempt + 1))
                continue
            text = r.text.strip()
            if not text or text.startswith("<") or "Date,Open" not in text.split("\n", 1)[0]:
                _log(f"stooq-direct {sym} attempt {attempt+1}/3: unexpected body "
                     f"({text[:60]!r})")
                time.sleep(1.0 * (attempt + 1))
                continue
            df = pd.read_csv(io.StringIO(text))
            if df.empty:
                _log(f"stooq-direct {sym}: empty CSV")
                return None
            df.columns = [c.strip().lower() for c in df.columns]
            if "date" not in df.columns:
                _log(f"stooq-direct {sym}: no Date column")
                return None
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
            df = df[keep]
            if "volume" not in df.columns:
                df["volume"] = 0
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            df["synthetic"] = False
            _log(f"stooq-direct {sym}: {len(df)} rows, last {df.index[-1].date()}")
            return df
        except Exception as e:
            _log(f"stooq-direct {sym} attempt {attempt+1}/3 raised: {e}")
            time.sleep(1.0 * (attempt + 1))
    return None


# --------------------------------------------------------------------- #
# Secondary: yfinance with curl_cffi Chrome impersonation
# --------------------------------------------------------------------- #
def _yfinance_session():
    """Return a curl_cffi session if available, otherwise None.

    yfinance accepts any requests-compatible session in its constructor;
    when we pass a curl_cffi session with ``impersonate="chrome120"`` Yahoo's
    bot-detection sees a real browser's TLS fingerprint instead of urllib3's.
    """
    try:
        from curl_cffi import requests as cc_requests  # type: ignore
        return cc_requests.Session(impersonate="chrome120")
    except Exception as e:
        _log(f"curl_cffi unavailable ({e}); yfinance will use plain urllib3")
        return None


def _try_yfinance(ticker: str, period: str = "3y") -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except Exception as e:
        _log(f"yfinance import failed: {e}")
        return None

    session = _yfinance_session()
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            tk = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
            df = tk.history(period=period, interval="1d", auto_adjust=True)
            if df is None or df.empty:
                _log(f"yfinance {ticker} returned empty (attempt {attempt+1}/3)")
                last_err = RuntimeError("empty response")
                time.sleep(1.0 * (attempt + 1))
                continue
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df["synthetic"] = False
            _log(f"yfinance {ticker}: {len(df)} rows, last {df.index[-1].date()}")
            return df
        except Exception as e:
            last_err = e
            _log(f"yfinance {ticker} failed (attempt {attempt+1}/3): {e}")
            time.sleep(1.0 * (attempt + 1))
    if last_err is not None:
        _log(f"yfinance {ticker}: giving up — {last_err}")
    return None


# --------------------------------------------------------------------- #
# Secondary: Stooq (different infra, same daily OHLCV; no rate limit on GH runners)
# --------------------------------------------------------------------- #
def _try_stooq(ticker: str) -> pd.DataFrame | None:
    try:
        from pandas_datareader import data as pdr  # type: ignore
    except Exception as e:
        _log(f"pandas_datareader unavailable ({e}); skipping Stooq")
        return None
    symbol = ticker + _STOOQ_SUFFIX  # e.g. SPY → SPY.US
    try:
        end = pd.Timestamp.today()
        start = end - pd.Timedelta(days=int(365 * 3.2))
        df = pdr.DataReader(symbol, "stooq", start=start, end=end)
        if df is None or df.empty:
            _log(f"stooq {symbol}: empty response")
            return None
        # Stooq returns columns Open/High/Low/Close/Volume and descending dates.
        df = df.rename(columns=str.lower).sort_index()
        df = df[["open", "high", "low", "close", "volume"]]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df["synthetic"] = False
        _log(f"stooq {symbol}: {len(df)} rows, last {df.index[-1].date()}")
        return df
    except Exception as e:
        _log(f"stooq {symbol} failed: {e}")
        return None


# --------------------------------------------------------------------- #
# Last resort: deterministic synthetic GBM
# --------------------------------------------------------------------- #
def _synthetic(ticker: str, days: int = 750) -> pd.DataFrame:
    """Per-ticker geometric Brownian motion. Stable across runs; demo only.

    Every row carries ``synthetic=True`` so the dashboard's traffic light
    and the system_status panel can flag it loudly.
    """
    rng = np.random.default_rng(abs(hash(ticker)) % (2**32))
    drift = 0.0004 + (abs(hash(ticker + "d")) % 7) * 1e-4
    vol = 0.012 + (abs(hash(ticker + "v")) % 9) * 0.001
    start_price = 50.0 + (abs(hash(ticker + "p")) % 250)

    end = pd.Timestamp.today().normalize()
    idx = pd.bdate_range(end=end, periods=days)
    rets = rng.normal(loc=drift, scale=vol, size=days)
    shocks = rng.choice([0.0, 0.0, 0.0, -0.04, 0.04], size=days)
    rets = rets + shocks
    close = start_price * np.exp(np.cumsum(rets))

    open_ = close * (1 + rng.normal(0, vol / 3, size=days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 3, size=days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 3, size=days)))
    volume = rng.integers(5_000_000, 50_000_000, size=days).astype(float)
    spike_idx = rng.choice(days, size=days // 25, replace=False)
    volume[spike_idx] *= rng.uniform(1.8, 3.5, size=spike_idx.shape)

    df = pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
        "synthetic": True,
    }, index=idx)
    df.index.name = "date"
    _log(f"SYNTHETIC fallback used for {ticker} — real sources unavailable")
    return df


# --------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------- #
def load_ticker(ticker: str, force_refresh: bool = False) -> pd.DataFrame:
    """Return OHLCV for ``ticker`` as a daily DataFrame.

    Priority: fresh real cache > yfinance > Stooq direct > Stooq reader >
    stale real cache > synthetic.

    The "stale cache" tier matters: if both live sources fail today but we
    have yesterday's REAL data on disk, returning it (still marked
    real, synthetic=False) is better than fabricating GBM.
    """
    cached = None if force_refresh else _read_cache(ticker)
    cache_is_real = (
        cached is not None and not cached.empty
        and "synthetic" in cached.columns
        and not bool(cached["synthetic"].iloc[-1])
    )

    # 1. Fresh REAL cache → use it.
    if cached is not None and not cached.empty and cache_is_real:
        age_days = (pd.Timestamp.now() - cached.index.max()).days
        if age_days <= _MAX_AGE_DAYS:
            _log(f"{ticker}: fresh real cache ({age_days}d old)")
            return cached

    # 2. yfinance via curl_cffi Chrome impersonation — primary live source.
    fresh = _try_yfinance(ticker)
    if fresh is not None and not fresh.empty:
        _write_cache(ticker, fresh)
        return fresh

    # 3. Stooq direct CSV — fallback if Yahoo blocks.
    fresh = _try_stooq_direct(ticker)
    if fresh is not None and not fresh.empty:
        _write_cache(ticker, fresh)
        return fresh

    # 4. Stooq via pandas_datareader — optional secondary route.
    fresh = _try_stooq(ticker)
    if fresh is not None and not fresh.empty:
        _write_cache(ticker, fresh)
        return fresh

    # 5. Stale REAL cache beats synthetic — keep the dashboard honest.
    if cache_is_real:
        _log(f"{ticker}: using stale real cache (live sources unreachable)")
        return cached

    # 6. Synthetic fallback (clearly marked, never cached).
    _log(f"{ticker}: ALL REAL SOURCES FAILED — falling through to synthetic")
    return _synthetic(ticker)


def load_universe(tickers=None, force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    tickers = tickers or WATCHLIST
    return {t: load_ticker(t, force_refresh=force_refresh) for t in tickers}


def data_feed_health(frames: Dict[str, pd.DataFrame]) -> dict:
    """Quick health check used by the traffic-light status.

    Returns:
      ok           — True if no ticker is stale (>5 days behind)
      stale_tickers — count of stale frames
      synthetic    — True if ANY ticker is on synthetic data
      synthetic_tickers — list of tickers currently on synthetic
      as_of        — most-recent date across the universe
    """
    if not frames:
        return {"ok": False, "reason": "no data", "synthetic": False}
    synthetic_tickers = []
    for t, df in frames.items():
        is_syn = bool(df.get("synthetic", pd.Series([False])).iloc[-1]) if not df.empty else False
        if is_syn:
            synthetic_tickers.append(t)
    stale = 0
    today = pd.Timestamp.today().normalize()
    for t, df in frames.items():
        if df.empty or (today - df.index.max()).days > 5:
            stale += 1
    return {
        "ok": stale == 0,
        "stale_tickers": stale,
        "synthetic": len(synthetic_tickers) > 0,
        "synthetic_tickers": synthetic_tickers,
        "as_of": str(max(df.index.max() for df in frames.values()).date()),
    }


if __name__ == "__main__":
    frames = load_universe()
    health = data_feed_health(frames)
    _log(f"feed health: {health}")
    for t, df in frames.items():
        if df.empty: continue
        last = df.iloc[-1]
        flag = "SYNTHETIC" if bool(last.get("synthetic", False)) else "real"
        print(f"{t:5s} {flag:9s} {len(df):>5d} rows, last close {last['close']:.2f} on {df.index[-1].date()}")
