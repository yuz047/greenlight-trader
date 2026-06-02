"""Dynamic ETF selection and rotation."""
from __future__ import annotations

from datetime import date
from typing import Any

from config import DATA_DIR, MANDATE
from data_contracts import write_json
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


CORE_SYMBOLS = {MANDATE.benchmark, MANDATE.secondary_growth_anchor, MANDATE.defensive_anchor, "SHY"}


def select_dynamic_etfs(
    score_payload: dict[str, Any],
    feature_payload: dict[str, Any],
    regime_payload: dict[str, Any],
    as_of: str | None = None,
    max_count: int = 5,
) -> dict[str, Any]:
    as_of = as_of or score_payload.get("as_of") or date.today().isoformat()
    features = {row["symbol"]: row for row in feature_payload.get("feature_rows", [])}
    regime = regime_payload.get("regime", "DATA_FAILURE")
    selected = []
    rejected = []

    for score in score_payload.get("scores", []):
        symbol = score["symbol"]
        if symbol in CORE_SYMBOLS or score.get("asset_type") != "etf":
            continue
        row = features.get(symbol, {})
        reasons = []
        if not score.get("investable_flag"):
            rejected.append({"symbol": symbol, "reason": "not_investable", "score": score["final_score"]})
            continue
        if score["final_score"] < 0.42:
            rejected.append({"symbol": symbol, "reason": "score_below_threshold", "score": score["final_score"]})
            continue
        if _duplicates_core(row, score):
            rejected.append({"symbol": symbol, "reason": "duplicates_SPY_or_QQQ_without_useful_exposure", "score": score["final_score"]})
            continue
        if regime in ("STRESS", "DATA_FAILURE") and row.get("category") not in ("defensive", "rates"):
            rejected.append({"symbol": symbol, "reason": f"regime_{regime}_blocks_risk_etf", "score": score["final_score"]})
            continue
        reasons.extend(score.get("explanations", []))
        reasons.append("earned dynamic ETF eligibility through score")
        selected.append({"symbol": symbol, "score": score["final_score"], "sector": row.get("sector"), "theme": row.get("theme"), "category": row.get("category"), "reasons": reasons})
        if len(selected) >= max_count:
            break

    selected_symbols = {row["symbol"] for row in selected}
    for score in score_payload.get("scores", []):
        symbol = score["symbol"]
        if score.get("asset_type") == "etf" and symbol not in CORE_SYMBOLS and symbol not in selected_symbols:
            if not any(r["symbol"] == symbol for r in rejected):
                rejected.append({"symbol": symbol, "reason": "not_selected_after_rank", "score": score["final_score"]})

    return add_watermark(
        {
            "as_of": as_of,
            "regime": regime,
            "selected_etfs": selected,
            "rejected_etfs": rejected,
            "rules": [
                "No permanent sector/theme ETF.",
                "ETF must earn allocation through score.",
                "ETF is rejected if it duplicates SPY/QQQ without useful exposure.",
                "ETF allocation is capped by config.",
            ],
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def write_selected_etfs(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "selected_etfs.json", payload)


def _duplicates_core(feature_row: dict[str, Any], score: dict[str, Any]) -> bool:
    corr_spy = abs(float(feature_row.get("correlation_spy") or 0.0))
    corr_qqq = abs(float(feature_row.get("correlation_qqq") or 0.0))
    diversification = float(score.get("diversification_score") or 0.0)
    leadership = float(score.get("leadership_score") or 0.0)
    return max(corr_spy, corr_qqq) > 0.96 and diversification < 0.18 and leadership < 0.62
