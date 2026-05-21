"""Validate GreenLight dashboard JSON before publishing.

This is intentionally strict around the failure modes that caused the
dashboard regressions: synthetic cache pollution, truncated equity history,
identical strategy/benchmark plot lines, and a year-long SPY-only book.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config import DATA_DIR, CACHE_DIR, MANDATE


START_DATE = "2025-01-01"
STARTING_CAPITAL = MANDATE.starting_capital
MIN_SNAPSHOT_ROWS = 250
FULL_YEAR_WINDOW = 252


def _load_json(name: str):
    return json.loads((DATA_DIR / f"{name}.json").read_text())


def _fail(message: str) -> None:
    raise SystemExit(f"[validate] {message}")


def validate_cache() -> None:
    for path in sorted(CACHE_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            _fail(f"could not read cache file {path}: {exc}")
        if "synthetic" in df.columns and df["synthetic"].astype(str).str.lower().eq("true").any():
            _fail(f"synthetic rows found in cache file {path}")


def _healthy_published_data() -> bool:
    status = _load_json("system_status")
    data = status.get("data", {})
    return bool(data.get("ok", False)) and not bool(data.get("synthetic", False))


def validate_snapshots() -> None:
    snapshots = _load_json("snapshots")
    if len(snapshots) <= MIN_SNAPSHOT_ROWS:
        _fail(f"snapshots has {len(snapshots)} rows, expected > {MIN_SNAPSHOT_ROWS}")
    first = snapshots[0]
    if first.get("date") != START_DATE:
        _fail(f"first snapshot date is {first.get('date')}, expected {START_DATE}")
    if round(float(first.get("equity", 0.0)), 2) != STARTING_CAPITAL:
        _fail(f"first strategy equity is not ${STARTING_CAPITAL:,.0f}")
    if round(float(first.get("benchmark_equity", 0.0)), 2) != STARTING_CAPITAL:
        _fail(f"first benchmark equity is not ${STARTING_CAPITAL:,.0f}")

    differences = [
        abs(float(s["equity"]) - float(s.get("benchmark_equity", s["equity"])))
        for s in snapshots
    ]
    if max(differences) <= 0.01:
        _fail("strategy and benchmark plot lines are identical")

    healthy_data = _healthy_published_data()
    if healthy_data and not any(int(s.get("n_picks_open", 0)) > 0 for s in snapshots):
        _fail("snapshot history never holds a non-SPY pick")

    if healthy_data:
        for start in range(0, len(snapshots) - FULL_YEAR_WINDOW + 1):
            window = snapshots[start:start + FULL_YEAR_WINDOW]
            if all(int(s.get("n_picks_open", 0)) == 0 for s in window):
                _fail(
                    "found a full 252-row window with no non-SPY picks "
                    f"({window[0]['date']} to {window[-1]['date']})"
                )


def validate_activity() -> None:
    trades = _load_json("trades")
    positions = _load_json("positions")
    has_non_spy_trade = any(t.get("symbol") != "SPY" for t in trades)
    has_non_spy_position = any(p.get("symbol") != "SPY" for p in positions)
    if not has_non_spy_trade and not has_non_spy_position:
        _fail("no non-SPY trades or open non-SPY positions found")


def main() -> None:
    validate_cache()
    validate_snapshots()
    validate_activity()
    print("[validate] dashboard JSON OK")


if __name__ == "__main__":
    main()
