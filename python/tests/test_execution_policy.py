from execution_policy import decide_execution


def test_black_risk_halts_execution():
    payload = decide_execution(
        {"weights": {}},
        {"target_allocations": [{"symbol": "SPY", "weight": 1.0}]},
        {"risk_status": {"light": "BLACK"}},
        [],
        "2024-01-31",
    )
    assert payload["execution_decision"]["decision"] == "DATA_HALT"


def test_small_drift_no_trade():
    payload = decide_execution(
        {"weights": {"SPY": 0.51}, "positions": {"SPY": {}}},
        {"target_allocations": [{"symbol": "SPY", "weight": 0.50}]},
        {"risk_status": {"light": "GREEN"}},
        [],
        "2024-01-31",
    )
    assert payload["execution_decision"]["decision"] == "NO_TRADE"


def test_initial_cash_allocation_can_exceed_turnover_cap():
    payload = decide_execution(
        {"weights": {"CASH": 1.0}, "positions": {}},
        {"target_allocations": [{"symbol": "SPY", "weight": 1.0}]},
        {"risk_status": {"light": "GREEN"}},
        [],
        "2024-01-31",
    )
    assert payload["execution_decision"]["decision"] == "EXECUTE"
