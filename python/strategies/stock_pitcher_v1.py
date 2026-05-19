"""stock_pitcher_v1 — relative-strength + trend-quality stock pitcher.

This is a cross-sectional ranker, not a per-symbol rule. Every name in
the universe is scored on four normalized factors:

    T (trend t-stat)       — slope / stderr of OLS on log(close) over `trend_window`.
                              Captures persistent trend, not just one good day.
    Q (trend quality)      — R^2 of the same regression. Filters out noisy lines.
    R (relative strength)  — `rs_window` total return minus SPY's over the same window.
    M (risk-adj momentum)  — `mom_window` return / `mom_window` realized vol.

The four factors are z-scored across the universe and averaged into a
composite. The strategy emits a signal for each symbol whose composite
exceeds `min_zscore`, with stop / target sized to the realized trend
slope rather than a fixed multiple of ATR (so calmer trends get tighter
stops, choppy trends get wider ones).

The pitcher cooperates with the simpler rule-based strategies — they
fire concurrently and the risk engine consumes signals in score order.
"""
from __future__ import annotations
import math
from typing import Optional, Dict
import numpy as np
import pandas as pd

from ._types import Signal


MANIFEST = {
    "id": "stock_pitcher_v1",
    "version": "1.0",
    "kind": "ranker",
    "params": {
        "trend_window": 60,
        "rs_window": 63,         # ~ one quarter
        "mom_window": 20,
        "min_zscore": 0.6,       # composite z must exceed this
        "min_quality": 0.25,     # R^2 floor — reject very noisy trends
        "min_relative_strength": -0.05,  # must not be lagging SPY by more than 5%
        "atr_window": 14,
        "stop_mult": 1.5,        # stop = stop_mult * ATR(14)
        "target_horizon_days": 5,
        "target_min_atr": 1.0,
        "target_max_atr": 4.0,
        "max_hold_days": 10,
        "benchmark": "SPY",
        "max_picks": 3,          # cap per day; risk engine still gates further
    },
    "rules": (
        "Universe-wide rank on 4 z-scored factors: 60d trend t-stat, R^2 quality, "
        "63d relative strength vs SPY, and 20d return / 20d vol. Pick top names "
        "with composite z > 0.6 AND quality > 0.25 AND RS > -5%. Stop = 1.5 ATR. "
        "Target = projected slope * 5 days, clipped to [1, 4] ATR. Max hold 10d."
    ),
    "status": "active",
}


def _trend_stats(close: pd.Series, window: int) -> tuple[float, float, float]:
    """Return (slope_per_day_in_log, t_stat, r_squared) of OLS on log(close)."""
    s = np.log(close.tail(window).to_numpy())
    if len(s) < window or np.any(~np.isfinite(s)):
        return (float("nan"), float("nan"), float("nan"))
    x = np.arange(len(s), dtype=float)
    x_bar = x.mean()
    y_bar = s.mean()
    sxx = ((x - x_bar) ** 2).sum()
    sxy = ((x - x_bar) * (s - y_bar)).sum()
    if sxx <= 0:
        return (float("nan"), float("nan"), float("nan"))
    slope = sxy / sxx
    intercept = y_bar - slope * x_bar
    resid = s - (slope * x + intercept)
    ss_res = (resid ** 2).sum()
    ss_tot = ((s - y_bar) ** 2).sum()
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    # standard error of slope
    n = len(s)
    if n < 4:
        return (slope, float("nan"), r2)
    se = math.sqrt(ss_res / (n - 2) / sxx)
    t_stat = slope / se if se > 0 else 0.0
    return (slope, t_stat, r2)


def _relative_strength(sym_close: pd.Series, bench_close: pd.Series, window: int) -> float:
    if len(sym_close) < window + 1 or len(bench_close) < window + 1:
        return float("nan")
    sr = sym_close.iloc[-1] / sym_close.iloc[-window - 1] - 1.0
    br = bench_close.iloc[-1] / bench_close.iloc[-window - 1] - 1.0
    return float(sr - br)


def _risk_adj_momentum(close: pd.Series, window: int) -> float:
    rets = close.pct_change().dropna().tail(window)
    if len(rets) < window:
        return float("nan")
    vol = rets.std()
    if vol == 0 or not np.isfinite(vol):
        return float("nan")
    return float(rets.sum() / vol)


def _zscore(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(float)
    mask = np.isfinite(arr)
    if not mask.any():
        return arr
    mu = arr[mask].mean()
    sd = arr[mask].std(ddof=0)
    if sd == 0:
        return np.where(mask, 0.0, np.nan)
    return np.where(mask, (arr - mu) / sd, np.nan)


# Cache one ranking per (regime, n_symbols, last_date) — the registry calls
# us once per symbol per run, but the ranking is cross-sectional. We compute
# it the first time and reuse for the rest of the call.
_RANK_CACHE: dict = {}


def _compute_ranks(universe: Dict[str, pd.DataFrame], params: dict) -> Dict[str, dict]:
    syms = list(universe.keys())
    bench = params["benchmark"]
    if bench not in universe:
        return {}
    bench_close = universe[bench]["close"]
    trend_w = params["trend_window"]

    slopes, ts, qs, rss, mms = [], [], [], [], []
    for sym in syms:
        df = universe[sym]
        if df.empty or len(df) < max(trend_w, params["rs_window"]) + 2:
            slopes.append(np.nan); ts.append(np.nan); qs.append(np.nan)
            rss.append(np.nan); mms.append(np.nan); continue
        sl, t, r2 = _trend_stats(df["close"], trend_w)
        slopes.append(sl); ts.append(t); qs.append(r2)
        rss.append(_relative_strength(df["close"], bench_close, params["rs_window"]))
        mms.append(_risk_adj_momentum(df["close"], params["mom_window"]))

    zT = _zscore(np.array(ts))
    zQ = _zscore(np.array(qs))
    zR = _zscore(np.array(rss))
    zM = _zscore(np.array(mms))

    out: Dict[str, dict] = {}
    for i, sym in enumerate(syms):
        if not np.isfinite(zT[i]) or not np.isfinite(zR[i]):
            continue
        composite = float(np.nanmean([zT[i], zQ[i], zR[i], zM[i]]))
        out[sym] = {
            "slope": float(slopes[i]),
            "t_stat": float(ts[i]),
            "r2": float(qs[i]),
            "rs": float(rss[i]),
            "rad_mom": float(mms[i]),
            "z_trend": float(zT[i]),
            "z_quality": float(zQ[i]),
            "z_rs": float(zR[i]),
            "z_mom": float(zM[i]),
            "composite": composite,
        }
    # Rank (1 = best)
    ranked = sorted(out.items(), key=lambda kv: kv[1]["composite"], reverse=True)
    for rank, (sym, _) in enumerate(ranked, start=1):
        out[sym]["rank"] = rank
    return out


def run(
    symbol: str, df: pd.DataFrame, params: dict,
    *, regime: str, sentiment: float, universe: Optional[Dict[str, pd.DataFrame]] = None,
) -> Optional[Signal]:
    if universe is None or symbol == params["benchmark"]:
        return None
    if regime in ("distressed",):
        return None
    if df.empty:
        return None
    last = df.iloc[-1]
    if "atr14" not in df.columns or pd.isna(last["atr14"]):
        return None

    # Cache key uses the count + last close date so we recompute once per run
    cache_key = (regime, len(universe), str(df.index[-1].date()))
    ranks = _RANK_CACHE.get(cache_key)
    if ranks is None:
        ranks = _compute_ranks(universe, params)
        _RANK_CACHE[cache_key] = ranks

    info = ranks.get(symbol)
    if info is None:
        return None
    if info["composite"] < params["min_zscore"]:
        return None
    if info["r2"] < params["min_quality"]:
        return None
    if info["rs"] < params["min_relative_strength"]:
        return None
    # Cap to top N
    if info["rank"] > params["max_picks"]:
        return None

    atr_v = float(last["atr14"])
    if atr_v <= 0 or not np.isfinite(atr_v):
        return None
    price = float(last["close"])

    stop_distance = params["stop_mult"] * atr_v
    # Project the regression slope `target_horizon_days` ahead and use the
    # implied price move as the target; clip to [min, max] ATR multiples so
    # we don't get fantasy targets on very steep but short trends.
    projected_log_move = info["slope"] * params["target_horizon_days"]
    projected_price_move = price * (math.exp(projected_log_move) - 1.0)
    target_distance = max(
        params["target_min_atr"] * atr_v,
        min(params["target_max_atr"] * atr_v, projected_price_move),
    )

    rationale = (
        f"Rank #{info['rank']} by composite z={info['composite']:+.2f} "
        f"(trend z={info['z_trend']:+.2f}, quality R²={info['r2']:.2f}, "
        f"RS vs {params['benchmark']}={info['rs']*100:+.1f}%, "
        f"risk-adj mom z={info['z_mom']:+.2f}). "
        f"Projected 5d move ${projected_price_move:+.2f}; "
        f"stop ${stop_distance:.2f}, target ${target_distance:.2f}. regime={regime}."
    )

    # Score blends rank (top is best) and composite z so the risk engine
    # consumes pitcher candidates before weak breakouts.
    score = min(1.0, max(0.0, 0.6 + 0.2 * info["composite"] + 0.1 * (4 - info["rank"])))

    return Signal(
        symbol=symbol,
        strategy_id=MANIFEST["id"],
        side="long",
        rationale=rationale,
        stop_distance=float(stop_distance),
        target_distance=float(target_distance),
        max_hold_days=int(params["max_hold_days"]),
        score=float(score),
        extras={
            "rank": info["rank"],
            "composite_z": round(info["composite"], 3),
            "trend_t_stat": round(info["t_stat"], 2),
            "trend_r2": round(info["r2"], 3),
            "rs_vs_bench": round(info["rs"], 4),
            "projected_5d_move": round(projected_price_move, 2),
            "entry_ref_price": round(price, 2),
        },
    )
