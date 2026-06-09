"""Refresh public benchmark curves through a requested market date."""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from massive_client import MassiveClient, bars_to_frame, yahoo_price_bars
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
    client = MassiveClient()
    price_history, data_health = client.load_price_history(
        BENCHMARK_SYMBOLS,
        args.start_date,
        end_date,
        allow_synthetic=False,
        allow_secondary_price_fallback=True,
        optional_symbols=set(BENCHMARK_SYMBOLS) - {"SPY", "QQQ"},
    )
    _fill_missing_with_yahoo(price_history, BENCHMARK_SYMBOLS, args.start_date, end_date)
    if price_history.get("SPY") is None or price_history["SPY"].empty:
        raise SystemExit("SPY benchmark history is required")
    if price_history.get("QQQ") is None or price_history["QQQ"].empty:
        raise SystemExit("QQQ benchmark history is required")
    payload = run_benchmarks(price_history, as_of=end_date)
    payload["data_health"] = data_health
    write_benchmark_outputs(payload)
    spy_end = payload["snapshots"]["SPY_buy_hold"][-1]
    print(f"updated public benchmarks through {spy_end['date']}, SPY={spy_end['equity']:.2f}")


def _fill_missing_with_yahoo(price_history, symbols: list[str], start_date: str, end_date: str) -> None:
    for symbol in symbols:
        frame = price_history.get(symbol)
        if frame is not None and not frame.empty:
            continue
        bars = yahoo_price_bars(symbol, start_date, end_date)
        if bars:
            price_history[symbol] = bars_to_frame(bars)


def latest_completed_market_date() -> str:
    today = date.today()
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate.isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2022-01-03")
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
