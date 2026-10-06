"""Risk must refer to the marked account, and missing valuation paths stay unknown."""
import json
import hashlib

import pandas as pd
import pytest

import run_daily
import validate_outputs
from portfolio import PaperPortfolio, Position
from risk import evaluate_risk
from strategy_benchmarks import buy_and_hold
from yfinance_client import YFinanceClient, expected_sessions
from test_yfinance_migration import patch_runtime_dir, prices


def test_daily_decision_uses_advanced_benchmark_and_final_risk_includes_costs(tmp_path, monkeypatch):
    patch_runtime_dir(monkeypatch, tmp_path)
    account = PaperPortfolio(cash=500, positions={'QQQ': Position('QQQ', 45, 100, 100)},
                             benchmark_equity=5000, valuation_date='2026-06-26',
                             recovery_provenance={'date': '2026-06-26'})
    account.save()
    monkeypatch.setattr(run_daily, 'build_universe', lambda **kwargs: {'candidates': [{'symbol':'SPY'},{'symbol':'QQQ'}]})
    monkeypatch.setattr(run_daily, 'candidate_symbols', lambda universe: ['SPY','QQQ'])
    monkeypatch.setattr(run_daily, 'compute_features', lambda *args: {})
    monkeypatch.setattr(run_daily, 'determine_regime', lambda *args: {'regime':'RISK_ON','allow_new_alpha_entries':True})
    monkeypatch.setattr(run_daily, 'score_candidates', lambda *args, **kwargs: {})
    monkeypatch.setattr(run_daily, 'select_dynamic_etfs', lambda *args: {})
    monkeypatch.setattr(run_daily, 'allocate_targets', lambda *args: {'target_allocations': []})
    seen = []
    def decision(portfolio, targets, risk, history, as_of):
        seen.append(risk['risk_status'])
        return {'execution_decision': {'decision':'EXECUTE'}}
    monkeypatch.setattr(run_daily, 'decide_execution', decision)
    def trade_with_fee(portfolio, *args):
        portfolio.cash -= 150
        return [{'symbol':'QQQ','transaction_cost':150}]
    monkeypatch.setattr(PaperPortfolio, 'rebalance_to_targets', trade_with_fee)
    monkeypatch.setattr(run_daily, 'run_benchmarks', lambda *args, **kwargs: {})
    monkeypatch.setattr(run_daily, 'build_decision_log', lambda *args: {})
    monkeypatch.setattr(run_daily, 'append_decision_log', lambda *args: {'logs': []})
    def fetch(symbol, start, end):
        frame = prices(start, end)
        final = 120 if symbol=='SPY' else 110
        frame.loc[frame.index[-1], ['Open','High','Low','Close']] = [final,final+1,final-1,final]
        return frame
    client = YFinanceClient(tmp_path/'cache', fetcher=fetch, request_spacing=0)
    run_daily.main('2026-10-05', client=client)
    assert seen[0]['valuation_basis']['benchmark_equity'] == 6000
    assert seen[0]['valuation_basis']['nav'] == 5450
    assert seen[0]['relative_drawdown_pct'] == pytest.approx(.11)
    assert seen[0]['light'] == 'YELLOW'
    final = json.loads((tmp_path/'risk_status.json').read_text())['risk_status']
    assert final['valuation_basis']['nav'] == 5300
    assert final['valuation_basis']['benchmark_equity'] == 6000
    assert final['relative_drawdown_pct'] == pytest.approx(.14)
    assert final['light'] == 'RED'
    assert final['valuation_basis']['phase'] == 'post_execution'
    assert final['absolute_drawdown_pct'] is None
    assert not validate_outputs.valuation_consistency_failures()
    before = hashlib.sha256((tmp_path/'portfolio_state.json').read_bytes()).hexdigest()
    run_daily.main('2026-10-05', client=client)
    assert hashlib.sha256((tmp_path/'portfolio_state.json').read_bytes()).hexdigest() == before
    assert len(seen)==1


def test_missing_recovery_path_never_claims_full_period_zero_drawdown(tmp_path, monkeypatch):
    patch_runtime_dir(monkeypatch, tmp_path)
    account = PaperPortfolio(cash=5100, peak_nav=5100, valuation_date='2026-10-05',
                             recovery_provenance={'date':'2026-06-26'})
    run_daily._mark_recovery_drawdown_gap(account, '2026-10-05')
    state=account.snapshot()
    risk=evaluate_risk(state, {}, {'ok':True}, {'regime':'RISK_ON'}, '2026-10-05')['risk_status']
    assert state['absolute_drawdown_pct'] is None and risk['absolute_drawdown_pct'] is None
    assert risk['observed_absolute_drawdown_pct']==0
    assert risk['drawdown_definition']=='known_saved_snapshots_only'
    assert risk['drawdown_history']['missing_session_count']==len(expected_sessions('2026-06-26','2026-10-05'))-2


def test_validator_rejects_old_benchmark_risk_result(tmp_path, monkeypatch):
    patch_runtime_dir(monkeypatch, tmp_path)
    portfolio={'date':'2026-10-05','nav':5250,'benchmark_equity':5322,'relative_drawdown_pct':.022646,
               'absolute_drawdown_pct':None,'drawdown_history':{'status':'incomplete_recovery_gap'}}
    risk={'as_of':'2026-10-05','valuation_basis':{'as_of':'2026-10-05','nav':5250,'benchmark_equity':5261},
          'relative_drawdown_pct':.010505,'absolute_drawdown_pct':0,'drawdown_history':portfolio['drawdown_history']}
    for name,value in [('system_status.json',{'valuation_contract_version':2,'data_health':{'ok':True},'latest_run_date':'2026-10-05'}),
                       ('portfolio_state.json',portfolio),('risk_status.json',{'risk_status':risk})]:
        (tmp_path/name).write_text(json.dumps(value))
    failures=validate_outputs.valuation_consistency_failures()
    assert any('benchmark_equity' in x for x in failures)
    assert any('relative drawdown' in x for x in failures)
    assert any('full-period' in x for x in failures)


@pytest.mark.parametrize('symbol',['SPY','QQQ'])
def test_benchmark_keeps_same_price_return_dividend_convention(symbol):
    frame=pd.DataFrame({'close':[100.,99.], 'adj_close':[95.,95.], 'dividends':[0.,1.]},
                       index=pd.to_datetime(['2026-10-01','2026-10-02']))
    curve=buy_and_hold(frame,5000)
    assert curve.iloc[-1]==4950
