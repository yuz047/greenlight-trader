"""Markdown comparison report generation."""
from __future__ import annotations

from typing import Any

from config import DATA_DIR
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, watermarked_text


def write_comparison_report(benchmark_payload: dict[str, Any]) -> str:
    metrics = benchmark_payload.get("metrics", {})
    verdict = benchmark_payload.get("verdict", {})
    lines = ["## Verdict", ""]
    for key, value in verdict.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Metrics", ""])
    for name, row in metrics.items():
        total = row.get("total_return", 0.0)
        sharpe = row.get("Sharpe", 0.0)
        max_dd = row.get("max_drawdown", 0.0)
        lines.append(f"- {name}: total_return={total}, Sharpe={sharpe}, max_drawdown={max_dd}")
    lines.append("")
    lines.append("Weak benchmark results are intentionally preserved in this report.")
    text = watermarked_text("Greenlight 2.0 Comparison Report", "\n".join(lines), SYSTEMATIC_TEMPLATE_OUTPUT)
    (DATA_DIR / "comparison_report.md").write_text(text)
    return text
