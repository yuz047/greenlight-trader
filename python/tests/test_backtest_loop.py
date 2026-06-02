from backtest import run_backtest


def test_short_backtest_smoke():
    payload = run_backtest(
        "2023-01-03",
        "2024-01-12",
        train_start="2023-01-03",
        train_end="2023-12-29",
        invest_start="2024-01-02",
        max_symbols=8,
        allow_synthetic_trading=True,
        ai_memo_mode="off",
        step_days=3,
        train_step_days=10,
    )
    assert payload["equity_curve"]
    assert payload["benchmark_verdict"] is not None
    assert payload["rolling_training"]["updated_every_replay_day"] is True
