"""Extend the validated production replay by marking current holdings to market."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from typing import Any

import pandas as pd

from config import DATA_DIR
from data_contracts import write_json
from market_data import MarketDataClient
from yfinance_client import latest_completed_market_date
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


REPLAY_PATH = DATA_DIR / "production_replay_curve.json"


def main() -> None:
    args = parse_args()
    replay = json.loads(REPLAY_PATH.read_text())
    base = replay.get("extension_base") or {}
    allocation = {k: float(v) for k, v in (base.get("allocation") or {}).items()}
    if not allocation:
        raise SystemExit("production_replay_curve.json missing extension_base.allocation")

    base_date = str(base.get("date") or replay.get("end_date"))
    base_nav = float(base.get("nav") or _equity_on(replay, base_date))
    end_date = args.end_date or latest_completed_market_date()
    prior_health = replay.get("extension", {}).get("data_health", {})
    if end_date <= base_date or (end_date <= replay.get("end_date", "") and prior_health.get("ok") and prior_health.get("source", "").startswith("yfinance")):
        print(f"production replay already current at {replay.get('end_date', base_date)}; no writes")
        return

    symbols = sorted(symbol for symbol in allocation if symbol != "CASH")
    client = MarketDataClient()
    price_history, data_health = client.load_price_history(
        symbols,
        base_date,
        end_date,
        allow_synthetic=False,
        allow_secondary_price_fallback=True,
        optional_symbols=set(),
    )
    if not data_health["ok"]:
        raise SystemExit("DATA_HALT: replay has missing/stale prices; no curve was written")

    spy = price_history.get("SPY")
    if spy is None or spy.empty:
        raise SystemExit("SPY price history is required to extend production replay")
    dates = [idx.date().isoformat() for idx in spy.index if base_date < idx.date().isoformat() <= end_date]
    if not dates:
        print(f"no new SPY dates after {base_date} through {end_date}")
        return

    base_prices = {}
    missing_symbols = []
    for symbol in symbols:
        frame = price_history.get(symbol)
        if frame is None or frame.empty:
            missing_symbols.append(symbol)
            continue
        series = frame["close"].astype(float).sort_index().ffill()
        base_price = _price_as_of(series, base_date)
        if base_price is None or base_price <= 0:
            missing_symbols.append(symbol)
            continue
        base_prices[symbol] = base_price
        price_history[symbol] = frame.sort_index().ffill()

    if missing_symbols:
        raise SystemExit(f"missing extension prices: {', '.join(sorted(missing_symbols))}")

    existing_curve = [row for row in replay.get("equity_curve", []) if row.get("date") <= base_date]
    cash_value = base_nav * allocation.get("CASH", 0.0)
    extension_rows = []
    for current_date in dates:
        nav = cash_value
        for symbol in symbols:
            series = price_history[symbol]["close"].astype(float).sort_index().ffill()
            price = _price_as_of(series, current_date)
            if price is None or price <= 0:
                raise SystemExit(f"missing {symbol} close for {current_date}")
            nav += base_nav * allocation[symbol] * price / base_prices[symbol]
        extension_rows.append({"date": current_date, "equity": round(nav, 4)})

    updated = dict(replay)
    updated["equity_curve"] = existing_curve + extension_rows
    updated["end_date"] = updated["equity_curve"][-1]["date"]
    updated["point_count"] = len(updated["equity_curve"])
    updated["extension"] = {
        "method": "mark_to_market_current_allocation_until_next_full_replay",
        "base_date": base_date,
        "end_date": updated["end_date"],
        "requested_end_date": end_date,
        "base_nav": round(base_nav, 4),
        "symbols": symbols,
        "data_health": data_health,
        "watermark": SYSTEMATIC_TEMPLATE_OUTPUT,
    }
    write_json(REPLAY_PATH, add_watermark(updated, SYSTEMATIC_TEMPLATE_OUTPUT))
    print(
        f"extended production replay: {base_date}..{updated['end_date']}, "
        f"nav={updated['equity_curve'][-1]['equity']:.2f}"
    )


def _equity_on(replay: dict[str, Any], target_date: str) -> float:
    for row in replay.get("equity_curve", []):
        if row.get("date") == target_date:
            return float(row["equity"])
    raise SystemExit(f"missing replay equity for {target_date}")


def _price_as_of(series: pd.Series, target_date: str) -> float | None:
    target = pd.Timestamp(target_date)
    available = series.loc[series.index <= target]
    if available.empty:
        return None
    return float(available.iloc[-1])


def latest_completed_market_date() -> str:
    return latest_completed_market_date()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
