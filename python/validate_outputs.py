"""Validate generated Greenlight outputs."""
from __future__ import annotations

import json
import re

from config import DATA_DIR, REQUIRED_OUTPUTS
from watermark import has_valid_watermark


SECRET_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{20,}|api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9_-]{20,})")


def main() -> None:
    failures = []
    for name in REQUIRED_OUTPUTS:
        path = DATA_DIR / name
        if not path.exists():
            failures.append(f"missing required output: {name}")
            continue
        text = path.read_text()
        if SECRET_RE.search(text):
            failures.append(f"secret-like string found in {name}")
        if path.suffix == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                failures.append(f"invalid JSON {name}: {exc}")
                continue
            if not has_valid_watermark(payload):
                failures.append(f"missing watermark: {name}")
        elif "Watermark:" not in text:
            failures.append(f"missing text watermark: {name}")

    target_path = DATA_DIR / "target_allocations.json"
    if target_path.exists():
        payload = json.loads(target_path.read_text())
        weights = [float(row.get("weight", 0.0)) for row in payload.get("target_allocations", [])]
        if any(weight < -1e-9 for weight in weights):
            failures.append("negative long-only target weight")
        if sum(weights) > 1.0001:
            failures.append(f"target weights sum above 1: {sum(weights)}")

    metrics_path = DATA_DIR / "benchmark_metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text()).get("metrics", {})
        required = {"SPY_buy_hold", "QQQ_buy_hold", "VIX_20_15_strategy", "SPY_200DMA_trend"}
        missing = required - set(metrics)
        if missing:
            failures.append(f"missing benchmark metrics: {sorted(missing)}")

    if failures:
        raise SystemExit("\n".join(failures))
    print("output validation passed")


if __name__ == "__main__":
    main()
