from etf_selector import select_dynamic_etfs


def test_etf_selector_selects_earned_etf_and_rejects_clone():
    scores = {
        "as_of": "2024-01-31",
        "scores": [
            {"symbol": "XLK", "asset_type": "etf", "final_score": 0.7, "investable_flag": True, "diversification_score": 0.4, "leadership_score": 0.8, "explanations": []},
            {"symbol": "CLONE", "asset_type": "etf", "final_score": 0.65, "investable_flag": True, "diversification_score": 0.05, "leadership_score": 0.4, "explanations": []},
        ],
    }
    features = {
        "feature_rows": [
            {"symbol": "XLK", "asset_type": "etf", "correlation_spy": 0.7, "correlation_qqq": 0.8, "category": "sector", "theme": "Technology"},
            {"symbol": "CLONE", "asset_type": "etf", "correlation_spy": 0.99, "correlation_qqq": 0.98, "category": "broad", "theme": "Clone"},
        ]
    }
    payload = select_dynamic_etfs(scores, features, {"regime": "RISK_ON"}, "2024-01-31")
    assert [row["symbol"] for row in payload["selected_etfs"]] == ["XLK"]
    assert any(row["symbol"] == "CLONE" and "duplicates" in row["reason"] for row in payload["rejected_etfs"])
