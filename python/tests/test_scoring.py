from scoring import score_candidates


def test_stock_bad_timing_waits_even_with_information():
    features = {
        "as_of": "2024-01-31",
        "feature_rows": [
            {
                "symbol": "TEST",
                "asset_type": "stock",
                "investable_flag": True,
                "data_quality_multiplier": 1.0,
                "analyst_upside": 0.3,
                "relative_strength_spy": 0.10,
                "momentum_63d": 0.15,
                "rsi": 82,
                "extension_flag": True,
                "realized_volatility": 0.20,
                "missing_data_count": 0,
            }
        ],
    }
    scores = score_candidates(features, {"regime": "RISK_ON"})
    row = scores["scores"][0]
    assert row["wait_flag"] is True
    assert row["timing_multiplier"] < 1


def test_etf_score_uses_regime_fit_not_fundamentals():
    features = {
        "as_of": "2024-01-31",
        "feature_rows": [
            {
                "symbol": "XLK",
                "asset_type": "etf",
                "category": "sector",
                "theme": "Technology",
                "investable_flag": True,
                "data_quality_multiplier": 1.0,
                "relative_strength_spy": 0.08,
                "momentum_63d": 0.12,
                "rsi": 55,
                "realized_volatility": 0.18,
                "correlation_spy": 0.7,
                "missing_data_count": 0,
            }
        ],
    }
    scores = score_candidates(features, {"regime": "RISK_ON"})
    row = scores["scores"][0]
    assert row["regime_fit_score"] > 0
    assert row["information_score"] == 0
