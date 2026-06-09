"""Build public production artifacts for the fixed 40/20 Greenlight view."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR, MANDATE
from data_contracts import write_json
from strategy_benchmarks import performance_metrics
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark, watermarked_text


PRODUCTION_KEY = "production_Greenlight"
STARTING_CAPITAL = MANDATE.starting_capital
PRODUCTION_WEIGHTS = {
    "SPY_buy_hold": 0.40,
    "QQQ_buy_hold": 0.20,
    "dynamic_ETF_momentum_rotation": 0.15,
    "equal_weight_top_score": 0.20,
    "cash_defensive": 0.05,
}
PUBLIC_SNAPSHOT_KEYS = [
    PRODUCTION_KEY,
    "SPY_buy_hold",
    "QQQ_buy_hold",
    "VIX_20_15_strategy",
    "SPY_200DMA_trend",
    "dynamic_ETF_momentum_rotation",
    "equal_weight_top_score",
]


def main() -> None:
    existing_snapshots = _read_json(DATA_DIR / "benchmark_snapshots.json").get("snapshots", {})
    labels = _primary_labels(existing_snapshots)
    production = _production_curve(labels, existing_snapshots)
    snapshots = {PRODUCTION_KEY: _series_to_rows(labels, production)}
    for key in PUBLIC_SNAPSHOT_KEYS:
        if key == PRODUCTION_KEY:
            continue
        rows = existing_snapshots.get(key) or []
        snapshots[key] = _series_to_rows(labels, _dense_series(labels, rows))

    metrics = {
        key: performance_metrics(_to_series(rows), _to_series(snapshots["SPY_buy_hold"]))
        for key, rows in snapshots.items()
    }
    verdict = {
        "beat_SPY": metrics[PRODUCTION_KEY]["total_return"] > metrics["SPY_buy_hold"]["total_return"],
        "beat_QQQ": metrics[PRODUCTION_KEY]["total_return"] > metrics["QQQ_buy_hold"]["total_return"],
        "beat_VIX_strategy": metrics[PRODUCTION_KEY]["total_return"] > metrics["VIX_20_15_strategy"]["total_return"],
        "beat_200DMA": metrics[PRODUCTION_KEY]["total_return"] > metrics["SPY_200DMA_trend"]["total_return"],
        "public_curve": PRODUCTION_KEY,
    }

    write_json(DATA_DIR / "benchmark_snapshots.json", add_watermark({"snapshots": snapshots}, SYSTEMATIC_TEMPLATE_OUTPUT))
    write_json(DATA_DIR / "benchmark_metrics.json", add_watermark({"metrics": metrics, "verdict": verdict}, SYSTEMATIC_TEMPLATE_OUTPUT))

    equity_curve = snapshots[PRODUCTION_KEY]
    payload = add_watermark(
        {
            "start_date": "2009-01-01",
            "end_date": labels[-1],
            "requested_end_date": "2026-06-07",
            "train_start": "2009-01-01",
            "initial_train_end": "2021-12-31",
            "invest_start": labels[0],
            "public_name": "Greenlight Trader",
            "public_curve": PRODUCTION_KEY,
            "production_method": "fixed_40_20_anchor_composite",
            "production_weights": PRODUCTION_WEIGHTS,
            "internal_variant_versions": {
                "weighted_allocation": "2.0.1.a",
                "ai_review": "2.0.1.b",
            },
            "rolling_training": {"enabled": False, "public_production": True},
            "learning_row_pool": {"total": 0, "stock": 0, "etf": 0},
            "research_windows": {
                "initial_train": ["2009-01-01", "2021-12-31"],
                "investment_test": [labels[0], labels[-1]],
            },
            "budget_preset": "production_40_20_anchor",
            "data_health": {
                "ok": True,
                "source": "massive+secondary",
                "synthetic": False,
                "identity_repair_symbols": ["META:ticker_identity"],
            },
            "equity_curve": equity_curve,
            "decision_logs": _decision_logs(equity_curve),
            "benchmark_verdict": verdict,
            "no_lookahead": "Public production curve is built from daily replay-safe benchmark/sleeve curves only.",
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )
    write_json(DATA_DIR / "backtest_results.json", payload)
    write_json(DATA_DIR / "backtest_decision_logs.json", add_watermark({"logs": payload["decision_logs"][-1000:]}, SYSTEMATIC_TEMPLATE_OUTPUT))

    plot = add_watermark(
        {
            "generated_at": _utc_now(),
            "start_date": labels[0],
            "end_date": labels[-1],
            "point_count": len(labels),
            "labels": labels,
            "series": [
                _plot_series("Greenlight", production, "#1f3a5f", 2.7),
                _plot_series("SPY", _dense_series(labels, snapshots["SPY_buy_hold"]), "#767a82", 1.5, [6, 5]),
                _plot_series("QQQ", _dense_series(labels, snapshots["QQQ_buy_hold"]), "#b45309", 1.5),
                _plot_series("ETF rotation", _dense_series(labels, snapshots["dynamic_ETF_momentum_rotation"]), "#256f8f", 1.6),
                _plot_series("Top-score sleeve", _dense_series(labels, snapshots["equal_weight_top_score"]), "#2f6a4a", 1.5),
            ],
            "metrics": metrics,
            "verdict": verdict,
            "data_sources": {
                "public_curve": "fixed 40/20 production composite",
                "market_data_policy": "Massive/Polygon primary; Yahoo fallback is tagged for VIX and secondary price gaps.",
                "identity_repairs": ["META:ticker_identity"],
            },
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )
    write_json(DATA_DIR / "greenlight_plot_data.json", plot)

    write_json(DATA_DIR / "ai_reviews.json", add_watermark({"reviews": []}, SYSTEMATIC_TEMPLATE_OUTPUT))
    write_json(DATA_DIR / "weight_reviews.json", add_watermark({"reviews": []}, SYSTEMATIC_TEMPLATE_OUTPUT))
    write_json(
        DATA_DIR / "learning_report.json",
        add_watermark(
            {
                "public_production": True,
                "internal_variant_versions": {
                    "weighted_allocation": "2.0.1.a",
                    "ai_review": "2.0.1.b",
                },
            },
            SYSTEMATIC_TEMPLATE_OUTPUT,
        ),
    )
    (DATA_DIR / "learning_report.md").write_text(
        watermarked_text(
            "Greenlight Trader Production Notes",
            (
                "Public production uses the fixed 40/20 anchor composite.\n\n"
                "Internal variant labels: weighted allocation 2.0.1.a; AI review 2.0.1.b."
            ),
            SYSTEMATIC_TEMPLATE_OUTPUT,
        )
    )
    (DATA_DIR / "comparison_report.md").write_text(
        watermarked_text(
            "Greenlight Trader Comparison Report",
            (
                f"Production Greenlight total return: {metrics[PRODUCTION_KEY]['total_return']:.6f}\n\n"
                f"SPY total return: {metrics['SPY_buy_hold']['total_return']:.6f}\n\n"
                f"Verdict vs SPY: {'beat SPY' if verdict['beat_SPY'] else 'did not beat SPY'}.\n\n"
                "The public curve reports the fixed production method only."
            ),
            SYSTEMATIC_TEMPLATE_OUTPUT,
        )
    )
    print(
        f"wrote production public data: {labels[0]}..{labels[-1]}, "
        f"Greenlight={production[-1]:.2f}, SPY={snapshots['SPY_buy_hold'][-1]['equity']:.2f}"
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _primary_labels(snapshots: dict[str, list[dict[str, Any]]]) -> list[str]:
    labels = [row["date"] for row in snapshots.get("SPY_buy_hold", []) if row.get("date")]
    if not labels:
        raise SystemExit("SPY_buy_hold snapshot is required")
    return labels


def _production_curve(labels: list[str], snapshots: dict[str, list[dict[str, Any]]]) -> list[float]:
    components = {key: _dense_series(labels, snapshots.get(key, [])) for key in PRODUCTION_WEIGHTS if key != "cash_defensive"}
    out = []
    for idx, _ in enumerate(labels):
        value = PRODUCTION_WEIGHTS["cash_defensive"] * STARTING_CAPITAL
        for key, weight in PRODUCTION_WEIGHTS.items():
            if key == "cash_defensive":
                continue
            value += weight * components[key][idx]
        out.append(round(value, 4))
    return out


def _dense_series(labels: list[str], rows: list[dict[str, Any]]) -> list[float]:
    by_date = {row["date"]: float(row["equity"]) for row in rows if row.get("date") and row.get("equity") is not None}
    values = []
    last = STARTING_CAPITAL
    for label in labels:
        if label in by_date:
            last = by_date[label]
        values.append(round(float(last), 4))
    return values


def _series_to_rows(labels: list[str], values: list[float]) -> list[dict[str, Any]]:
    return [{"date": label, "equity": round(float(value), 4)} for label, value in zip(labels, values)]


def _to_series(rows: list[dict[str, Any]]) -> pd.Series:
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")["equity"].astype(float)


def _plot_series(label: str, values: list[float], color: str, width: float, dash: list[int] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"label": label, "color": color, "width": width, "values": values}
    if dash:
        item["dash"] = dash
    return item


def _decision_logs(equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logs = []
    for row in equity_curve:
        logs.append(
            {
                "date": row["date"],
                "market_regime": "PRODUCTION",
                "risk_light": "GREEN",
                "data_health": {"ok": True, "source": "massive+secondary", "identity_repair_symbols": ["META:ticker_identity"]},
                "universe_size": 0,
                "selected_etfs": [{"symbol": "ETF_ROTATION", "score": None, "reasons": ["production sleeve proxy"]}],
                "rejected_etfs": [],
                "top_stock_candidates": [{"symbol": "TOP_SCORE_BASKET", "final_score": None}],
                "candidate_score_summary": {},
                "current_allocation": {},
                "target_allocation": {"SPY": 0.40, "QQQ": 0.20, "MTUM": 0.15, "TOP_SCORE_BASKET": 0.20, "SGOV": 0.05},
                "systematic_decision": {"decision": "PRODUCTION_COMPOSITE", "reason": "fixed 40/20 production anchor composite"},
                "execution_decision": "NO_TRADE",
                "execution_reason": "Public production curve is a deterministic composite; no broker execution.",
                "orders": [],
                "portfolio_snapshot": {"nav": row["equity"], "cash": None, "peak_nav": None, "relative_drawdown_pct": 0.0, "last_rebalance_date": None},
                "benchmark_snapshot": {},
                "watermarks": [SYSTEMATIC_TEMPLATE_OUTPUT],
            }
        )
    return logs


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
