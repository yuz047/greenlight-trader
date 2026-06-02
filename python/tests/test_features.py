from massive_client import bars_to_frame, synthetic_price_bars
from features import compute_features


def _history(symbols):
    return {symbol: bars_to_frame(synthetic_price_bars(symbol, "2023-01-01", "2024-02-15")) for symbol in symbols}


def test_features_compute_technical_fields():
    universe = {
        "candidates": [
            {"symbol": "SPY", "asset_type": "benchmark", "sector": "Broad", "theme": "S&P 500"},
            {"symbol": "QQQ", "asset_type": "benchmark", "sector": "Growth", "theme": "Nasdaq"},
            {"symbol": "AAPL", "asset_type": "stock", "sector": "Technology", "theme": None},
        ]
    }
    payload = compute_features(universe, _history(["SPY", "QQQ", "AAPL"]), "2024-01-31")
    aapl = next(row for row in payload["feature_rows"] if row["symbol"] == "AAPL")
    assert aapl["price"] is not None
    assert aapl["momentum_63d"] is not None
    assert aapl["rsi"] is not None
    assert aapl["data_quality_flag"] == "synthetic"
