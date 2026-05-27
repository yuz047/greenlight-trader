"""Live opportunity-list builder.

Massive is optional. With ``MASSIVE_API_KEY`` or ``POLYGON_API_KEY`` set, the
daily run enriches the local technical ranker with:

- top gainers from Massive snapshots,
- Massive financial ratios for valuation/quality,
- Benzinga consensus ratings and price targets when the plan includes them.

Without the key or paid datasets, the module still maintains a broad live list
from local OHLCV so the allocator is not limited to Mag7.
"""
from __future__ import annotations

import math
import os
import sys
import time
from typing import Dict, Iterable, List

import pandas as pd
import requests

from config import (
    CORE_UNIVERSE,
    DISCOVERY_UNIVERSE,
    MASSIVE_BASE_URL_ENV,
    MASSIVE_KEY_ENV,
    POLYGON_KEY_ENV,
    WATCHLIST,
)


def _log(msg: str) -> None:
    print(f"[candidates] {msg}", file=sys.stderr, flush=True)


def _num(value, default=None):
    try:
        if value is None:
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _clip(value: float | None, lo: float, hi: float, default: float = 0.0) -> float:
    if value is None or not math.isfinite(value):
        return default
    return max(lo, min(hi, value))


class MassiveClient:
    def __init__(self) -> None:
        self.api_key = os.environ.get(MASSIVE_KEY_ENV) or os.environ.get(POLYGON_KEY_ENV)
        self.base_url = os.environ.get(MASSIVE_BASE_URL_ENV, "https://api.massive.com").rstrip("/")
        self.session = requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def get(self, path: str, params: dict | None = None) -> dict | None:
        if not self.api_key:
            return None
        params = dict(params or {})
        params["apiKey"] = self.api_key
        try:
            resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=15)
            if resp.status_code >= 400:
                _log(f"Massive {path}: HTTP {resp.status_code} {resp.text[:120]}")
                return None
            return resp.json()
        except requests.RequestException as exc:
            _log(f"Massive {path}: {exc}")
            return None

    def top_gainers(self) -> list[dict]:
        data = self.get(
            "/v2/snapshot/locale/us/markets/stocks/gainers",
            {"include_otc": "false"},
        )
        return list((data or {}).get("tickers") or (data or {}).get("results") or [])

    def ratios(self, ticker: str) -> dict:
        data = self.get(
            "/stocks/financials/v1/ratios",
            {"ticker": ticker, "limit": 1, "sort": "date.desc"},
        )
        results = (data or {}).get("results") or []
        return results[0] if results else {}

    def consensus(self, ticker: str) -> dict:
        data = self.get(
            f"/benzinga/v1/consensus-ratings/{ticker}",
            {"limit": 1},
        )
        results = (data or {}).get("results") or []
        return results[0] if results else {}


def discover_symbols() -> list[str]:
    """Return the broad daily universe, with Massive movers added when available."""
    symbols = set(CORE_UNIVERSE + DISCOVERY_UNIVERSE)
    client = MassiveClient()
    if client.enabled:
        for row in client.top_gainers()[:20]:
            sym = row.get("ticker") or row.get("T") or row.get("symbol")
            if sym and isinstance(sym, str) and sym.isalpha() and len(sym) <= 5:
                symbols.add(sym.upper())
        _log(f"Massive discovery enabled; tracking {len(symbols)} symbols")
    else:
        _log("Massive discovery disabled; set MASSIVE_API_KEY or POLYGON_API_KEY")
    return sorted(symbols)


def _ret(close: pd.Series, window: int) -> float | None:
    if len(close) < window + 1:
        return None
    start = _num(close.iloc[-window - 1])
    end = _num(close.iloc[-1])
    if not start or not end or start <= 0:
        return None
    return end / start - 1.0


def _technical_research(symbol: str, df: pd.DataFrame, spy: pd.DataFrame | None) -> dict:
    close = df["close"] if "close" in df else pd.Series(dtype=float)
    volume = df["volume"] if "volume" in df else pd.Series(dtype=float)
    price = _num(close.iloc[-1] if len(close) else None)
    ret20 = _ret(close, 20)
    ret63 = _ret(close, 63)
    ret126 = _ret(close, 126)
    spy_ret63 = _ret(spy["close"], 63) if spy is not None and "close" in spy else 0.0
    avg_vol = volume.tail(20).mean() if len(volume) >= 20 else None
    vol_ratio = _num(volume.iloc[-1] / avg_vol if avg_vol and avg_vol > 0 else None, 1.0)
    sma50 = _num(df["sma50"].iloc[-1] if "sma50" in df and len(df) else None)
    extension = price / sma50 if price and sma50 and sma50 > 0 else None

    rel63 = (ret63 or 0.0) - (spy_ret63 or 0.0)
    reward = (
        0.35 * _clip(rel63 / 0.18, -1, 1)
        + 0.30 * _clip((ret126 or 0.0) / 0.30, -1, 1)
        + 0.20 * _clip((ret20 or 0.0) / 0.12, -1, 1)
        + 0.15 * _clip((vol_ratio or 1.0) - 1.0, -1, 1)
    )
    if extension and extension > 1.22:
        reward -= 0.25

    return {
        "symbol": symbol,
        "price": price,
        "return_20d": ret20,
        "return_63d": ret63,
        "return_126d": ret126,
        "relative_strength_63d": rel63,
        "volume_ratio_20d": vol_ratio,
        "extension_sma50": extension,
        "market_reward_score": round(_clip(reward, -1, 1), 4),
        "source": "local",
    }


def _score_ratios(row: dict) -> dict:
    pe = _num(row.get("price_to_earnings"))
    ps = _num(row.get("price_to_sales"))
    fcf = _num(row.get("free_cash_flow"))
    roe = _num(row.get("return_on_equity"))
    debt = _num(row.get("debt_to_equity"))

    valuation = 0.0
    if pe is not None:
        valuation += 0.35 if 8 <= pe <= 45 else (-0.2 if pe > 80 else 0.05)
    if ps is not None:
        valuation += 0.30 if ps <= 12 else (-0.25 if ps > 25 else 0.05)
    if fcf is not None:
        valuation += 0.20 if fcf > 0 else -0.20

    quality = 0.0
    if roe is not None:
        quality += 0.35 if roe >= 0.12 else (-0.15 if roe < 0 else 0.0)
    if debt is not None:
        quality += 0.15 if debt <= 1.5 else (-0.20 if debt > 4 else 0.0)
    if fcf is not None and fcf > 0:
        quality += 0.20

    red_flag = (ps is not None and ps > 35) or (pe is not None and pe > 120) or (fcf is not None and fcf < 0)
    return {
        "market_cap": _num(row.get("market_cap")),
        "price_to_earnings": pe,
        "price_to_sales": ps,
        "free_cash_flow": fcf,
        "return_on_equity": roe,
        "debt_to_equity": debt,
        "valuation_health_score": round(_clip(valuation, -1, 1), 4),
        "quality_health_score": round(_clip(quality, -1, 1), 4),
        "valuation_red_flag": bool(red_flag),
    }


def _score_consensus(row: dict, price: float | None) -> dict:
    target = _num(row.get("consensus_price_target"))
    buy = int(row.get("buy_ratings") or 0) + int(row.get("strong_buy_ratings") or 0)
    hold = int(row.get("hold_ratings") or 0)
    sell = int(row.get("sell_ratings") or 0) + int(row.get("strong_sell_ratings") or 0)
    total = buy + hold + sell
    upside = target / price - 1.0 if target and price and price > 0 else None
    buy_share = buy / total if total else None
    score = 0.0
    if upside is not None:
        score += 0.55 * _clip(upside / 0.25, -1, 1)
    if buy_share is not None:
        score += 0.35 * _clip((buy_share - 0.45) / 0.35, -1, 1)
    if sell > 0 and total and sell / total > 0.20:
        score -= 0.25
    return {
        "consensus_price_target": target,
        "consensus_upside": upside,
        "buy_ratings": buy,
        "hold_ratings": hold,
        "sell_ratings": sell,
        "ratings_contributors": int(row.get("ratings_contributors") or total or 0),
        "forecast_health_score": round(_clip(score, -1, 1), 4),
    }


def build_candidate_research(enriched: Dict[str, pd.DataFrame], limit: int = 40) -> list[dict]:
    """Build and return the daily opportunity list."""
    spy = enriched.get("SPY")
    rows = [
        _technical_research(sym, df, spy)
        for sym, df in enriched.items()
        if (
            sym not in {"SPY", "QQQ", "SHY", "^VIX"}
            and df is not None
            and not df.empty
            and not bool(df.get("synthetic", pd.Series([False])).iloc[-1])
        )
    ]
    rows.sort(key=lambda row: row.get("market_reward_score", 0), reverse=True)

    client = MassiveClient()
    if client.enabled:
        candidate_symbols = [r["symbol"] for r in rows[:limit]]
        for i, sym in enumerate(candidate_symbols, start=1):
            ratios = client.ratios(sym)
            if ratios:
                rows_by_symbol = next(r for r in rows if r["symbol"] == sym)
                rows_by_symbol.update(_score_ratios(ratios))
                rows_by_symbol["source"] = "massive"
            consensus = client.consensus(sym)
            if consensus:
                rows_by_symbol = next(r for r in rows if r["symbol"] == sym)
                rows_by_symbol.update(_score_consensus(consensus, rows_by_symbol.get("price")))
                rows_by_symbol["source"] = "massive+benzinga"
            if i % 8 == 0:
                time.sleep(0.25)

    for row in rows:
        row.setdefault("valuation_health_score", 0.0)
        row.setdefault("quality_health_score", 0.0)
        row.setdefault("forecast_health_score", 0.0)
        row.setdefault("valuation_red_flag", False)
        row["opportunity_score"] = round(
            0.46 * row.get("market_reward_score", 0.0)
            + 0.22 * row.get("forecast_health_score", 0.0)
            + 0.18 * row.get("quality_health_score", 0.0)
            + 0.14 * row.get("valuation_health_score", 0.0),
            4,
        )
        row["healthy_prediction"] = (
            row.get("forecast_health_score", 0.0) >= 0.15
            and row.get("valuation_health_score", 0.0) >= -0.25
            and not row.get("valuation_red_flag", False)
        )

    rows.sort(key=lambda row: row.get("opportunity_score", 0.0), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows[:limit]


def attach_research(enriched: Dict[str, pd.DataFrame], research_rows: Iterable[dict]) -> None:
    by_symbol = {row["symbol"]: row for row in research_rows}
    for sym, row in by_symbol.items():
        if sym in enriched:
            enriched[sym].attrs["candidate_research"] = row
