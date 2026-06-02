"""Feature engineering for stocks and ETFs."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from config import DATA_DIR, MANDATE
from data_contracts import CandidateFeatureRow, write_json
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def compute_features(
    universe_payload: dict[str, Any],
    price_history: dict[str, pd.DataFrame],
    as_of: str | None = None,
    current_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    current_weights = current_weights or {}
    spy = _slice_to_asof(price_history.get(MANDATE.benchmark), as_of, lookback=260)
    qqq = _slice_to_asof(price_history.get(MANDATE.secondary_growth_anchor), as_of, lookback=260)
    portfolio_proxy = _weighted_portfolio_returns(price_history, current_weights, as_of)

    rows: list[dict[str, Any]] = []
    for candidate in universe_payload.get("candidates", []):
        row = _feature_row(candidate, price_history.get(candidate["symbol"]), spy, qqq, portfolio_proxy, as_of)
        rows.append(asdict(row))

    return add_watermark(
        {
            "as_of": as_of,
            "feature_rows": rows,
            "no_lookahead": "features use bars with date <= as_of only",
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def write_features(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "candidate_features.json", payload)


def _feature_row(
    candidate: dict[str, Any],
    frame: pd.DataFrame | None,
    spy: pd.DataFrame | None,
    qqq: pd.DataFrame | None,
    portfolio_proxy_returns: pd.Series | None,
    as_of: str,
) -> CandidateFeatureRow:
    symbol = candidate["symbol"]
    asset_type = candidate["asset_type"]
    hist = _slice_to_asof(frame, as_of, lookback=260)
    missing = 0
    if hist is None or hist.empty or len(hist) < 20:
        return CandidateFeatureRow(
            symbol=symbol,
            asset_type=asset_type,
            as_of=as_of,
            sector=candidate.get("sector"),
            industry=candidate.get("industry"),
            theme=candidate.get("theme"),
            category=candidate.get("category"),
            market_cap=candidate.get("market_cap"),
            data_quality_flag="missing_price_history",
            data_quality_multiplier=0.25,
            investable_flag=False,
            high_risk_symbol_flag=bool(candidate.get("high_risk_symbol_flag")),
            missing_data_count=12,
        )

    close = hist["close"].astype(float)
    volume = hist["volume"].astype(float)
    price = float(close.iloc[-1])
    avg_dollar_volume = float((close * volume).tail(20).mean())
    source_flags = set(str(x) for x in hist.get("data_quality_flag", pd.Series(["ok"])).tail(5).dropna().unique())
    data_quality_flag = "synthetic" if "synthetic" in source_flags else "ok"
    data_quality_multiplier = 0.55 if data_quality_flag == "synthetic" else 1.0

    momentum_20d = _pct_return(close, 20)
    momentum_63d = _pct_return(close, 63)
    momentum_126d = _pct_return(close, 126)
    realized_volatility = _annualized_vol(close.pct_change().dropna().tail(63))
    sma50 = close.tail(50).mean() if len(close) >= 50 else np.nan
    sma200 = close.tail(200).mean() if len(close) >= 200 else np.nan
    recent_high = close.tail(126).max()
    drawdown = float(price / recent_high - 1) if recent_high and recent_high > 0 else None
    rsi = _rsi(close)
    atr = _atr(hist)
    volume_zscore = _zscore_last(volume.tail(60))
    distance_from_50dma = float(price / sma50 - 1) if np.isfinite(sma50) and sma50 > 0 else None

    spy_close = spy["close"].astype(float) if spy is not None and not spy.empty else None
    qqq_close = qqq["close"].astype(float) if qqq is not None and not qqq.empty else None
    rs_spy = _relative_strength(close, spy_close, 63)
    rs_qqq = _relative_strength(close, qqq_close, 63)
    beta_spy = _beta(close, spy_close)
    beta_qqq = _beta(close, qqq_close)
    corr_spy = _corr(close, spy_close)
    corr_qqq = _corr(close, qqq_close)
    corr_port = _corr_returns(close.pct_change().dropna(), portfolio_proxy_returns)

    if any(value is None for value in (momentum_63d, rs_spy, rsi, atr, realized_volatility)):
        missing += 1
    if candidate.get("market_cap") is None and asset_type == "stock":
        missing += 1
        data_quality_multiplier *= 0.9

    investable = True
    reasons = []
    if price < MANDATE.min_price and asset_type not in ("cash_proxy", "benchmark"):
        investable = False
        reasons.append("low_price")
    if avg_dollar_volume < MANDATE.min_avg_dollar_volume and asset_type not in ("cash_proxy", "benchmark"):
        investable = False
        reasons.append("low_liquidity")
    if candidate.get("market_cap") is not None and candidate["market_cap"] < MANDATE.min_market_cap and asset_type == "stock":
        investable = False
        reasons.append("small_market_cap")
    if candidate.get("high_risk_symbol_flag"):
        data_quality_multiplier *= 0.75

    if reasons:
        data_quality_flag = ",".join(reasons)

    earnings_proximity_days = None
    event_risk = 0.0
    if earnings_proximity_days is not None and earnings_proximity_days <= 5:
        event_risk = 0.25

    liquidity_score = min(1.0, max(0.0, avg_dollar_volume / 25_000_000.0))
    vol_adj_momentum = None
    if momentum_63d is not None and realized_volatility and realized_volatility > 0:
        vol_adj_momentum = momentum_63d / realized_volatility

    return CandidateFeatureRow(
        symbol=symbol,
        asset_type=asset_type,
        as_of=as_of,
        sector=candidate.get("sector"),
        industry=candidate.get("industry"),
        theme=candidate.get("theme"),
        category=candidate.get("category"),
        market_cap=candidate.get("market_cap"),
        avg_dollar_volume=avg_dollar_volume,
        price=price,
        news_sentiment=None,
        news_volume=0,
        earnings_proximity_days=earnings_proximity_days,
        relative_strength_spy=rs_spy,
        relative_strength_qqq=rs_qqq,
        momentum_20d=momentum_20d,
        momentum_63d=momentum_63d,
        momentum_126d=momentum_126d,
        above_50dma=bool(price > sma50) if np.isfinite(sma50) else None,
        above_200dma=bool(price > sma200) if np.isfinite(sma200) else None,
        drawdown_from_high=drawdown,
        sector_theme_leadership=rs_spy,
        volatility_adjusted_momentum=vol_adj_momentum,
        rsi=rsi,
        atr=atr,
        volume_zscore=volume_zscore,
        distance_from_50dma=distance_from_50dma,
        pullback_flag=bool(distance_from_50dma is not None and -0.08 <= distance_from_50dma <= -0.01 and (rsi or 50) < 55),
        breakout_flag=bool(len(close) >= 21 and price >= close.tail(21).iloc[:-1].max() and (volume_zscore or 0) > 0.5),
        extension_flag=bool(distance_from_50dma is not None and distance_from_50dma > 0.12 and (rsi or 0) > 70),
        realized_volatility=realized_volatility,
        beta_spy=beta_spy,
        beta_qqq=beta_qqq,
        correlation_spy=corr_spy,
        correlation_qqq=corr_qqq,
        correlation_portfolio=corr_port,
        event_risk=event_risk,
        liquidity_score=liquidity_score,
        high_risk_symbol_flag=bool(candidate.get("high_risk_symbol_flag")),
        data_quality_flag=data_quality_flag,
        data_quality_multiplier=max(0.1, min(1.0, data_quality_multiplier)),
        investable_flag=investable,
        missing_data_count=missing,
    )


def _slice_to_asof(frame: pd.DataFrame | None, as_of: str, lookback: int | None = None) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    idx = frame.index.searchsorted(pd.Timestamp(as_of), side="right")
    if idx <= 0:
        return frame.iloc[:0]
    start = max(0, idx - lookback) if lookback else 0
    return frame.iloc[start:idx]


def _pct_return(series: pd.Series, days: int) -> float | None:
    if len(series) <= days:
        return None
    start = float(series.iloc[-days - 1])
    end = float(series.iloc[-1])
    return end / start - 1 if start > 0 else None


def _annualized_vol(returns: pd.Series) -> float | None:
    if len(returns) < 10:
        return None
    return float(returns.std(ddof=0) * np.sqrt(252))


def _relative_strength(series: pd.Series, benchmark: pd.Series | None, days: int) -> float | None:
    own = _pct_return(series, days)
    bench = _pct_return(benchmark, days) if benchmark is not None else None
    if own is None or bench is None:
        return None
    return own - bench


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) <= period:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).tail(period).mean()
    loss = -delta.clip(upper=0).tail(period).mean()
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - (100 / (1 + rs)))


def _atr(frame: pd.DataFrame, period: int = 14) -> float | None:
    if len(frame) <= period:
        return None
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def _zscore_last(series: pd.Series) -> float | None:
    if len(series) < 10:
        return None
    std = float(series.std(ddof=0))
    if std == 0:
        return 0.0
    return float((series.iloc[-1] - series.mean()) / std)


def _beta(series: pd.Series, benchmark: pd.Series | None, lookback: int = 126) -> float | None:
    if benchmark is None:
        return None
    pair = pd.concat([series.pct_change(), benchmark.pct_change()], axis=1, join="inner").dropna().tail(lookback)
    if len(pair) < 20:
        return None
    var = float(pair.iloc[:, 1].var(ddof=0))
    if var == 0:
        return None
    return float(pair.iloc[:, 0].cov(pair.iloc[:, 1]) / var)


def _corr(series: pd.Series, benchmark: pd.Series | None, lookback: int = 126) -> float | None:
    if benchmark is None:
        return None
    return _corr_returns(series.pct_change().dropna(), benchmark.pct_change().dropna(), lookback)


def _corr_returns(left: pd.Series, right: pd.Series | None, lookback: int = 126) -> float | None:
    if right is None or right.empty:
        return None
    pair = pd.concat([left, right], axis=1, join="inner").dropna().tail(lookback)
    if len(pair) < 20:
        return None
    return float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))


def _weighted_portfolio_returns(
    price_history: dict[str, pd.DataFrame],
    current_weights: dict[str, float],
    as_of: str,
) -> pd.Series | None:
    parts = []
    for symbol, weight in current_weights.items():
        frame = _slice_to_asof(price_history.get(symbol), as_of, lookback=260)
        if frame is not None and not frame.empty:
            parts.append(frame["close"].astype(float).pct_change().fillna(0) * float(weight))
    if not parts:
        return None
    return sum(parts).dropna()
