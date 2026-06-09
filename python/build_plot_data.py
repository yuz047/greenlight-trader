"""Build a compact daily comparison plot artifact for static websites."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from config import DATA_DIR
from data_contracts import write_json
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


PLOT_SERIES = [
    ("production_Greenlight", "Greenlight", "#1f3a5f", 2.7, None),
    ("SPY_buy_hold", "SPY", "#767a82", 1.5, [6, 5]),
    ("QQQ_buy_hold", "QQQ", "#b45309", 1.5, None),
    ("VIX_20_15_strategy", "VIX 20/15", "#9b2c1f", 1.4, [3, 5]),
    ("SPY_200DMA_trend", "SPY 200DMA", "#2f6a4a", 1.5, None),
    ("dynamic_ETF_momentum_rotation", "ETF rotation", "#256f8f", 1.6, None),
    ("equal_weight_top_score", "Top-score sleeve", "#2f6a4a", 1.5, None),
]


def main() -> None:
    backtest = _read_json(DATA_DIR / "backtest_results.json")
    benchmark_snapshots = _read_json(DATA_DIR / "benchmark_snapshots.json")
    benchmark_metrics = _read_json(DATA_DIR / "benchmark_metrics.json")

    equity_curve = backtest.get("equity_curve") or []
    if not equity_curve:
        raise SystemExit("backtest_results.json has no equity_curve")

    labels = [str(row["date"]) for row in equity_curve if row.get("date")]
    snapshots = dict(benchmark_snapshots.get("snapshots") or {})
    snapshots["production_Greenlight"] = [
        {"date": row["date"], "equity": row["equity"]}
        for row in equity_curve
        if row.get("date") and row.get("equity") is not None
    ]

    series = []
    for key, label, color, width, dash in PLOT_SERIES:
        rows = snapshots.get(key) or []
        if not rows:
            continue
        values = _forward_fill(labels, rows)
        non_null = sum(value is not None for value in values)
        if non_null < max(2, int(len(labels) * 0.95)):
            raise SystemExit(f"{key} is too sparse for the plot: {non_null}/{len(labels)}")
        item: dict[str, Any] = {
            "key": key,
            "label": label,
            "color": color,
            "width": width,
            "values": values,
        }
        if dash:
            item["dash"] = dash
        series.append(item)

    if len(series) < 5:
        raise SystemExit(f"not enough comparison series: {len(series)}")

    payload = add_watermark(
        {
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "start_date": labels[0],
            "end_date": labels[-1],
            "point_count": len(labels),
            "labels": labels,
            "series": series,
            "metrics": benchmark_metrics.get("metrics", {}),
            "verdict": benchmark_metrics.get("verdict", {}),
            "data_sources": {
                "plot_axis": "data/backtest_results.json equity_curve",
                "comparison_curves": "data/benchmark_snapshots.json",
                "market_data_policy": "Massive/Polygon primary; Yahoo fallback is enabled in massive_client for VIX and secondary price gaps.",
            },
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )
    write_json(DATA_DIR / "greenlight_plot_data.json", payload)
    print(f"wrote {DATA_DIR / 'greenlight_plot_data.json'} ({len(labels)} points, {len(series)} series)")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"missing required file: {path}")
    return json.loads(path.read_text())


def _forward_fill(labels: list[str], rows: list[dict[str, Any]]) -> list[float | None]:
    point_map = {
        str(row["date"]): float(row["equity"])
        for row in rows
        if row.get("date") and row.get("equity") is not None
    }
    values: list[float | None] = []
    last: float | None = None
    for label in labels:
        if label in point_map:
            last = point_map[label]
        values.append(round(last, 4) if last is not None else None)
    return values


if __name__ == "__main__":
    main()
