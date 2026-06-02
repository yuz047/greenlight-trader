from risk import evaluate_risk


def test_synthetic_data_forces_black():
    payload = evaluate_risk(
        {"nav": 5000, "peak_nav": 5000, "weights": {}},
        {"target_allocations": []},
        {"ok": False, "synthetic": True},
        {"regime": "DATA_FAILURE"},
        "2024-01-31",
    )
    assert payload["risk_status"]["light"] == "BLACK"


def test_drawdown_breach_is_red_when_data_ok():
    payload = evaluate_risk(
        {"nav": 3500, "peak_nav": 5000, "weights": {}},
        {"target_allocations": []},
        {"ok": True, "synthetic": False},
        {"regime": "RISK_ON", "allow_new_alpha_entries": True},
        "2024-01-31",
    )
    assert payload["risk_status"]["light"] == "RED"
