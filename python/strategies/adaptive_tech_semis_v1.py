"""Adaptive tech/semiconductor allocator.

The goal is not to predict every wiggle. It keeps SPY as ballast, buys
tech/semiconductor leadership when the setup is attractive, refuses badly
extended names, and rotates a larger sleeve to SHY during high-stress drops.
"""
from __future__ import annotations
import math
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ._types import Signal


MANIFEST = {
    "id": "adaptive_tech_semis_v1",
    "version": "1.0",
    "kind": "allocator",
    "params": {
        "benchmark": "SPY",
        "vol_symbol": "^VIX",
        "safety_symbol": "SHY",
        "growth_universe": [
            "QQQ", "SMH", "NVDA", "AVGO", "AMD", "TSM",
            "GOOGL", "MSFT", "AMZN", "META", "AAPL", "TSLA",
            "ARM", "ASML", "MU", "LRCX", "KLAC", "AMAT", "MRVL", "MPWR", "ON", "NXPI",
            "PLTR", "CRM", "NOW", "SNOW", "DDOG", "NET", "CRWD", "PANW", "ZS", "MDB", "ADBE",
            "UBER", "ABNB", "SHOP", "MELI", "NFLX", "SPOT", "BKNG",
            "V", "MA", "AXP", "COIN", "HOOD", "CME", "ICE",
            "GE", "ETN", "VRT", "CEG", "TLN", "PWR", "EME",
            "LLY", "NVO", "ISRG", "VRTX", "REGN", "TMO",
        ],
        "semis": ["SMH", "NVDA", "AVGO", "AMD", "TSM", "ARM", "ASML", "MU", "LRCX", "KLAC", "AMAT", "MRVL", "MPWR", "ON", "NXPI"],
        "etfs": ["QQQ", "SMH"],
        "max_picks": 4,
        "stock_weight": 0.10,
        "etf_weight": 0.20,
        "fear_etf_weight": 0.30,
        "safety_weight": 0.45,
        "min_score": 0.20,
        "fear_vix": 20.0,
        "calm_vix": 16.0,
        "stress_vix": 28.0,
        "spy_stress_drawdown": 0.12,
        "hard_spy_drawdown": 0.18,
        "max_entry_extension_sma50": 1.20,
        "max_entry_rsi": 78.0,
        "sell_extension_sma50": 1.28,
        "sell_rsi": 82.0,
        "trend_break_sma50": 0.95,
        "rs_window": 63,
        "mom_window": 20,
        "decay_zscore_exit": 0.0,
        "stop_atr": 4.0,
        "target_atr": 12.0,
        "max_hold_days": 160,
    },
    "rules": (
        "Hold SPY as ballast. In normal/fear regimes, rank QQQ, SMH, and major "
        "tech/semiconductor stocks by relative strength, trend, momentum, and "
        "buyable pullback quality. Avoid new entries when RSI or price/50dma is "
        "too extended. Exit holdings that become overextended or break trend. "
        "When SPY drawdown/VIX indicate stress, prefer a larger SHY safety sleeve."
    ),
    "status": "active",
}


def _last(df: pd.DataFrame, col: str, default: float = float("nan")) -> float:
    if df.empty or col not in df.columns or pd.isna(df[col].iloc[-1]):
        return default
    return float(df[col].iloc[-1])


def _ret(close: pd.Series, window: int) -> float:
    if len(close) < window + 1:
        return float("nan")
    start = float(close.iloc[-window - 1])
    end = float(close.iloc[-1])
    return end / start - 1.0 if start > 0 else float("nan")


def _spy_context(universe: Dict[str, pd.DataFrame], params: dict) -> dict:
    spy = universe.get(params["benchmark"])
    vix_df = universe.get(params["vol_symbol"])
    if spy is None or spy.empty:
        return {"stress": True, "hard_stress": True, "fear": False, "vix": float("nan")}

    close = _last(spy, "close")
    sma200 = _last(spy, "sma200")
    hi200 = float(spy["close"].tail(200).max()) if len(spy) >= 200 else close
    dd200 = 1.0 - close / hi200 if hi200 > 0 else 0.0
    vix = _last(vix_df, "close") if vix_df is not None else float("nan")

    fear_state = False
    if vix_df is not None and not vix_df.empty:
        for value in vix_df["close"].dropna().tail(252):
            if not fear_state and value >= params["fear_vix"]:
                fear_state = True
            elif fear_state and value <= params["calm_vix"]:
                fear_state = False

    below_200 = close < sma200 if np.isfinite(sma200) else False
    stress = (
        dd200 >= params["spy_stress_drawdown"]
        or (np.isfinite(vix) and vix >= params["stress_vix"] and below_200)
    )
    hard_stress = dd200 >= params["hard_spy_drawdown"]
    return {
        "stress": stress,
        "hard_stress": hard_stress,
        "fear": fear_state,
        "vix": vix,
        "spy_dd200": dd200,
        "spy_below_200": below_200,
    }


def compute_ranks(universe: Dict[str, pd.DataFrame], params: dict) -> Dict[str, dict]:
    ctx = _spy_context(universe, params)
    out: Dict[str, dict] = {}

    safety = params["safety_symbol"]
    if safety in universe:
        out[safety] = {
            "rank": 1 if ctx["stress"] else 99,
            "composite": 1.0 if ctx["stress"] else -1.0,
            "target_weight": params["safety_weight"],
            "reason": "market stress safety sleeve" if ctx["stress"] else "safety sleeve not needed",
            **ctx,
        }

    bench = universe.get(params["benchmark"])
    if bench is None or bench.empty:
        return out
    bench_close = bench["close"]
    rows = []
    for sym in params["growth_universe"]:
        df = universe.get(sym)
        if df is None or df.empty or len(df) < max(200, params["rs_window"]) + 1:
            continue
        if bool(df.get("synthetic", pd.Series([False])).iloc[-1]):
            continue
        close = _last(df, "close")
        sma50 = _last(df, "sma50")
        sma200 = _last(df, "sma200")
        rsi14 = _last(df, "rsi14")
        atr14 = _last(df, "atr14")
        if close <= 0 or not np.isfinite(sma50) or not np.isfinite(sma200):
            continue

        rel = _ret(df["close"], params["rs_window"]) - _ret(bench_close, params["rs_window"])
        mom = _ret(df["close"], params["mom_window"])
        extension = close / sma50 if sma50 > 0 else float("nan")
        trend = close / sma200 - 1.0 if sma200 > 0 else float("nan")
        high20 = _last(df, "high20", close)
        pullback = close / high20 - 1.0 if high20 > 0 else 0.0
        research = df.attrs.get("candidate_research", {}) or {}
        market_reward = float(research.get("market_reward_score") or 0.0)
        forecast_health = float(research.get("forecast_health_score") or 0.0)
        valuation_health = float(research.get("valuation_health_score") or 0.0)
        quality_health = float(research.get("quality_health_score") or 0.0)
        massive_bonus = 0.18 * market_reward + 0.12 * forecast_health + 0.10 * quality_health + 0.08 * valuation_health
        if research.get("valuation_red_flag"):
            massive_bonus -= 0.18
        overbought = (
            extension >= params["sell_extension_sma50"]
            or rsi14 >= params["sell_rsi"]
        )
        broken = (
            extension <= params["trend_break_sma50"]
            and rel < 0
        )
        too_high_to_enter = (
            extension >= params["max_entry_extension_sma50"]
            or rsi14 >= params["max_entry_rsi"]
        )
        if ctx["hard_stress"]:
            score = -1.0
        else:
            semi_bonus = 0.12 if sym in params["semis"] else 0.0
            etf_bonus = 0.45 if sym == "QQQ" else (0.25 if sym == "SMH" else 0.0)
            fear_pullback_bonus = 0.0
            if ctx["fear"] and -0.12 <= pullback <= -0.02:
                fear_pullback_bonus = 0.25
            chase_penalty = 0.20 if too_high_to_enter and sym in params["etfs"] else (
                0.40 if too_high_to_enter else 0.0
            )
            stress_penalty = 0.45 if ctx["stress"] and sym not in params["etfs"] else 0.0
            score = (
                1.8 * rel
                + 0.9 * mom
                + 0.7 * trend
                + massive_bonus
                + semi_bonus
                + etf_bonus
                + fear_pullback_bonus
                - chase_penalty
                - stress_penalty
            )
            if overbought or (broken and sym not in params["etfs"]):
                score = -1.0
        rows.append((sym, score, {
            "composite": float(score),
            "relative_strength": float(rel) if np.isfinite(rel) else 0.0,
            "momentum_20d": float(mom) if np.isfinite(mom) else 0.0,
            "trend_vs_200d": float(trend) if np.isfinite(trend) else 0.0,
            "extension_sma50": float(extension) if np.isfinite(extension) else 0.0,
            "rsi14": float(rsi14) if np.isfinite(rsi14) else 0.0,
            "pullback_from_20d_high": float(pullback),
            "overbought": bool(overbought),
            "broken": bool(broken),
            "too_high_to_enter": bool(too_high_to_enter),
            "atr14": float(atr14) if np.isfinite(atr14) else 0.0,
            "target_weight": _target_weight(sym, params, ctx),
            "market_reward_score": market_reward,
            "forecast_health_score": forecast_health,
            "valuation_health_score": valuation_health,
            "quality_health_score": quality_health,
            "massive_source": research.get("source"),
            **ctx,
        }))

    ranked = sorted(rows, key=lambda row: row[1], reverse=True)
    for rank, (sym, _score, info) in enumerate(ranked, start=1):
        info["rank"] = rank
        out[sym] = info
    return out


def run(
    symbol: str, df: pd.DataFrame, params: dict,
    *, regime: str, sentiment: float, universe: Optional[Dict[str, pd.DataFrame]] = None,
) -> Optional[Signal]:
    if universe is None or df.empty:
        return None
    ranks = compute_ranks(universe, params)
    info = ranks.get(symbol)
    if info is None:
        return None

    if symbol == params["safety_symbol"]:
        if not info.get("stress"):
            return None
        price = _last(df, "close")
        return Signal(
            symbol=symbol,
            strategy_id=MANIFEST["id"],
            side="long",
            rationale=(
                f"Safety sleeve: SPY 200d drawdown {info['spy_dd200']*100:.1f}%, "
                f"VIX {info['vix']:.1f}; rotating part of buying power to SHY."
            ),
            stop_distance=max(0.01, price * 0.03),
            target_distance=max(0.01, price * 0.05),
            max_hold_days=int(params["max_hold_days"]),
            score=0.65,
            extras={
                "target_weight": params["safety_weight"],
                "regime_role": "safety",
                "spy_dd200": round(info["spy_dd200"], 4),
                "vix": round(info["vix"], 2) if np.isfinite(info["vix"]) else None,
            },
        )

    if info["rank"] > params["max_picks"]:
        return None
    if info["composite"] < params["min_score"]:
        return None
    if info.get("too_high_to_enter") and symbol not in params["etfs"]:
        return None
    if info.get("hard_stress"):
        return None

    price = _last(df, "close")
    atr = info.get("atr14", 0.0)
    stop_distance = params["stop_atr"] * atr if atr > 0 else price * 0.08
    target_distance = params["target_atr"] * atr if atr > 0 else price * 0.18
    return Signal(
        symbol=symbol,
        strategy_id=MANIFEST["id"],
        side="long",
        rationale=(
            f"Rank #{info['rank']} adaptive tech/semis score={info['composite']:+.2f}; "
            f"RS63={info['relative_strength']*100:+.1f}%, mom20={info['momentum_20d']*100:+.1f}%, "
            f"price/50dma={info['extension_sma50']:.2f}, RSI={info['rsi14']:.1f}, "
            f"forecast={info['forecast_health_score']:+.2f}, valuation={info['valuation_health_score']:+.2f}, "
            f"VIX={info['vix']:.1f}. Target weight {info['target_weight']*100:.0f}%."
        ),
        stop_distance=float(stop_distance),
        target_distance=float(target_distance),
        max_hold_days=int(params["max_hold_days"]),
        score=float(min(1.0, max(0.0, 0.55 + info["composite"] / 2.0))),
        extras={
            "target_weight": info["target_weight"],
            "rank": info["rank"],
            "composite": round(info["composite"], 3),
            "rs63": round(info["relative_strength"], 4),
            "mom20": round(info["momentum_20d"], 4),
            "extension_sma50": round(info["extension_sma50"], 3),
            "rsi14": round(info["rsi14"], 1),
            "market_reward_score": round(info["market_reward_score"], 3),
            "forecast_health_score": round(info["forecast_health_score"], 3),
            "valuation_health_score": round(info["valuation_health_score"], 3),
            "quality_health_score": round(info["quality_health_score"], 3),
            "massive_source": info.get("massive_source"),
            "vix": round(info["vix"], 2) if np.isfinite(info["vix"]) else None,
            "regime_role": "growth",
        },
    )


def _target_weight(symbol: str, params: dict, ctx: dict) -> float:
    if symbol == "QQQ":
        return params["fear_etf_weight"] if ctx["fear"] else params["etf_weight"]
    if symbol == "SMH":
        return 0.20 if ctx["fear"] else 0.15
    return params["stock_weight"]


def target_weights(universe: Dict[str, pd.DataFrame], params: dict) -> dict:
    """Return target portfolio weights for the allocation engine."""
    ctx = _spy_context(universe, params)
    ranks = compute_ranks(universe, params)

    if ctx["stress"]:
        return {
            "SPY": 0.35,
            params["safety_symbol"]: params["safety_weight"],
            "CASH": 0.20,
        }

    if ctx["fear"]:
        targets = {"SPY": 0.40, "QQQ": 0.25, "SMH": 0.20, "CASH": 0.05}
    else:
        targets = {"SPY": 0.55, "QQQ": 0.20, "SMH": 0.15}

    stock_candidates = []
    for sym, info in ranks.items():
        if sym in ("SPY", "QQQ", "SMH", params["safety_symbol"]):
            continue
        if info.get("composite", -1.0) < params["min_score"]:
            continue
        if info.get("too_high_to_enter") or info.get("overbought") or info.get("broken"):
            continue
        stock_candidates.append((sym, info["composite"]))
    stock_candidates.sort(key=lambda item: item[1], reverse=True)

    remaining = max(0.0, 1.0 - sum(targets.values()))
    for sym, _score in stock_candidates[:2]:
        if remaining + 1e-9 < params["stock_weight"]:
            break
        targets[sym] = params["stock_weight"]
        remaining -= params["stock_weight"]
    targets["CASH"] = targets.get("CASH", 0.0) + remaining
    return targets
