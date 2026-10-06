"""Run daily, replay, benchmarks, page contracts and validators locally."""
from __future__ import annotations
import sys
from datetime import date, timedelta
from config import DATA_DIR
from data_contracts import read_json
from yfinance_client import latest_completed_market_date
from market_data import MarketDataClient
from portfolio import PaperPortfolio
from universe import build_universe, candidate_symbols
import run_daily
import update_production_replay_curve
import update_public_benchmarks
import build_production_public_data
import validate_outputs
import validate_watermarks
import validate_dashboard_data


def main():
    if not (DATA_DIR / "migration_provenance.json").exists():
        raise SystemExit("Initialize an explicit trusted baseline before running the replacement pipeline")
    as_of = latest_completed_market_date()
    client = MarketDataClient()
    portfolio = PaperPortfolio.load()
    replay = read_json(DATA_DIR / "production_replay_curve.json", {})
    base = replay.get("extension_base", {})
    allocation = base.get("allocation", {})
    if not allocation or not base.get("date"):
        raise SystemExit("DATA_HALT: missing explicit replay base; no portfolio writes")
    universe = build_universe(as_of, client, list(portfolio.positions))
    # Validate all three data requirements before the daily portfolio can move.
    requirements = [
        ('forward', candidate_symbols(universe), (date.fromisoformat(as_of) - timedelta(days=420)).isoformat()),
        ('replay', sorted(set(allocation) - {'CASH'}), base['date']),
        ('benchmark', update_public_benchmarks.BENCHMARK_SYMBOLS, '2022-01-03'),
    ]
    for phase, symbols, start in requirements:
        _, health = client.load_price_history(symbols, start, as_of, optional_symbols=set())
        if not health['ok']:
            run_daily.halt_before_valuation(portfolio, {**health, 'failed_pipeline_phase': phase}, as_of, client)
            raise SystemExit('DATA_HALT: preflight failed; no portfolio or curve updates')
    run_daily.main(as_of, client)
    if not read_json(DATA_DIR / "system_status.json", {}).get("data_health", {}).get("ok"):
        raise SystemExit("DATA_HALT: remaining pipeline stages were not run")
    prior_argv = sys.argv
    try:
        sys.argv = ["update_production_replay_curve", "--end-date", as_of]
        update_production_replay_curve.main()
        sys.argv = ["update_public_benchmarks", "--end-date", as_of]
        update_public_benchmarks.main()
    finally:
        sys.argv = prior_argv
    build_production_public_data.main()
    validate_outputs.main()
    validate_watermarks.main()
    validate_dashboard_data.main()
    print(f"PIPELINE_PASS {as_of}; private outputs at {DATA_DIR}")


if __name__ == "__main__":
    main()
