"""Candidate scoring for stocks and ETFs."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from config import DATA_DIR, DEFAULT_ETF_SCORE_WEIGHTS, DEFAULT_STOCK_SCORE_WEIGHTS
from data_contracts import CandidateScore, write_json
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def score_candidates(
    feature_payload: dict[str, Any],
    regime_payload: dict[str, Any],
    stock_weights: dict[str, float] | None = None,
    etf_weights: dict[str, float] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or feature_payload.get("as_of") or date.today().isoformat()
    stock_weights = stock_weights or DEFAULT_STOCK_SCORE_WEIGHTS
    etf_weights = etf_weights or DEFAULT_ETF_SCORE_WEIGHTS
    regime = regime_payload.get("regime", "DATA_FAILURE")

    scores = []
    for row in feature_payload.get("feature_rows", []):
        if row.get("asset_type") in ("etf", "cash_proxy", "benchmark") and row.get("symbol") not in ("SPY", "QQQ", "SGOV", "SHY"):
            score = _score_etf(row, regime, etf_weights, as_of)
        elif row.get("asset_type") == "stock":
            score = _score_stock(row, stock_weights, as_of)
        else:
            score = _score_anchor(row, regime, as_of)
        scores.append(asdict(score))

    sorted_scores = sorted(scores, key=lambda item: item["final_score"], reverse=True)
    return add_watermark(
        {
            "as_of": as_of,
            "regime": regime,
            "stock_weights": stock_weights,
            "etf_weights": etf_weights,
            "scores": sorted_scores,
            "summary": {
                "count": len(sorted_scores),
                "investable_count": len([s for s in sorted_scores if s["investable_flag"]]),
                "top_symbols": [s["symbol"] for s in sorted_scores[:10]],
            },
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def write_candidate_scores(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "candidate_scores.json", payload)


def _score_stock(row: dict[str, Any], weights: dict[str, float], as_of: str) -> CandidateScore:
    information = _information_score(row)
    leadership = _leadership_score(row)
    timing = _timing_score(row)
    risk_penalty = _risk_penalty(row)
    timing_multiplier = _timing_multiplier(row)
    data_multiplier = float(row.get("data_quality_multiplier") or 1.0)
    final = (
        weights["information"] * information
        + weights["leadership"] * leadership
        + weights["timing"] * timing
        - risk_penalty
    )
    final = max(0.0, final) * timing_multiplier * data_multiplier
    wait = information > 0.65 and timing < 0.35
    if wait:
        final *= 0.65
    return CandidateScore(
        symbol=row["symbol"],
        asset_type=row["asset_type"],
        as_of=as_of,
        final_score=round(final, 5),
        information_score=round(information, 5),
        leadership_score=round(leadership, 5),
        timing_score=round(timing, 5),
        risk_penalty=round(risk_penalty, 5),
        investable_flag=bool(row.get("investable_flag")),
        timing_multiplier=round(timing_multiplier, 5),
        data_quality_multiplier=round(data_multiplier, 5),
        wait_flag=wait,
        explanations=_explain(row, information, leadership, timing, risk_penalty, wait),
    )


def _score_etf(row: dict[str, Any], regime: str, weights: dict[str, float], as_of: str) -> CandidateScore:
    leadership = _leadership_score(row)
    regime_fit = _regime_fit(row, regime)
    diversification = _diversification_score(row)
    timing = _timing_score(row)
    risk_penalty = _risk_penalty(row) * 0.75
    timing_multiplier = _timing_multiplier(row)
    data_multiplier = float(row.get("data_quality_multiplier") or 1.0)
    final = (
        weights["leadership"] * leadership
        + weights["regime_fit"] * regime_fit
        + weights["diversification"] * diversification
        + weights["timing"] * timing
        - risk_penalty
    )
    final = max(0.0, final) * timing_multiplier * data_multiplier
    return CandidateScore(
        symbol=row["symbol"],
        asset_type="etf",
        as_of=as_of,
        final_score=round(final, 5),
        leadership_score=round(leadership, 5),
        timing_score=round(timing, 5),
        regime_fit_score=round(regime_fit, 5),
        diversification_score=round(diversification, 5),
        risk_penalty=round(risk_penalty, 5),
        investable_flag=bool(row.get("investable_flag")),
        timing_multiplier=round(timing_multiplier, 5),
        data_quality_multiplier=round(data_multiplier, 5),
        explanations=_explain(row, 0.0, leadership, timing, risk_penalty, False, regime_fit, diversification),
    )


def _score_anchor(row: dict[str, Any], regime: str, as_of: str) -> CandidateScore:
    symbol = row["symbol"]
    base = 0.60 if symbol == "SPY" else 0.35
    if symbol == "QQQ":
        base = 0.50 if regime == "RISK_ON" else 0.20 if regime == "NEUTRAL" else 0.05
    if symbol in ("SGOV", "SHY"):
        base = 0.70 if regime in ("FEAR", "STRESS", "DATA_FAILURE") else 0.20
    return CandidateScore(
        symbol=symbol,
        asset_type=row.get("asset_type", "benchmark"),
        as_of=as_of,
        final_score=base,
        investable_flag=bool(row.get("investable_flag", True)),
        data_quality_multiplier=float(row.get("data_quality_multiplier") or 1.0),
        explanations=[f"{symbol} anchor score is controlled by regime budget, not alpha ranking."],
    )


def _information_score(row: dict[str, Any]) -> float:
    parts = []
    for key, scale in (
        ("analyst_upside", 0.30),
        ("analyst_rating", 1.00),
        ("revenue_growth", 0.25),
        ("earnings_growth", 0.25),
        ("margins", 0.30),
        ("roe", 0.25),
        ("free_cash_flow_signal", 1.00),
        ("valuation_reasonableness", 1.00),
        ("news_sentiment", 1.00),
    ):
        value = row.get(key)
        if value is not None:
            parts.append(_clip01(0.5 + float(value) / max(scale, 1e-9)))
    if not parts:
        return 0.45
    return float(sum(parts) / len(parts))


def _leadership_score(row: dict[str, Any]) -> float:
    parts = []
    for key, scale in (
        ("relative_strength_spy", 0.15),
        ("relative_strength_qqq", 0.15),
        ("momentum_20d", 0.08),
        ("momentum_63d", 0.16),
        ("momentum_126d", 0.25),
        ("volatility_adjusted_momentum", 1.50),
    ):
        value = row.get(key)
        if value is not None:
            parts.append(_clip01(0.5 + float(value) / (2 * scale)))
    if row.get("above_50dma"):
        parts.append(0.65)
    if row.get("above_200dma"):
        parts.append(0.70)
    if not parts:
        return 0.25
    return float(sum(parts) / len(parts))


def _timing_score(row: dict[str, Any]) -> float:
    score = 0.50
    rsi = row.get("rsi")
    if rsi is not None:
        if 40 <= rsi <= 62:
            score += 0.20
        elif 30 <= rsi < 40:
            score += 0.10
        elif rsi > 75:
            score -= 0.25
        elif rsi < 25:
            score -= 0.10
    if row.get("pullback_flag"):
        score += 0.15
    if row.get("breakout_flag"):
        score += 0.12
    if row.get("extension_flag"):
        score -= 0.20
    volume_z = row.get("volume_zscore")
    if volume_z is not None and volume_z > 1.0:
        score += 0.05
    return _clip01(score)


def _risk_penalty(row: dict[str, Any]) -> float:
    penalty = 0.0
    vol = row.get("realized_volatility")
    if vol is not None:
        penalty += max(0.0, min(0.25, (float(vol) - 0.25) * 0.35))
    drawdown = row.get("drawdown_from_high")
    if drawdown is not None and drawdown < -0.25:
        penalty += min(0.20, abs(float(drawdown)) * 0.35)
    beta = row.get("beta_spy")
    if beta is not None and beta > 1.8:
        penalty += 0.05
    if row.get("event_risk"):
        penalty += float(row["event_risk"])
    if row.get("high_risk_symbol_flag"):
        penalty += 0.12
    penalty += min(0.15, 0.03 * int(row.get("missing_data_count") or 0))
    return _clip01(penalty)


def _timing_multiplier(row: dict[str, Any]) -> float:
    if row.get("extension_flag"):
        return 0.70
    if row.get("pullback_flag") or row.get("breakout_flag"):
        return 1.05
    return 1.0


def _regime_fit(row: dict[str, Any], regime: str) -> float:
    category = row.get("category") or ""
    theme = row.get("theme") or ""
    if regime == "RISK_ON":
        if category in ("sector", "industry", "theme", "factor") and theme not in ("Short Treasuries", "Gold"):
            return 0.70
        return 0.45
    if regime == "NEUTRAL":
        if category in ("factor", "defensive", "rates"):
            return 0.65
        return 0.50
    if regime in ("FEAR", "STRESS"):
        if category in ("defensive", "rates") or theme in ("Gold", "Short Treasuries", "Long Treasuries"):
            return 0.80
        return 0.25
    return 0.10


def _diversification_score(row: dict[str, Any]) -> float:
    corr_spy = row.get("correlation_spy")
    corr_qqq = row.get("correlation_qqq")
    corr_port = row.get("correlation_portfolio")
    values = [abs(float(v)) for v in (corr_spy, corr_qqq, corr_port) if v is not None]
    if not values:
        return 0.50
    avg = sum(values) / len(values)
    return _clip01(1.0 - avg)


def _explain(
    row: dict[str, Any],
    information: float,
    leadership: float,
    timing: float,
    risk_penalty: float,
    wait: bool,
    regime_fit: float | None = None,
    diversification: float | None = None,
) -> list[str]:
    reasons = []
    if information >= 0.60:
        reasons.append("information score is above neutral")
    if leadership >= 0.60:
        reasons.append("leadership and relative-strength inputs are supportive")
    if timing < 0.35:
        reasons.append("timing is weak")
    if wait:
        reasons.append("strong information but poor timing: wait/reduce target")
    if risk_penalty > 0.12:
        reasons.append("risk penalty reduced score")
    if regime_fit is not None and regime_fit >= 0.65:
        reasons.append("ETF has favorable regime fit")
    if diversification is not None and diversification >= 0.55:
        reasons.append("ETF adds diversification versus anchors/current book")
    if row.get("data_quality_flag") not in (None, "ok"):
        reasons.append(f"data quality flag: {row.get('data_quality_flag')}")
    return reasons or ["neutral composite score"]


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
