"""stock_pitcher_v2 — high-conviction, long-hold pitcher for the SPY-anchored book.

V2 differs from v1 in three ways that match the new mandate:

  - Higher conviction floor:    composite z >= 1.0 (was 0.6).
  - Longer holds:               30 trading days, exits on signal decay
                                (composite z < 0.5) — picks ride trends rather
                                than chasing 5-day breakouts.
  - Cap of 2 picks:             matches the SPY-core architecture, which keeps
                                a 50% SPY baseline at minimum.

Stops and targets are still ATR-anchored but wider (the pitcher is no longer
trying to outperform on absolute basis — it's trying to beat SPY in the names
it picks, so we let positions breathe).
"""
from __future__ import annotations
import math
from typing import Optional, Dict
import numpy as np
import pandas as pd

from ._types import Signal


MANIFEST = {
    "id": "stock_pitcher_v2",
    "version": "2.0",
    "kind": "ranker",
    "params": {
        "trend_window": 60,
        "rs_window": 63,
        "mom_window": 20,
        "min_zscore": 1.0,               # was 0.6 — higher conviction
        "min_quality": 0.30,             # tighter R² floor
        "min_relative_strength": 0.00,   # must lead SPY (was -0.05)
        "atr_window": 14,
        "stop_mult": 2.0,                # wider stop, let it breathe
        "target_horizon_days": 20,       # project trend further forward
        "target_min_atr": 2.0,
        "target_max_atr": 6.0,
        "max_hold_days": 30,             # was 10 — ride the trend
        "decay_zscore_exit": 0.5,        # exit when composite z falls below this
        "benchmark": "SPY",
        "max_picks": 2,
    },
    "rules": (
        "Universe-wide composite rank: 60d trend t-stat, R^2 quality, 63d RS vs SPY, "
        "20d return / 20d vol. Take top 2 names with composite z >= 1.0 AND R^2 >= 0.3 "
        "AND RS >= SPY. Stop = 2 ATR. Target = projected 20d move, clipped to [2, 6] ATR. "
        "Max hold 30d; early exit when composite z falls below 0.5."
    ),
    "status": "active",
}


def _trend_stats(close: pd.Series, window: int) -> tuple[float, float, float]:
    s = np.log(close.tail(window).to_numpy())
    if len(s) < window or np.any(~np.isfinite(s)):
        return (float("nan"), float("nan"), float("nan"))
    x = np.arange(len(s), dtype=float)
    sxx = ((x - x.mean()) ** 2).sum()
    sxy = ((x - x.mean()) * (s - s.mean())).sum()
    if sxx <= 0:
        return (float("nan"), float("nan"), float("nan"))
    slope = sxy / sxx
    intercept = s.mean() - slope * x.mean()
    resid = s - (slope * x + intercept)
    ss_res = (resid ** 2).sum()
    ss_tot = ((s - s.mean()) ** 2).sum()
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    n = len(s)
    if n < 4:
        return (slope, float("nan"), r2)
    se = math.sqrt(ss_res / (n - 2) / sxx)
    t_stat = slope / se if se > 0 else 0.0
    return (slope, t_stat, r2)


def _relative_strength(sym_close: pd.Series, bench_close: pd.Series, window: int) -> float:
    if len(sym_close) < window + 1 or len(bench_close) < window + 1:
        return float("nan")
    return float(sym_close.iloc[-1] / sym_close.iloc[-window - 1]
                 - bench_close.iloc[-1] / bench_close.iloc[-window - 1])


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


_RANK_CACHE: dict = {}


def compute_ranks(universe: Dict[str, pd.DataFrame], params: dict) -> Dict[str, dict]:
    """Public helper — portfolio uses this to check whether a held pick's
    composite z has decayed below the exit threshold."""
    syms = list(universe.keys())
    bench = params["benchmark"]
    if bench not in universe:
        return {}
    bench_close = universe[bench]["close"]
    trend_w = params["trend_window"]

    ts, qs, rss, mms, slopes = [], [], [], [], []
    for sym in syms:
        df = universe[sym]
        if df.empty or len(df) < max(trend_w, params["rs_window"]) + 2:
            slopes.append(np.nan); ts.append(np.nan); qs.append(np.nan)
            rss.append(np.nan); mms.append(np.nan); continue
        sl, t, r2 = _trend_stats(df["close"], trend_w)
        slopes.append(sl); ts.append(t); qs.append(r2)
        rss.append(_relative_strength(df["close"], bench_close, params["rs_window"]))
        mms.append(_risk_adj_momentum(df["close"], params["mom_window"]))

    zT = _zscore(np.array(ts)); zQ = _zscore(np.array(qs))
    zR = _zscore(np.array(rss)); zM = _zscore(np.array(mms))

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
            "z_trend": float(zT[i]),
            "z_quality": float(zQ[i]),
            "z_rs": float(zR[i]),
            "z_mom": float(zM[i]),
            "composite": composite,
        }
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

    cache_key = (regime, len(universe), str(df.index[-1].date()))
    ranks = _RANK_CACHE.get(cache_key)
    if ranks is None:
        ranks = compute_ranks(universe, params)
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
    if info["rank"] > params["max_picks"]:
        return None

    atr_v = float(last["atr14"])
    if atr_v <= 0 or not np.isfinite(atr_v):
        return None
    price = float(last["close"])

    stop_distance = params["stop_mult"] * atr_v
    projected_log_move = info["slope"] * params["target_horizon_days"]
    projected_price_move = price * (math.exp(projected_log_move) - 1.0)
    target_distance = max(
        params["target_min_atr"] * atr_v,
        min(params["target_max_atr"] * atr_v, projected_price_move),
    )

    rationale = (
        f"Rank #{info['rank']} composite z={info['composite']:+.2f} "
        f"(trend z={info['z_trend']:+.2f}, R²={info['r2']:.2f}, "
        f"RS vs SPY={info['rs']*100:+.1f}%). "
        f"Projected 20d move ${projected_price_move:+.2f}; "
        f"stop ${stop_distance:.2f}, target ${target_distance:.2f}. "
        f"Replacing 25% SPY core with this pick."
    )
    score = min(1.0, max(0.0, 0.5 + 0.3 * info["composite"] + 0.1 * (3 - info["rank"])))

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
            "projected_horizon_move": round(projected_price_move, 2),
            "entry_ref_price": round(price, 2),
            "exit_z_threshold": params["decay_zscore_exit"],
        },
    )
