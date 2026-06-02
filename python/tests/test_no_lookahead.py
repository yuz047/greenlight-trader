from massive_client import bars_to_frame, synthetic_price_bars
from features import compute_features


def test_feature_price_uses_as_of_not_future():
    frame = bars_to_frame(synthetic_price_bars("AAPL", "2023-01-01", "2024-02-15"))
    spy = bars_to_frame(synthetic_price_bars("SPY", "2023-01-01", "2024-02-15"))
    qqq = bars_to_frame(synthetic_price_bars("QQQ", "2023-01-01", "2024-02-15"))
    as_of = "2024-01-10"
    expected = float(frame.loc[frame.index <= as_of]["close"].iloc[-1])
    payload = compute_features(
        {"candidates": [{"symbol": "AAPL", "asset_type": "stock"}, {"symbol": "SPY", "asset_type": "benchmark"}, {"symbol": "QQQ", "asset_type": "benchmark"}]},
        {"AAPL": frame, "SPY": spy, "QQQ": qqq},
        as_of,
    )
    row = next(item for item in payload["feature_rows"] if item["symbol"] == "AAPL")
    assert row["price"] == expected
    assert row["price"] != float(frame["close"].iloc[-1])
