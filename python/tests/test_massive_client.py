from data_contracts import PriceBar
from massive_client import MassiveClient, bars_to_frame, merge_price_bars, synthetic_price_bars


def test_synthetic_bars_are_flagged():
    bars = synthetic_price_bars("SPY", "2024-01-01", "2024-01-31")
    assert bars
    assert {bar.data_quality_flag for bar in bars} == {"synthetic"}
    frame = bars_to_frame(bars)
    assert not frame.empty
    assert "close" in frame


def test_missing_key_marks_endpoint_unavailable(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    client = MassiveClient(api_key=None)
    assert not client.has_key
    assert client.get_aggregates("SPY", "2024-01-01", "2024-01-02") == []
    report = client.availability_report()
    assert report
    assert next(iter(report.values()))["available"] is False


def test_merge_price_bars_prefers_primary_overlap():
    secondary = [
        PriceBar("SPY", "2020-01-02", 1, 1, 1, 1, 100, source="yahoo.price", data_quality_flag="secondary_source"),
        PriceBar("SPY", "2020-01-03", 2, 2, 2, 2, 100, source="yahoo.price", data_quality_flag="secondary_source"),
    ]
    primary = [
        PriceBar("SPY", "2020-01-03", 3, 3, 3, 3, 100, source="massive", data_quality_flag="ok"),
    ]
    merged = merge_price_bars(primary=primary, secondary=secondary)
    assert [bar.date for bar in merged] == ["2020-01-02", "2020-01-03"]
    assert merged[-1].source == "massive"
