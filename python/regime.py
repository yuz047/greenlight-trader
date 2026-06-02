"""Market regime classification."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from config import DATA_DIR, MANDATE, REGIME_BUDGETS
from data_contracts import write_json
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def determine_regime(
    price_history: dict[str, pd.DataFrame],
    feature_payload: dict[str, Any] | None = None,
    data_health: dict[str, Any] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    data_health = data_health or {}
    if not data_health.get("ok", False):
        return add_watermark(
            {
                "as_of": as_of,
                "regime": "DATA_FAILURE",
                "risk_on_score": 0.0,
                "inputs": {"data_health": data_health},
                "budgets": REGIME_BUDGETS["DATA_FAILURE"],
                "allow_new_alpha_entries": False,
            },
            SYSTEMATIC_TEMPLATE_OUTPUT,
        )

    spy = _slice(price_history.get(MANDATE.benchmark), as_of)
    qqq = _slice(price_history.get(MANDATE.secondary_growth_anchor), as_of)
    vix = _slice(price_history.get("^VIX"), as_of)
    if spy is None or len(spy) < 200:
        return add_watermark(
            {
                "as_of": as_of,
                "regime": "DATA_FAILURE",
                "risk_on_score": 0.0,
                "inputs": {"missing": "SPY_200DMA"},
                "budgets": REGIME_BUDGETS["DATA_FAILURE"],
                "allow_new_alpha_entries": False,
            },
            SYSTEMATIC_TEMPLATE_OUTPUT,
        )

    close = spy["close"].astype(float)
    spy_above_200 = bool(close.iloc[-1] > close.tail(200).mean())
    spy_drawdown = float(close.iloc[-1] / close.tail(200).max() - 1)
    qqq_rs = _relative_strength(qqq["close"].astype(float), close, 63) if qqq is not None and len(qqq) > 63 else 0.0
    vix_level = float(vix["close"].iloc[-1]) if vix is not None and not vix.empty else None
    vix_change = float(vix["close"].iloc[-1] / vix["close"].iloc[-6] - 1) if vix is not None and len(vix) > 6 else None
    etf_breadth = _etf_leadership_breadth(feature_payload)

    risk_on_score = 0.0
    risk_on_score += 0.30 if spy_above_200 else -0.30
    risk_on_score += 0.20 if spy_drawdown > -0.08 else -0.20
    risk_on_score += 0.15 if qqq_rs > 0 else -0.05
    risk_on_score += 0.15 if etf_breadth >= 0.45 else -0.10
    if vix_level is not None:
        risk_on_score += 0.15 if vix_level < 20 else (-0.25 if vix_level > 30 else -0.05)
    if vix_change is not None and vix_change > 0.25:
        risk_on_score -= 0.15

    if spy_drawdown <= -0.20 or (vix_level is not None and vix_level >= 35):
        regime = "STRESS"
    elif spy_drawdown <= -0.10 or not spy_above_200 or (vix_level is not None and vix_level >= 25):
        regime = "FEAR"
    elif risk_on_score >= 0.35:
        regime = "RISK_ON"
    else:
        regime = "NEUTRAL"

    return add_watermark(
        {
            "as_of": as_of,
            "regime": regime,
            "risk_on_score": round(float(risk_on_score), 4),
            "inputs": {
                "spy_above_200dma": spy_above_200,
                "spy_drawdown_from_200d_high": round(spy_drawdown, 4),
                "vix_level": vix_level,
                "vix_change": vix_change,
                "qqq_vs_spy_relative_strength": qqq_rs,
                "etf_leadership_breadth": etf_breadth,
                "data_health": data_health,
            },
            "budgets": REGIME_BUDGETS[regime],
            "allow_new_alpha_entries": regime in ("RISK_ON", "NEUTRAL"),
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def write_regime(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "regime.json", payload)


def _slice(frame: pd.DataFrame | None, as_of: str) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    out = frame.loc[frame.index <= pd.Timestamp(as_of)]
    return out if not out.empty else None


def _relative_strength(series: pd.Series, benchmark: pd.Series, days: int) -> float:
    if len(series) <= days or len(benchmark) <= days:
        return 0.0
    return float(series.iloc[-1] / series.iloc[-days - 1] - benchmark.iloc[-1] / benchmark.iloc[-days - 1])


def _etf_leadership_breadth(feature_payload: dict[str, Any] | None) -> float:
    if not feature_payload:
        return 0.0
    rows = [r for r in feature_payload.get("feature_rows", []) if r.get("asset_type") == "etf"]
    if not rows:
        return 0.0
    leaders = [r for r in rows if r.get("above_50dma") and (r.get("relative_strength_spy") or 0) > 0]
    return len(leaders) / len(rows)
