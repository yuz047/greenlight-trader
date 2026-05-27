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
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
import requests

from config import (
    CORE_UNIVERSE,
    DISCOVERY_UNIVERSE,
    MEGA_CAP_UNIVERSE,
    MASSIVE_BASE_URL_ENV,
    MASSIVE_KEY_ENV,
    POLYGON_KEY_ENV,
    WATCHLIST,
)


SHARED_MASSIVE_ENV = Path(__file__).resolve().parents[3] / "high-risk-symbols" / ".env.massive"
SHARED_HIGH_RISK_SYMBOLS = Path(__file__).resolve().parents[3] / "high-risk-symbols" / "data" / "symbols.json"
_HIGH_RISK_CACHE: dict[str, dict] | None = None


def _log(msg: str) -> None:
    print(f"[candidates] {msg}", file=sys.stderr, flush=True)


def _load_shared_massive_env() -> None:
    """Reuse the high-risk-symbols Massive env file without copying secrets."""
    if os.environ.get(MASSIVE_KEY_ENV) or os.environ.get(POLYGON_KEY_ENV):
        return
    if not SHARED_MASSIVE_ENV.exists():
        return
    try:
        for line in SHARED_MASSIVE_ENV.read_text().splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key in {MASSIVE_KEY_ENV, POLYGON_KEY_ENV, MASSIVE_BASE_URL_ENV} and value:
                os.environ.setdefault(key, value)
        if os.environ.get(MASSIVE_KEY_ENV) or os.environ.get(POLYGON_KEY_ENV):
            _log(f"loaded Massive credentials from shared env: {SHARED_MASSIVE_ENV}")
    except OSError as exc:
        _log(f"could not read shared Massive env {SHARED_MASSIVE_ENV}: {exc}")


def _high_risk_cache() -> dict[str, dict]:
    global _HIGH_RISK_CACHE
    if _HIGH_RISK_CACHE is not None:
        return _HIGH_RISK_CACHE
    try:
        rows = json.loads(SHARED_HIGH_RISK_SYMBOLS.read_text()) if SHARED_HIGH_RISK_SYMBOLS.exists() else []
    except (OSError, json.JSONDecodeError):
        rows = []
    _HIGH_RISK_CACHE = {str(row.get("symbol", "")).upper(): row for row in rows if row.get("symbol")}
    return _HIGH_RISK_CACHE


def _tradable_massive_discovery(sym: str) -> bool:
    """Filter Massive movers through the high-risk-symbols database.

    The high-risk project keeps the broad security master. GreenLight should use
    that feed for discovery, but avoid warrants/rights and pump-risk microcaps as
    buy candidates.
    """
    if not sym or not sym.isalpha() or len(sym) > 5:
        return False
    row = _high_risk_cache().get(sym)
    if not row:
        return False
    flags = row.get("flags") or {}
    if row.get("rule_high_risk") or row.get("pca_high_risk") or int(row.get("hit_count") or 0) >= 3:
        return False
    if bool(flags.get("mcap_below")) and bool(flags.get("price_below")):
        return False
    mcap_musd = _num(row.get("mcap_musd"))
    return mcap_musd is None or mcap_musd >= 500.0


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
        _load_shared_massive_env()
        self.api_key = os.environ.get(MASSIVE_KEY_ENV) or os.environ.get(POLYGON_KEY_ENV)
        self.base_url = os.environ.get(MASSIVE_BASE_URL_ENV, "https://api.massive.com").rstrip("/")
        self.session = requests.Session()
        self.disabled_products: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _product(self, path: str) -> str | None:
        if path.startswith("/stocks/financials/"):
            return "financials"
        if path.startswith("/benzinga/"):
            return "benzinga"
        return None

    def get(self, path: str, params: dict | None = None) -> dict | None:
        if not self.api_key:
            return None
        product = self._product(path)
        if product and product in self.disabled_products:
            return None
        params = dict(params or {})
        params["apiKey"] = self.api_key
        try:
            resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=15)
            if resp.status_code >= 400:
                if resp.status_code == 403 and "NOT_AUTHORIZED" in resp.text and product:
                    self.disabled_products.add(product)
                    _log(f"Massive {product} endpoint not entitled; skipping for this run")
                    return None
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
    symbols = set(CORE_UNIVERSE + MEGA_CAP_UNIVERSE + DISCOVERY_UNIVERSE)
    client = MassiveClient()
    if client.enabled:
        for row in client.top_gainers()[:20]:
            sym = row.get("ticker") or row.get("T") or row.get("symbol")
            if sym and isinstance(sym, str):
                sym = sym.upper()
                if _tradable_massive_discovery(sym):
                    symbols.add(sym)
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


def _rolling_percentile(series: pd.Series, value: float | None, window: int = 252) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    sample = series.dropna().tail(window)
    if sample.empty:
        return None
    return float((sample <= value).mean())


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
    sma200 = _num(df["sma200"].iloc[-1] if "sma200" in df and len(df) else None)
    rsi14 = _num(df["rsi14"].iloc[-1] if "rsi14" in df and len(df) else None)
    atr14 = _num(df["atr14"].iloc[-1] if "atr14" in df and len(df) else None)
    extension = price / sma50 if price and sma50 and sma50 > 0 else None
    trend_vs_200 = price / sma200 - 1.0 if price and sma200 and sma200 > 0 else None
    high20 = _num(df["high20"].iloc[-1] if "high20" in df and len(df) else None)
    high63 = _num(close.tail(63).max() if len(close) >= 63 else None)
    pullback_20d = price / high20 - 1.0 if price and high20 and high20 > 0 else None
    pullback_63d = price / high63 - 1.0 if price and high63 and high63 > 0 else None
    atr_pct = atr14 / price if atr14 and price and price > 0 else None
    ret_series = close.pct_change()
    vol20 = _num(ret_series.tail(20).std())
    vol_pctile = _rolling_percentile(ret_series.rolling(20).std(), vol20)

    rel63 = (ret63 or 0.0) - (spy_ret63 or 0.0)

    trend_score = (
        0.45 * _clip((trend_vs_200 or 0.0) / 0.35, -1, 1)
        + 0.35 * _clip(rel63 / 0.20, -1, 1)
        + 0.20 * _clip((ret126 or 0.0) / 0.45, -1, 1)
    )
    breakout_score = (
        0.40 * _clip((ret20 or 0.0) / 0.16, -1, 1)
        + 0.30 * _clip((vol_ratio or 1.0) - 1.0, -1, 1)
        + 0.30 * _clip((pullback_20d or 0.0) / 0.02 + 1.0, 0, 1)
    )
    pullback_score = (
        0.45 * _clip(rel63 / 0.20, -1, 1)
        + 0.35 * (1.0 if pullback_63d is not None and -0.14 <= pullback_63d <= -0.025 else 0.0)
        + 0.20 * _clip((50.0 - abs((rsi14 or 50.0) - 50.0)) / 50.0, 0, 1)
    )
    volume_score = _clip((vol_ratio or 1.0) - 1.0, -1, 1)
    risk_score = (
        -0.30 if extension and extension > 1.22 else 0.0
    ) + (
        -0.25 if rsi14 and rsi14 > 78 else 0.0
    ) + (
        -0.20 if vol_pctile and vol_pctile > 0.90 else 0.0
    )
    if breakout_score >= pullback_score and breakout_score >= 0.35:
        setup = "breakout"
        setup_score = breakout_score
    elif pullback_score >= 0.30:
        setup = "pullback"
        setup_score = pullback_score
    else:
        setup = "trend"
        setup_score = trend_score
    technical_score = _clip(
        0.42 * trend_score
        + 0.24 * breakout_score
        + 0.18 * pullback_score
        + 0.10 * volume_score
        + 0.06 * setup_score
        + risk_score,
        -1,
        1,
    )

    return {
        "symbol": symbol,
        "price": price,
        "return_20d": ret20,
        "return_63d": ret63,
        "return_126d": ret126,
        "relative_strength_63d": rel63,
        "volume_ratio_20d": vol_ratio,
        "extension_sma50": extension,
        "trend_vs_200d": trend_vs_200,
        "rsi14": rsi14,
        "atr_pct": atr_pct,
        "pullback_20d": pullback_20d,
        "pullback_63d": pullback_63d,
        "trend_score": round(_clip(trend_score, -1, 1), 4),
        "breakout_score": round(_clip(breakout_score, -1, 1), 4),
        "pullback_score": round(_clip(pullback_score, -1, 1), 4),
        "volume_score": round(volume_score, 4),
        "technical_score": round(technical_score, 4),
        "market_reward_score": round(technical_score, 4),
        "setup": setup,
        "source": "local",
    }


def _pick(row: dict, *keys):
    for key in keys:
        value = row
        ok = True
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                ok = False
                break
        if ok and value is not None:
            return value
    return None


def _score_ratios(row: dict) -> dict:
    pe = _num(_pick(row, "price_to_earnings", "valuation.price_to_earnings", "ratios.price_to_earnings", "pe_ratio"))
    ps = _num(_pick(row, "price_to_sales", "valuation.price_to_sales", "ratios.price_to_sales", "ps_ratio"))
    fcf = _num(_pick(row, "free_cash_flow", "cash_flow.free_cash_flow", "cash_flow_statement.free_cash_flow"))
    roe = _num(_pick(row, "return_on_equity", "profitability.return_on_equity", "ratios.return_on_equity", "roe"))
    debt = _num(_pick(row, "debt_to_equity", "leverage.debt_to_equity", "ratios.debt_to_equity"))

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
    target = _num(_pick(row, "consensus_price_target", "price_target.consensus", "avg_price_target"))
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


def _yfinance_fallback(symbol: str, price: float | None) -> dict:
    """Fill forecast/valuation fields when Massive partner data is absent.

    This keeps the dashboard informative locally. Massive remains the preferred
    source when the API key and paid datasets are available.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).get_info()
    except Exception as exc:
        _log(f"yfinance fundamentals {symbol}: {exc}")
        return {}
    target = _num(info.get("targetMeanPrice"))
    upside = target / price - 1.0 if target and price and price > 0 else None
    recommendation = _num(info.get("recommendationMean"))
    buy_score = None
    if recommendation is not None:
        # Yahoo scale is generally 1 strong buy to 5 sell.
        buy_score = _clip((3.0 - recommendation) / 2.0, -1, 1)
    forecast = 0.0
    if upside is not None:
        forecast += 0.65 * _clip(upside / 0.25, -1, 1)
    if buy_score is not None:
        forecast += 0.25 * buy_score
    out = {
        "consensus_price_target": target,
        "consensus_upside": upside,
        "forecast_health_score": round(_clip(forecast, -1, 1), 4),
        "price_to_earnings": _num(info.get("forwardPE") or info.get("trailingPE")),
        "price_to_sales": _num(info.get("priceToSalesTrailing12Months")),
        "return_on_equity": _num(info.get("returnOnEquity")),
        "debt_to_equity": _num(info.get("debtToEquity")),
    }
    ratio_scores = _score_ratios(out)
    out.update({k: v for k, v in ratio_scores.items() if v is not None})
    out["source"] = "yfinance+local"
    return out


def build_candidate_research(enriched: Dict[str, pd.DataFrame], limit: int = 80) -> list[dict]:
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
    protected_symbols = set(CORE_UNIVERSE + MEGA_CAP_UNIVERSE + ["SNDK"])
    for row in rows:
        if row["symbol"] in protected_symbols:
            row["choice_group"] = "mega-cap/watchlist" if row["symbol"] in MEGA_CAP_UNIVERSE else "core/watchlist"
            row["must_review"] = True
        else:
            row["choice_group"] = "discovery"
            row["must_review"] = False

    rows.sort(key=lambda row: row.get("market_reward_score", 0), reverse=True)

    client = MassiveClient()
    if client.enabled:
        candidate_symbols = sorted({r["symbol"] for r in rows[:limit]} | {r["symbol"] for r in rows if r["symbol"] in protected_symbols})
        for i, sym in enumerate(candidate_symbols, start=1):
            ratios = client.ratios(sym)
            rows_by_symbol = next(r for r in rows if r["symbol"] == sym)
            if ratios:
                rows_by_symbol.update(_score_ratios(ratios))
                rows_by_symbol["source"] = "massive"
            consensus = client.consensus(sym)
            if consensus:
                rows_by_symbol.update(_score_consensus(consensus, rows_by_symbol.get("price")))
                rows_by_symbol["source"] = "massive+benzinga"
            if i % 8 == 0:
                time.sleep(0.25)

    fallback_symbols = sorted({
        r["symbol"] for r in rows
        if r.get("forecast_health_score") is None
        or r.get("consensus_price_target") is None
        or r.get("price_to_earnings") is None
    } & protected_symbols)
    fallback_symbols += [
        r["symbol"] for r in rows
        if r["symbol"] not in set(fallback_symbols)
        and (
            r.get("forecast_health_score") is None
            or r.get("consensus_price_target") is None
            or r.get("price_to_earnings") is None
        )
    ][: max(0, min(limit, 40) - len(fallback_symbols))]
    for i, sym in enumerate(fallback_symbols, start=1):
        row = next(r for r in rows if r["symbol"] == sym)
        fallback = _yfinance_fallback(sym, row.get("price"))
        if fallback:
            filled_from_fallback = False
            for key, value in fallback.items():
                if key == "source" or value is None:
                    continue
                if row.get(key) in (None, 0.0):
                    row[key] = value
                    filled_from_fallback = True
            if filled_from_fallback:
                source = str(row.get("source") or "local")
                row["source"] = "yfinance+local" if source == "local" else f"{source}+yfinance"
        if i % 8 == 0:
            time.sleep(0.25)

    for row in rows:
        row.setdefault("valuation_health_score", 0.0)
        row.setdefault("quality_health_score", 0.0)
        row.setdefault("forecast_health_score", 0.0)
        row.setdefault("valuation_red_flag", False)
        row["opportunity_score"] = round(
            0.34 * row.get("technical_score", row.get("market_reward_score", 0.0))
            + 0.22 * row.get("market_reward_score", 0.0)
            + 0.20 * row.get("forecast_health_score", 0.0)
            + 0.14 * row.get("quality_health_score", 0.0)
            + 0.10 * row.get("valuation_health_score", 0.0),
            4,
        )
        row["healthy_prediction"] = (
            row.get("forecast_health_score", 0.0) >= 0.05
            and row.get("valuation_health_score", 0.0) >= -0.25
            and not row.get("valuation_red_flag", False)
        )

    rows.sort(key=lambda row: row.get("opportunity_score", 0.0), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    selected = rows[:limit]
    selected_symbols = {row["symbol"] for row in selected}
    missing_protected = [row for row in rows if row["symbol"] in protected_symbols and row["symbol"] not in selected_symbols]
    if missing_protected:
        selected = selected + missing_protected
        selected.sort(key=lambda row: row.get("opportunity_score", 0.0), reverse=True)
    return selected


def attach_research(enriched: Dict[str, pd.DataFrame], research_rows: Iterable[dict]) -> None:
    by_symbol = {row["symbol"]: row for row in research_rows}
    for sym, row in by_symbol.items():
        if sym in enriched:
            enriched[sym].attrs["candidate_research"] = row
