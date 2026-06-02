from universe import build_universe


def test_universe_contains_core_anchors_and_dynamic_etfs():
    payload = build_universe(as_of="2024-01-31")
    rows = {row["symbol"]: row for row in payload["candidates"]}
    assert rows["SPY"]["asset_type"] == "benchmark"
    assert rows["QQQ"]["asset_type"] == "benchmark"
    assert rows["SGOV"]["asset_type"] == "cash_proxy"
    assert rows["SMH"]["reason_included"] == "dynamic_etf_pool_candidate"
    assert "permanent" not in rows["SMH"]["reason_included"]
