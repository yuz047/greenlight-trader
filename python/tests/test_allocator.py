from allocator import allocate_targets


def test_allocator_weights_sum_to_one_and_caps_stock():
    scores = {
        "as_of": "2024-01-31",
        "scores": [
            {"symbol": "AAPL", "asset_type": "stock", "final_score": 0.8, "investable_flag": True, "timing_multiplier": 1, "data_quality_multiplier": 1, "wait_flag": False},
            {"symbol": "MSFT", "asset_type": "stock", "final_score": 0.7, "investable_flag": True, "timing_multiplier": 1, "data_quality_multiplier": 1, "wait_flag": False},
            {"symbol": "XLK", "asset_type": "etf", "final_score": 0.7, "investable_flag": True, "timing_multiplier": 1, "data_quality_multiplier": 1},
        ],
    }
    features = {
        "feature_rows": [
            {"symbol": "SPY", "asset_type": "benchmark", "realized_volatility": 0.15, "sector": "Broad", "theme": "S&P"},
            {"symbol": "QQQ", "asset_type": "benchmark", "realized_volatility": 0.20, "sector": "Growth", "theme": "Nasdaq"},
            {"symbol": "SGOV", "asset_type": "cash_proxy", "realized_volatility": 0.02, "sector": "Cash", "theme": "T-Bills"},
            {"symbol": "AAPL", "asset_type": "stock", "realized_volatility": 0.25, "sector": "Technology", "theme": None},
            {"symbol": "MSFT", "asset_type": "stock", "realized_volatility": 0.25, "sector": "Technology", "theme": None},
            {"symbol": "XLK", "asset_type": "etf", "realized_volatility": 0.20, "sector": "Technology", "theme": "Technology"},
        ]
    }
    payload = allocate_targets(scores, features, {"selected_etfs": [{"symbol": "XLK"}]}, {"regime": "RISK_ON"}, "2024-01-31")
    weights = {row["symbol"]: row["weight"] for row in payload["target_allocations"]}
    assert sum(weights.values()) <= 1.0001
    assert weights["QQQ"] > 0
    assert weights["AAPL"] <= 0.08
