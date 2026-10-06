import pandas as pd
import numpy as np
import pytest
import backtest
from backtest import run_backtest
from yfinance_client import YFinanceClient, expected_sessions


def test_short_backtest_smoke(monkeypatch, tmp_path):
    # Deterministic unit-test fixture, distinct from live-cache E2E evidence.
    def fixture_prices(symbol, start, end):
        dates = expected_sessions(start, end)
        close = pd.Series([100 + n / 10 + .2 * np.sin(n / 3) for n in range(len(dates))], index=dates)
        return pd.DataFrame({'Open': close, 'High': close + 1, 'Low': close - 1,
            'Close': close, 'Adj Close': close, 'Volume': 1_000_000,
            'Dividends': 0, 'Stock Splits': 0})
    monkeypatch.setattr(backtest, 'MarketDataClient', lambda: YFinanceClient(cache_dir=tmp_path, fetcher=fixture_prices, request_spacing=0))
    payload = run_backtest(
        "2023-01-03",
        "2024-01-12",
        train_start="2023-01-03",
        train_end="2023-12-29",
        invest_start="2024-01-02",
        max_symbols=8,
        allow_synthetic_trading=False,
        ai_memo_mode="off",
        step_days=3,
        train_step_days=10,
    )
    assert payload["equity_curve"]
    assert payload["benchmark_verdict"] is not None
    assert payload["rolling_training"]["updated_every_replay_day"] is True


def test_synthetic_trading_is_rejected():
    with pytest.raises(ValueError, match='Synthetic trading is disabled'):
        run_backtest('2024-01-01', '2024-02-01', allow_synthetic_trading=True)
