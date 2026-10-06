"""Yahoo daily bars, explicit split-only research prices, no synthetic fallback.

Caches are local and gitignored. A denied request is never retried. A rate-limit
response opens a one-minute circuit; a later invocation may try again after it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import yfinance as yf
from yfinance._http import new_session

from config import CACHE_DIR
from data_contracts import PriceBar

CALENDAR = xcals.get_calendar("XNYS")
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class UpstreamHTTPError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f'upstream_HTTP_{status_code}')


def latest_completed_market_date(now: datetime | None = None) -> str:
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tz is None:
        now = now.tz_localize("UTC")
    day = now.tz_convert("America/New_York").date().isoformat()
    session = CALENDAR.date_to_session(day, direction="previous")
    if CALENDAR.session_close(session) > now:
        session = CALENDAR.previous_session(session)
    return session.date().isoformat()


def expected_sessions(start: str, end: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([x.date() for x in CALENDAR.sessions_in_range(start, end)])


def normalize_history(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or not set(PRICE_COLUMNS).issubset(raw.columns):
        raise ValueError("empty_or_missing_OHLCV")
    frame = raw.copy()
    frame.index = pd.DatetimeIndex([x.date() for x in pd.to_datetime(frame.index)])
    if frame.index.has_duplicates:
        raise ValueError("duplicate_trading_dates")
    frame = frame.sort_index()
    # Yahoo emits all-empty OHLC rows on some index holidays. Retain partial
    # rows so validation fails on genuine trading-day defects.
    frame = frame.loc[~frame[["Open", "High", "Low", "Close"]].isna().all(axis=1)]
    frame = frame.reindex(columns=PRICE_COLUMNS + ["Adj Close", "Dividends", "Stock Splits"])
    for name in ["Dividends", "Stock Splits"]:
        frame[name] = frame[name].fillna(0)
    frame["Adj Close"] = frame["Adj Close"].fillna(frame["Close"])
    if not np.isfinite(frame[PRICE_COLUMNS].to_numpy(dtype=float)).all():
        raise ValueError("invalid_OHLCV")
    if (frame[["Open", "High", "Low", "Close"]] <= 0).any().any() or (frame["Volume"] < 0).any():
        raise ValueError("invalid_price_or_volume")
    if ((frame["High"] + 1e-6 < frame[["Open", "Low", "Close"]].max(axis=1)) | (frame["Low"] - 1e-6 > frame[["Open", "High", "Close"]].min(axis=1))).any():
        raise ValueError("inconsistent_OHLC")
    return frame


class YFinanceClient:
    is_configured = True  # This public-price provider has no key requirement.

    def __init__(self, cache_dir: Path = CACHE_DIR, fetcher: Callable | None = None,
                 clock: Callable = time.monotonic, sleeper: Callable = time.sleep, request_spacing: float = 5):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fetcher = fetcher
        self.clock, self.sleeper = clock, sleeper
        self.request_spacing = request_spacing
        self.last_request = None
        self.access_denied = False
        self._blocked_status = None
        self.endpoint_availability: dict[str, dict[str, Any]] = {}
        self.raw_frames: dict[str, pd.DataFrame] = {}
        # Anonymous Yahoo cookies/crumbs are kept only for the current process.
        import tempfile
        self._anonymous_cache = tempfile.TemporaryDirectory(prefix="yf-anonymous-", dir=self.cache_dir, ignore_cleanup_errors=True)
        yf.set_tz_cache_location(self._anonymous_cache.name)
        # Intercept the response before yfinance can switch cookie strategies
        # and immediately retry a denied/rate-limited endpoint.
        self.session = new_session()
        sender = self.session.request
        self.session.request = lambda *args, **kwargs: self._guarded_request(sender, *args, **kwargs)
        yf.config.network.retries = 0

    def _throttle(self):
        if self.last_request is not None:
            self.sleeper(max(0, self.request_spacing - (self.clock() - self.last_request)))
        self.last_request = self.clock()

    def _guarded_request(self, sender, *args, **kwargs):
        cooldown = self.cache_dir / 'cooldown.json'
        if self.access_denied:
            raise UpstreamHTTPError(self._blocked_status or 403)
        if cooldown.exists() and datetime.fromisoformat(json.loads(cooldown.read_text())['retry_after']) > datetime.now(timezone.utc):
            raise UpstreamHTTPError(429)
        self._throttle()
        self._blocked_status = None
        response = sender(*args, **kwargs)
        if response.status_code in {401, 403, 429}:
            self._blocked_status = response.status_code
            if response.status_code == 429:
                cooldown.write_text(json.dumps({'retry_after': (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}))
            else:
                self.access_denied = True
            raise UpstreamHTTPError(response.status_code)
        return response

    def _mark(self, endpoint: str, available: bool, reason: str) -> None:
        self.endpoint_availability[endpoint] = {"endpoint": endpoint, "available": available, "reason": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(), "plan_dependent": False, "point_in_time_safe": True}

    def availability_report(self) -> dict:
        return dict(sorted(self.endpoint_availability.items()))

    def cache_path(self, symbol: str) -> Path:
        return self.cache_dir / (hashlib.sha256(symbol.encode()).hexdigest()[:24] + ".json")

    def store_history(self, symbol: str, raw: pd.DataFrame, start: str, end: str) -> None:
        frame = normalize_history(raw)
        body = {"symbol": symbol, "requested_start": start, "requested_end": end,
                "provider": "yfinance", "auto_adjust": False, "rows": [
                    {"date": d.date().isoformat(), **{k: float(v) for k, v in row.items()}} for d, row in frame.iterrows()]}
        target = self.cache_path(symbol)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(body, allow_nan=False))
        temporary.replace(target)

    def _history(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        requested_start, requested_end = start, end
        yahoo_symbol = "^VIX" if symbol in {"I:VIX", "VIX", "^VIX"} else symbol.replace(".", "-")
        path = self.cache_path(yahoo_symbol)
        if path.exists():
            try:
                cache = json.loads(path.read_text())
                if cache.get("auto_adjust") is False and cache["requested_start"] <= start and cache["requested_end"] >= end:
                    frame = pd.DataFrame(cache["rows"]).set_index("date")
                    frame.index = pd.to_datetime(frame.index)
                    frame = normalize_history(frame)
                    self.raw_frames[symbol] = frame
                    self._mark("history/" + symbol, True, "cache_hit_split_adjusted")
                    return frame.loc[start:end]
                if cache.get("auto_adjust") is False:
                    # Keep the full cached history when advancing the end date.
                    start = min(start, cache["requested_start"])
                    end = max(end, cache["requested_end"])
            except (KeyError, ValueError, TypeError):
                self._mark("history/" + symbol, False, "invalid_cache")
        cooldown_path = self.cache_dir / "cooldown.json"
        if self.access_denied:
            raise RuntimeError("access_denied_circuit")
        if cooldown_path.exists():
            if datetime.fromisoformat(json.loads(cooldown_path.read_text())["retry_after"]) > datetime.now(timezone.utc):
                raise RuntimeError("rate_limit_cooldown")
        try:
            if self.fetcher:
                self._throttle()
                raw = self.fetcher(yahoo_symbol, start, end)
            else:
                raw = yf.Ticker(yahoo_symbol, session=self.session).history(start=start, end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat(),
                    interval="1d", auto_adjust=False, actions=True, repair=False, keepna=True, timeout=20, raise_errors=True)
            self.store_history(yahoo_symbol, raw, start, end)
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None) or self._blocked_status
            if isinstance(exc, yf.exceptions.YFRateLimitError) or status == 429:
                cooldown_path.write_text(json.dumps({"retry_after": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}))
                reason = "rate_limit_429_cooldown"
            elif status in {401, 403}:
                self.access_denied = True
                reason = "access_denied_" + str(status)
            else:
                reason = "history_failed_" + type(exc).__name__
            self._mark("history/" + symbol, False, reason)
            raise
        frame = normalize_history(raw)
        self.raw_frames[symbol] = frame
        self._mark("history/" + symbol, True, "live_split_adjusted")
        return frame.loc[requested_start:requested_end]

    def get_aggregates(self, symbol: str, start_date: str, end_date: str, multiplier: int = 1,
                       timespan: str = "day", adjusted: bool = True) -> list[PriceBar]:
        if multiplier != 1 or timespan != "day" or not adjusted:
            raise ValueError("This provider explicitly supports split-adjusted daily research prices only")
        try:
            frame = self._history(symbol, start_date, end_date)
            return [PriceBar(symbol, d.date().isoformat(), r.Open, r.High, r.Low, r.Close, r.Volume,
                vwap=None, source="yfinance.split_adjusted", data_quality_flag="ok") for d, r in frame.iterrows()]
        except Exception:
            return []

    def load_price_history(self, symbols: list[str], start_date: str, end_date: str,
                           allow_synthetic: bool = False, allow_secondary_price_fallback: bool = False,
                           optional_symbols: set[str] | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        optional = optional_symbols if optional_symbols is not None else {"^VIX", "VIX", "I:VIX"}
        frames, missing, optional_missing, defects = {}, [], [], {}
        expected = expected_sessions(start_date, end_date)
        for symbol in symbols:
            bars = self.get_aggregates(symbol, start_date, end_date)
            rows = [{"date": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                     "volume": b.volume, "vwap": b.vwap, "source": b.source, "data_quality_flag": b.data_quality_flag} for b in bars]
            frame = pd.DataFrame(rows)
            if rows:
                frame["date"] = pd.to_datetime(frame["date"])
                frame = frame.set_index("date").reindex(expected)
            else:
                frame = pd.DataFrame(index=expected, columns=["open", "high", "low", "close", "volume", "vwap", "source", "data_quality_flag"])
            bad = frame["close"].isna() | (frame["close"].astype(float) <= 0)
            if bad.any() or not len(expected):
                defects[symbol] = [d.date().isoformat() for d in frame.index[bad]][:10]
                self._mark("history/" + symbol, False, self.endpoint_availability.get("history/" + symbol, {}).get("reason", "") + ";missing_or_stale_sessions")
                (optional_missing if symbol in optional else missing).append(symbol)
                frames[symbol] = frame.iloc[:0]
            else:
                frames[symbol] = frame
        health = {"source": "yfinance.split_adjusted", "ok": not missing, "synthetic": False,
            "fallback_symbols": [], "secondary_source_symbols": [], "optional_missing_symbols": optional_missing,
            "missing_critical_symbols": missing, "date_defects": defects,
            "adjustment_policy": "split_only_price_return", "endpoint_availability": self.availability_report()}
        return frames, health

    def corporate_actions(self, symbol: str, after: str, end: str) -> pd.DataFrame:
        frame = self._history(symbol, after, end)
        return frame.loc[frame.index > pd.Timestamp(after), ["Dividends", "Stock Splits"]]

    def get_market_movers(self, direction: str = "gainers") -> list:
        self._mark("optional_screener/" + direction, False, "disabled_fixed_universe;Yahoo_screener_not_equivalent_to_Massive_snapshot")
        return []

    def get_ticker_profile(self, symbol: str):
        self._mark("optional_profile/" + symbol, False, "profile_hydration_not_enabled")
        return None
