import pandas as pd

from massive_client import bars_to_frame, synthetic_price_bars
from strategy_benchmarks import buy_and_hold, performance_metrics, run_benchmarks


def test_performance_metrics_include_required_fields():
    frame = bars_to_frame(synthetic_price_bars("SPY", "2024-01-01", "2024-03-31"))
    curve = buy_and_hold(frame, 5000)
    metrics = performance_metrics(curve, curve)
    assert "Sharpe" in metrics
    assert "max_relative_drawdown_vs_SPY" in metrics


def test_run_benchmarks_has_verdict():
    history = {symbol: bars_to_frame(synthetic_price_bars(symbol, "2024-01-01", "2024-03-31")) for symbol in ["SPY", "QQQ", "^VIX", "XLK"]}
    payload = run_benchmarks(history, pd.Series(dtype=float), as_of="2024-03-31")
    assert "SPY_buy_hold" in payload["metrics"]
    assert "beat_SPY" in payload["verdict"]
