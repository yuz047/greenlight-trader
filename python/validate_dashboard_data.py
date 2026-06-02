"""Validate static dashboard data dependencies."""
from __future__ import annotations

import json

from config import DATA_DIR, ROOT


DASHBOARD_FILES = [
    "system_status.json",
    "portfolio_state.json",
    "candidate_scores.json",
    "selected_etfs.json",
    "execution_decisions.json",
    "benchmark_metrics.json",
    "benchmark_snapshots.json",
    "ai_reviews.json",
    "backtest_results.json",
    "backtest_decision_logs.json",
]


def main() -> None:
    failures = []
    if not (ROOT / "web" / "index.html").exists():
        failures.append("missing web/index.html")
    for name in DASHBOARD_FILES:
        path = DATA_DIR / name
        if not path.exists():
            failures.append(f"missing dashboard data {name}")
            continue
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            failures.append(f"dashboard data invalid JSON {name}: {exc}")
    if failures:
        raise SystemExit("\n".join(failures))
    print("dashboard data validation passed")


if __name__ == "__main__":
    main()
