from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

import run_daily
from portfolio import PaperPortfolio, Position
from yfinance_client import YFinanceClient, expected_sessions, latest_completed_market_date, normalize_history


def patch_runtime_dir(monkeypatch, tmp_path):
    root = Path(run_daily.__file__).resolve().parent
    for module in list(sys.modules.values()):
        location = getattr(module, '__file__', None)
        if location and Path(location).resolve().is_relative_to(root) and hasattr(module, 'DATA_DIR'):
            monkeypatch.setattr(module, 'DATA_DIR', tmp_path)


def prices(start, end, symbol='SPY'):
    days = expected_sessions(start, end)
    return pd.DataFrame({'Open': 100., 'High': 101., 'Low': 99., 'Close': 100.,
        'Adj Close': 90., 'Volume': 0 if symbol == '^VIX' else 1_000_000,
        'Dividends': 0., 'Stock Splits': 0.}, index=days)


def test_split_only_research_and_private_cache_without_massive_key(tmp_path):
    calls = []
    def fetch(symbol, start, end):
        calls.append(symbol)
        return prices(start, end)
    client = YFinanceClient(tmp_path, fetcher=fetch, request_spacing=0)
    bars = client.get_aggregates('SPY', '2026-10-01', '2026-10-05')
    assert bars[-1].close == 100  # Never substitute dividend-adjusted 90.
    assert bars[-1].vwap is None
    client.get_aggregates('SPY', '2026-10-02', '2026-10-05')
    assert calls == ['SPY']
    assert client.availability_report()['history/SPY']['reason'] == 'cache_hit_split_adjusted'


@pytest.mark.parametrize('fault', ['empty', 'stale', 'partial'])
def test_price_faults_cannot_be_healthy(tmp_path, fault):
    def fetch(symbol, start, end):
        frame = prices(start, end)
        if fault == 'empty': return frame.iloc[:0]
        if fault == 'stale': return frame.iloc[:-1]
        frame.iloc[-1, frame.columns.get_loc('High')] = float('nan')
        return frame
    client = YFinanceClient(tmp_path, fetcher=fetch, request_spacing=0)
    _, health = client.load_price_history(['SPY'], '2026-10-01', '2026-10-05', allow_synthetic=True, optional_symbols=set())
    assert not health['ok'] and not health['synthetic']
    assert health['missing_critical_symbols'] == ['SPY']
    assert health['fallback_symbols'] == []


@pytest.mark.parametrize('status', [403, 429])
def test_access_and_rate_limits_do_not_trigger_retry_or_fallback(tmp_path, status):
    calls = []
    class HTTPFault(Exception): status_code = status
    def fetch(*args):
        calls.append(args[0])
        raise HTTPFault()
    client = YFinanceClient(tmp_path, fetcher=fetch, request_spacing=0)
    _, health = client.load_price_history(['SPY', 'QQQ'], '2026-10-01', '2026-10-05', optional_symbols=set())
    assert calls == ['SPY']
    assert not health['ok'] and not health['synthetic']
    if status == 429:
        cooldown = json.loads((tmp_path / 'cooldown.json').read_text())
        assert datetime.fromisoformat(cooldown['retry_after']) > datetime.now(timezone.utc)


@pytest.mark.parametrize('status', [403, 429])
def test_transport_rejects_before_yfinance_cookie_retry(tmp_path, monkeypatch, status):
    from types import SimpleNamespace
    from yfinance.data import YfData
    from yfinance_client import UpstreamHTTPError
    client = YFinanceClient(tmp_path, request_spacing=0)
    calls = []
    def sender(*args, **kwargs):
        calls.append('request')
        return SimpleNamespace(status_code=status)
    client.session.request = lambda *args, **kwargs: client._guarded_request(sender, *args, **kwargs)
    data = YfData(session=client.session)
    monkeypatch.setattr(data, '_get_cookie_and_crumb', lambda *args: (None, 'basic'))
    with pytest.raises(UpstreamHTTPError):
        data._make_request('https://query1.finance.yahoo.com/v8/finance/chart/SPY', client.session.get)
    with pytest.raises(UpstreamHTTPError):
        client.session.get('https://query1.finance.yahoo.com/v8/finance/chart/QQQ')
    assert calls == ['request']


def test_vix_holiday_cleanup_and_alias(tmp_path):
    def fetch(symbol, start, end):
        assert symbol == '^VIX'
        frame = prices(start, end, symbol)
        frame.loc[pd.Timestamp('2026-09-07')] = float('nan')
        frame.loc[pd.Timestamp('2026-09-07'), 'Volume'] = 0
        return frame
    client = YFinanceClient(tmp_path, fetcher=fetch, request_spacing=0)
    frame, health = client.load_price_history(['I:VIX'], '2026-09-04', '2026-09-08', optional_symbols=set())
    assert health['ok']
    assert len(frame['I:VIX']) == 2
    assert not frame['I:VIX']['close'].isna().any()


def test_exchange_calendar_respects_holidays_and_close():
    assert latest_completed_market_date(datetime(2026, 10, 6, 13, tzinfo=timezone.utc)) == '2026-10-05'
    assert latest_completed_market_date(datetime(2026, 10, 6, 21, tzinfo=timezone.utc)) == '2026-10-06'
    assert latest_completed_market_date(datetime(2026, 9, 7, 21, tzinfo=timezone.utc)) == '2026-09-04'


def test_actual_holdings_split_and_dividend_policy_are_idempotent():
    portfolio = PaperPortfolio(cash=0, positions={'TEST': Position('TEST', 10, 90, 100)}, corporate_action_date='2026-10-01')
    before = portfolio.nav()
    events = pd.DataFrame({'Dividends': [0, 1], 'Stock Splits': [2, 0]}, index=pd.to_datetime(['2026-10-02', '2026-10-05']))
    portfolio.apply_corporate_actions({'TEST': events}, '2026-10-05')
    assert portfolio.positions['TEST'].shares == 20
    assert portfolio.positions['TEST'].avg_price == 45
    assert portfolio.nav() == before and portfolio.cash == 0
    assert portfolio.corporate_action_ledger[-1]['excluded_cash_amount'] == 20
    portfolio.apply_corporate_actions({'TEST': events}, '2026-10-05')
    assert len(portfolio.corporate_action_ledger) == 2 and portfolio.positions['TEST'].shares == 20


def test_recovery_does_not_count_old_signals_as_recent_persistence():
    logs = [{'date': '2026-06-25'}, {'date': '2026-06-26'}, {'date': '2026-10-01'}, {'date': '2026-10-02'}, {'date': '2026-10-05'}]
    assert run_daily.recent_signal_history(logs[:2], '2026-10-05') == []
    assert [x['date'] for x in run_daily.recent_signal_history(logs, '2026-10-05')] == ['2026-10-01', '2026-10-02']


def test_benchmark_advances_across_gap_once():
    frame = pd.DataFrame({'close': [100., 105., 110.]}, index=pd.to_datetime(['2026-06-26', '2026-10-02', '2026-10-05']))
    portfolio = PaperPortfolio(benchmark_equity=5000, valuation_date='2026-06-26')
    run_daily._update_relative_benchmark_state(portfolio, {'SPY': frame}, portfolio.valuation_date)
    assert portfolio.benchmark_equity == pytest.approx(5500)
    from backtest import _update_relative_state
    research = PaperPortfolio(benchmark_equity=5000, valuation_date='2026-06-26')
    _update_relative_state(research, {'SPY': frame}, '2026-10-05')
    assert research.benchmark_equity == pytest.approx(5500)
    _update_relative_state(research, {'SPY': frame}, '2026-10-05')
    assert research.benchmark_equity == pytest.approx(5500)


def test_halt_precedes_every_portfolio_write(tmp_path, monkeypatch):
    patch_runtime_dir(monkeypatch, tmp_path)
    state = {'watermark': 'SYSTEMATIC_TEMPLATE_OUTPUT', 'date': '2026-10-02', 'cash': 0, 'nav': 1000,
             'benchmark_equity': 1234, 'positions': {'SPY': {'shares': 10, 'avg_price': 90, 'market_price': 100}}}
    path = tmp_path / 'portfolio_state.json'
    path.write_text(json.dumps(state))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    client = YFinanceClient(tmp_path / 'cache', fetcher=lambda *args: pd.DataFrame(), request_spacing=0)
    run_daily.main('2026-10-05', client=client)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not (tmp_path / 'snapshots.json').exists()
    assert json.loads((tmp_path / 'execution_decisions.json').read_text())['execution_decision']['decision'] == 'DATA_HALT'
    assert json.loads((tmp_path / 'system_status.json').read_text())['risk_light'] == 'BLACK'


def test_replay_preflight_fault_cannot_change_forward_portfolio(tmp_path, monkeypatch):
    import run_pipeline
    patch_runtime_dir(monkeypatch, tmp_path)
    state = {'date': '2026-06-26', 'cash': 0, 'nav': 1000, 'benchmark_equity': 1234,
             'positions': {'SPY': {'shares': 10, 'avg_price': 90, 'market_price': 100}}}
    files = {'portfolio_state.json': state, 'snapshots.json': {'snapshots': []},
             'migration_provenance.json': {},
             'production_replay_curve.json': {'extension_base': {'date': '2026-06-02', 'allocation': {'OCS': 1}}}}
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value))
    before = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files}
    def fetch(symbol, start, end):
        return pd.DataFrame() if symbol == 'OCS' else prices(start, end, symbol)
    client = YFinanceClient(tmp_path / 'cache', fetcher=fetch, request_spacing=0)
    monkeypatch.setattr(run_pipeline, 'MarketDataClient', lambda: client)
    monkeypatch.setattr(run_pipeline, 'latest_completed_market_date', lambda: '2026-10-05')
    monkeypatch.setattr(run_pipeline, 'build_universe', lambda *args: {})
    monkeypatch.setattr(run_pipeline, 'candidate_symbols', lambda *args: ['SPY'])
    with pytest.raises(SystemExit, match='preflight failed'):
        run_pipeline.main()
    assert {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files} == before
    status = json.loads((tmp_path / 'system_status.json').read_text())
    assert status['data_health']['failed_pipeline_phase'] == 'replay'
    assert json.loads((tmp_path / 'execution_decisions.json').read_text())['execution_decision']['decision'] == 'DATA_HALT'
