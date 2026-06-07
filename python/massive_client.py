"""Massive/Polygon data client with cache, normalization, and availability metadata."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from config import (
    CACHE_DIR,
    DEFAULT_MASSIVE_BASE_URL,
    MASSIVE_API_KEY_ENVS,
    MASSIVE_BASE_URL_ENV,
    MASSIVE_FORCE_REFRESH_ENV,
)
from data_contracts import EndpointAvailability, PriceBar, TickerProfile, utc_now_iso, write_json


class MassiveClient:
    """Small normalized wrapper around Massive/Polygon endpoints.

    The client never writes API keys to cache. If a key or endpoint is missing,
    the method records availability metadata and returns empty normalized data.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: Path = CACHE_DIR,
        timeout: int = 20,
    ) -> None:
        self.api_key = api_key or self._read_api_key()
        self.base_url = (base_url or os.getenv(MASSIVE_BASE_URL_ENV) or DEFAULT_MASSIVE_BASE_URL).rstrip("/")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.force_refresh = os.getenv(MASSIVE_FORCE_REFRESH_ENV, "").lower() in {"1", "true", "yes", "on"}
        self.endpoint_availability: dict[str, EndpointAvailability] = {}

    @staticmethod
    def _read_api_key() -> str | None:
        for name in MASSIVE_API_KEY_ENVS:
            value = os.getenv(name)
            if value:
                return value
        return None

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    def availability_report(self) -> dict[str, Any]:
        return {name: asdict(value) for name, value in sorted(self.endpoint_availability.items())}

    def write_availability_report(self, path: Path) -> None:
        write_json(path, self.availability_report())

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        safe_params = {k: v for k, v in params.items() if k != "apiKey"}
        raw = json.dumps({"endpoint": endpoint, "params": safe_params}, sort_keys=True)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
        name = endpoint.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        return self.cache_dir / f"{name}_{digest}.json"

    def _mark(
        self,
        endpoint: str,
        available: bool,
        reason: str,
        plan_dependent: bool = False,
        point_in_time_safe: bool = True,
    ) -> None:
        self.endpoint_availability[endpoint] = EndpointAvailability(
            endpoint=endpoint,
            available=available,
            checked_at=utc_now_iso(),
            reason=reason,
            plan_dependent=plan_dependent,
            point_in_time_safe=point_in_time_safe,
        )

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        plan_dependent: bool = False,
        point_in_time_safe: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        params = dict(params or {})
        if not self.api_key:
            self._mark(endpoint, False, "missing_api_key", plan_dependent, point_in_time_safe)
            return {"status": "UNAVAILABLE", "results": []}

        cache_path = self._cache_path(endpoint, params)
        if use_cache and not self.force_refresh and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                self._mark(endpoint, True, "cache_hit", plan_dependent, point_in_time_safe)
                return cached
            except json.JSONDecodeError:
                pass

        url = f"{self.base_url}{endpoint}"
        request_params = {**params, "apiKey": self.api_key}
        try:
            response = requests.get(url, params=request_params, timeout=self.timeout)
            if response.status_code in (401, 403):
                self._mark(endpoint, False, f"auth_or_plan_error_{response.status_code}", plan_dependent, point_in_time_safe)
                return {"status": "UNAVAILABLE", "results": [], "error": "auth_or_plan_error"}
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self._mark(endpoint, False, f"request_failed:{type(exc).__name__}", plan_dependent, point_in_time_safe)
            return {"status": "UNAVAILABLE", "results": [], "error": type(exc).__name__}

        self._mark(endpoint, True, payload.get("status", "ok"), plan_dependent, point_in_time_safe)
        cache_payload = dict(payload)
        cache_payload.pop("request_id", None)
        cache_path.write_text(json.dumps(cache_payload, indent=2, sort_keys=True) + "\n")
        return payload

    def get_aggregates(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        multiplier: int = 1,
        timespan: str = "day",
        adjusted: bool = True,
    ) -> list[PriceBar]:
        endpoint = f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{start_date}/{end_date}"
        payload = self._request(endpoint, {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000})
        bars: list[PriceBar] = []
        for row in payload.get("results", []) or []:
            ts = row.get("t")
            bar_date = datetime.fromtimestamp(ts / 1000, timezone.utc).date().isoformat() if ts else start_date
            bars.append(
                PriceBar(
                    symbol=symbol,
                    date=bar_date,
                    open=float(row.get("o", 0.0)),
                    high=float(row.get("h", 0.0)),
                    low=float(row.get("l", 0.0)),
                    close=float(row.get("c", 0.0)),
                    volume=float(row.get("v", 0.0)),
                    vwap=float(row["vw"]) if row.get("vw") is not None else None,
                    source="massive",
                    data_quality_flag="ok",
                )
            )
        return bars

    def get_ticker_profile(self, symbol: str) -> TickerProfile | None:
        endpoint = f"/v3/reference/tickers/{symbol}"
        payload = self._request(endpoint, {})
        result = payload.get("results") or {}
        if not result:
            return None
        return TickerProfile(
            symbol=symbol,
            asset_type="etf" if result.get("type") == "ETF" else "stock",
            name=result.get("name"),
            sector=result.get("sic_description") or result.get("sector"),
            industry=result.get("locale"),
            market_cap=_safe_float(result.get("market_cap")),
            exchange=result.get("primary_exchange"),
            currency=result.get("currency_name", "USD"),
            source="massive",
            data_quality_flag="ok",
        )

    def list_tickers(self, market: str = "stocks", active: bool = True, limit: int = 1000) -> list[dict[str, Any]]:
        endpoint = "/v3/reference/tickers"
        payload = self._request(endpoint, {"market": market, "active": str(active).lower(), "limit": limit})
        return list(payload.get("results", []) or [])

    def get_ticker_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        endpoint = "/v2/reference/news"
        payload = self._request(endpoint, {"ticker": symbol, "limit": limit, "order": "desc"}, plan_dependent=True)
        return list(payload.get("results", []) or [])

    def get_financial_snapshot(self, symbol: str, as_of: str) -> dict[str, Any]:
        endpoint = "/vX/reference/financials"
        payload = self._request(
            endpoint,
            {"ticker": symbol, "filing_date.lte": as_of, "limit": 1, "order": "desc", "sort": "filing_date"},
            plan_dependent=True,
            point_in_time_safe=False,
        )
        rows = payload.get("results", []) or []
        if not rows:
            return {"symbol": symbol, "point_in_time_available": False, "data_quality_flag": "unavailable"}
        row = rows[0]
        return {"symbol": symbol, "point_in_time_available": True, "data_quality_flag": "ok", "raw": row}

    def get_analyst_snapshot(self, symbol: str, as_of: str) -> dict[str, Any]:
        endpoint = "/v2/reference/analysts"
        self._mark(endpoint, False, "not_confirmed_by_massive_response", plan_dependent=True, point_in_time_safe=False)
        return {"symbol": symbol, "as_of": as_of, "point_in_time_available": False, "data_quality_flag": "unavailable"}

    def get_earnings_calendar(self, symbol: str, as_of: str) -> dict[str, Any]:
        endpoint = "/vX/reference/earnings"
        self._mark(endpoint, False, "not_confirmed_by_massive_response", plan_dependent=True, point_in_time_safe=False)
        return {"symbol": symbol, "as_of": as_of, "point_in_time_available": False, "data_quality_flag": "unavailable"}

    def get_market_movers(self, direction: str = "gainers") -> list[dict[str, Any]]:
        endpoint = f"/v2/snapshot/locale/us/markets/stocks/{direction}"
        payload = self._request(endpoint, {}, plan_dependent=True)
        rows = payload.get("tickers", []) or payload.get("results", []) or []
        return list(rows)

    def load_price_history(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        allow_synthetic: bool = True,
        allow_secondary_price_fallback: bool = False,
        optional_symbols: set[str] | None = None,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        optional_symbols = optional_symbols or {"^VIX", "VIX", "I:VIX"}
        frames: dict[str, pd.DataFrame] = {}
        fallback_symbols: list[str] = []
        optional_missing_symbols: list[str] = []
        secondary_source_symbols: list[str] = []
        for symbol in symbols:
            bars = self.get_aggregates(symbol, start_date, end_date) if self.has_key else []
            if not bars and self.has_key and symbol in {"^VIX", "VIX", "I:VIX"}:
                bars = yahoo_vix_bars("^VIX", start_date, end_date)
                if bars:
                    frames[symbol] = bars_to_frame(bars)
                    secondary_source_symbols.append(f"{symbol}:yahoo")
                    continue
            if self.has_key and allow_secondary_price_fallback and _bars_start_after(bars, start_date):
                secondary_bars = yahoo_price_bars(symbol, start_date, end_date)
                if secondary_bars:
                    bars = merge_price_bars(primary=bars, secondary=secondary_bars)
                    secondary_source_symbols.append(f"{symbol}:yahoo_price")
            if not bars and self.has_key and symbol in optional_symbols:
                frames[symbol] = bars_to_frame([])
                optional_missing_symbols.append(symbol)
                continue
            if not bars and allow_synthetic:
                bars = synthetic_price_bars(symbol, start_date, end_date)
                fallback_symbols.append(symbol)
            frames[symbol] = bars_to_frame(bars)

        critical_symbols = [symbol for symbol in (symbols or []) if symbol not in optional_symbols]
        missing_critical = [
            symbol
            for symbol in critical_symbols
            if symbol not in frames or frames[symbol].empty
        ]
        health = {
            "source": _health_source(self.has_key, fallback_symbols, secondary_source_symbols),
            "ok": self.has_key and not fallback_symbols and not missing_critical,
            "synthetic": bool(fallback_symbols),
            "fallback_symbols": fallback_symbols[:50],
            "optional_missing_symbols": optional_missing_symbols[:50],
            "secondary_source_symbols": secondary_source_symbols[:50],
            "missing_critical_symbols": missing_critical[:50],
            "endpoint_availability": self.availability_report(),
        }
        return frames, health


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def bars_to_frame(bars: list[PriceBar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "vwap", "source", "data_quality_flag"])
    rows = [asdict(bar) for bar in bars]
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    return frame[["open", "high", "low", "close", "volume", "vwap", "source", "data_quality_flag"]]


def _bars_start_after(bars: list[PriceBar], requested_start: str, tolerance_days: int = 30) -> bool:
    if not bars:
        return True
    first = min(pd.Timestamp(bar.date) for bar in bars)
    return first > pd.Timestamp(requested_start) + pd.Timedelta(days=tolerance_days)


def merge_price_bars(primary: list[PriceBar], secondary: list[PriceBar]) -> list[PriceBar]:
    """Merge secondary historical bars with primary data, preferring Massive overlap."""

    by_date = {bar.date: bar for bar in secondary}
    by_date.update({bar.date: bar for bar in primary})
    return [by_date[key] for key in sorted(by_date)]


def _health_source(has_key: bool, fallback_symbols: list[str], secondary_source_symbols: list[str]) -> str:
    if fallback_symbols:
        return "fallback.synthetic"
    if has_key and secondary_source_symbols:
        return "massive+secondary"
    return "massive" if has_key else "unavailable"


def synthetic_price_bars(symbol: str, start_date: str, end_date: str) -> list[PriceBar]:
    """Deterministic fallback bars for local tests and dashboard development.

    These are explicitly marked as synthetic and must trigger a BLACK risk gate.
    """

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    dates = pd.bdate_range(start, end)
    if dates.empty:
        return []

    seed = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    drift = 0.00018 + (seed % 17) / 100000
    vol = 0.010 + (seed % 11) / 1000
    if symbol in ("SGOV", "SHY"):
        drift, vol = 0.00008, 0.001
    if symbol == "^VIX":
        drift, vol = 0.0, 0.035

    base = 30 + (seed % 250)
    if symbol == "^VIX":
        base = 18
    shocks = rng.normal(drift, vol, len(dates))
    close = base * np.exp(np.cumsum(shocks))
    high = close * (1 + np.abs(rng.normal(0.003, vol / 3, len(dates))))
    low = close * (1 - np.abs(rng.normal(0.003, vol / 3, len(dates))))
    open_ = close * (1 + rng.normal(0, vol / 4, len(dates)))
    volume = rng.integers(500_000, 8_000_000, len(dates)).astype(float)
    if symbol in ("SPY", "QQQ"):
        volume *= 10

    bars = []
    for idx, dt in enumerate(dates):
        bars.append(
            PriceBar(
                symbol=symbol,
                date=dt.date().isoformat(),
                open=float(max(0.1, open_[idx])),
                high=float(max(open_[idx], high[idx], close[idx])),
                low=float(max(0.1, min(open_[idx], low[idx], close[idx]))),
                close=float(max(0.1, close[idx])),
                volume=float(volume[idx]),
                vwap=float(close[idx]),
                source="fallback.synthetic",
                data_quality_flag="synthetic",
            )
        )
    return bars


def yahoo_vix_bars(symbol: str, start_date: str, end_date: str) -> list[PriceBar]:
    """Fetch VIX daily bars from Yahoo when index data is unavailable in Massive."""

    return yahoo_price_bars(symbol, start_date, end_date, source="yahoo.vix")


def yahoo_price_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    source: str = "yahoo.price",
) -> list[PriceBar]:
    """Fetch adjusted daily bars from Yahoo as an explicitly marked secondary source."""

    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    try:
        response = requests.get(
            url,
            params={
                "period1": int(start.timestamp()),
                "period2": int(end.timestamp()),
                "interval": "1d",
                "events": "history",
                "includeAdjustedClose": "true",
            },
            headers={"User-Agent": "Mozilla/5.0 Greenlight/2.0"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            return []
        timestamps = result.get("timestamp") or []
        quote_rows = (result.get("indicators", {}).get("quote") or [{}])[0]
        adjclose_rows = (result.get("indicators", {}).get("adjclose") or [{}])[0]
    except Exception:
        return []

    bars = []
    opens = quote_rows.get("open") or []
    highs = quote_rows.get("high") or []
    lows = quote_rows.get("low") or []
    closes = quote_rows.get("close") or []
    volumes = quote_rows.get("volume") or []
    adjcloses = adjclose_rows.get("adjclose") or []
    for idx, ts in enumerate(timestamps):
        close = _list_value(closes, idx)
        if close is None:
            continue
        adjclose = _list_value(adjcloses, idx, close)
        adjustment = float(adjclose) / float(close) if close else 1.0
        open_ = _list_value(opens, idx, close)
        high = _list_value(highs, idx, close)
        low = _list_value(lows, idx, close)
        volume = _list_value(volumes, idx, 0.0)
        adjusted_open = float(open_) * adjustment
        adjusted_high = float(high) * adjustment
        adjusted_low = float(low) * adjustment
        adjusted_close = float(adjclose)
        bars.append(
            PriceBar(
                symbol=symbol,
                date=datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                open=adjusted_open,
                high=adjusted_high,
                low=adjusted_low,
                close=adjusted_close,
                volume=float(volume or 0.0),
                vwap=adjusted_close,
                source=source,
                data_quality_flag="secondary_source",
            )
        )
    return bars


def _list_value(values: list[Any], idx: int, default: Any = None) -> Any:
    if idx >= len(values):
        return default
    value = values[idx]
    return default if value is None else value
