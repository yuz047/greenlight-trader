"""Refresh public benchmark curves through a requested market date."""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from market_data import MarketDataClient
from yfinance_client import latest_completed_market_date
from strategy_benchmarks import run_benchmarks, write_benchmark_outputs


BENCHMARK_SYMBOLS = [
    "SPY",
    "QQQ",
    "^VIX",
    "XLK",
    "XLE",
    "XLF",
    "XLV",
    "SMH",
    "IWM",
    "TLT",
    "GLD",
    "MTUM",
    "QUAL",
]


def main() -> None:
    args = parse_args()
    end_date = args.end_date or latest_completed_market_date()
    client = MarketDataClient()
    price_history, data_health = client.load_price_history(
        BENCHMARK_SYMBOLS,
        args.start_date,
        end_date,
        allow_synthetic=False,
        allow_secondary_price_fallback=True,
        optional_symbols=set(),
    )
    if not data_health["ok"]:
        raise SystemExit("DATA_HALT: benchmarks have missing/stale prices; no output was written")
    if price_history.get("SPY") is None or price_history["SPY"].empty:
        raise SystemExit("SPY benchmark history is required")
    if price_history.get("QQQ") is None or price_history["QQQ"].empty:
        raise SystemExit("QQQ benchmark history is required")
    payload = run_benchmarks(price_history, as_of=end_date)
    payload["data_health"] = data_health
    write_benchmark_outputs(payload)
    spy_end = payload["snapshots"]["SPY_buy_hold"][-1]
    print(f"updated public benchmarks through {spy_end['date']}, SPY={spy_end['equity']:.2f}")


def latest_completed_market_date() -> str:
    return latest_completed_market_date()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2022-01-03")
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
