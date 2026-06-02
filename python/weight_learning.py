"""Constrained feature-weight learning."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from config import DATA_DIR, DEFAULT_ETF_SCORE_WEIGHTS, DEFAULT_STOCK_SCORE_WEIGHTS
from data_contracts import write_json
from watermark import ML_ESTIMATED_OUTPUT, add_watermark, watermarked_text


STOCK_FEATURES = ["information", "leadership", "timing"]
ETF_FEATURES = ["leadership", "regime_fit", "diversification", "timing"]


def learn_weights(
    training_rows: list[dict[str, Any]],
    asset_type: str = "stock",
    target_column: str = "forward_20d_alpha_vs_spy",
    method: str = "ridge",
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    features = STOCK_FEATURES if asset_type == "stock" else ETF_FEATURES
    defaults = DEFAULT_STOCK_SCORE_WEIGHTS if asset_type == "stock" else DEFAULT_ETF_SCORE_WEIGHTS
    frame = pd.DataFrame(training_rows)
    if frame.empty or target_column not in frame or not all(col in frame for col in features):
        return add_watermark(
            {
                "as_of": as_of,
                "asset_type": asset_type,
                "method": method,
                "approved_for_production": False,
                "weights": defaults,
                "reason": "insufficient_training_data_default_weights_retained",
            },
            ML_ESTIMATED_OUTPUT,
        )

    clean = frame[features + [target_column]].dropna()
    if len(clean) < max(20, len(features) * 8):
        return add_watermark(
            {
                "as_of": as_of,
                "asset_type": asset_type,
                "method": method,
                "approved_for_production": False,
                "weights": defaults,
                "reason": "too_few_clean_rows_default_weights_retained",
                "clean_rows": len(clean),
            },
            ML_ESTIMATED_OUTPUT,
        )

    x = clean[features].to_numpy(dtype=float)
    y = clean[target_column].to_numpy(dtype=float)
    x = (x - x.mean(axis=0)) / np.where(x.std(axis=0) == 0, 1, x.std(axis=0))
    lam = 1.0 if method == "ridge" else 0.1
    coef = np.linalg.pinv(x.T @ x + lam * np.eye(x.shape[1])) @ x.T @ y
    coef = np.maximum(coef, 0)
    if coef.sum() <= 0:
        weights = defaults
    else:
        coef = coef / coef.sum()
        coef = np.minimum(coef, 0.65)
        coef = coef / coef.sum()
        weights = {feature: round(float(weight), 6) for feature, weight in zip(features, coef)}

    validation = _validation_summary(clean, features, weights, target_column)
    return add_watermark(
        {
            "as_of": as_of,
            "asset_type": asset_type,
            "method": method,
            "approved_for_production": False,
            "weights": weights,
            "constraints": {
                "non_negative": True,
                "sum_to_one": True,
                "max_feature_weight_cap": 0.65,
                "human_approval_required": True,
            },
            "validation": validation,
            "targets": [
                "forward_20d_alpha_vs_spy",
                "forward_60d_alpha_vs_spy",
                "probability_of_outperforming_spy",
                "risk_adjusted_forward_return",
                "drawdown_contribution",
            ],
        },
        ML_ESTIMATED_OUTPUT,
    )


def write_learning_report(stock_result: dict[str, Any], etf_result: dict[str, Any]) -> None:
    payload = add_watermark({"stock": stock_result, "etf": etf_result}, ML_ESTIMATED_OUTPUT)
    write_json(DATA_DIR / "learning_report.json", payload)
    body = (
        "Stock weights: "
        f"{stock_result.get('weights')}\n\n"
        "ETF weights: "
        f"{etf_result.get('weights')}\n\n"
        "Production promotion: blocked until human approval and out-of-sample validation pass."
    )
    (DATA_DIR / "learning_report.md").write_text(watermarked_text("Learning Report", body, ML_ESTIMATED_OUTPUT))


def _validation_summary(frame: pd.DataFrame, features: list[str], weights: dict[str, float], target: str) -> dict[str, Any]:
    score = sum(frame[feature] * weights.get(feature, 0.0) for feature in features)
    corr = float(score.corr(frame[target])) if len(frame) > 2 else 0.0
    return {
        "clean_rows": int(len(frame)),
        "rank_ic_proxy": round(corr, 6) if np.isfinite(corr) else 0.0,
        "out_of_sample_required": True,
    }
