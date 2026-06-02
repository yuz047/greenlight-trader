# Greenlight 2.0 Work Plan

## Completed Baseline

- Created a fresh V2 folder while preserving the old GreenLight repository.
- Rebuilt around deterministic allocator modules instead of legacy strategy files.
- Added Massive/Polygon client, cache, endpoint availability reporting, and synthetic fallback gating.
- Added dynamic ETF discovery, stock universe construction, feature engineering, scoring, allocation, risk, execution policy, portfolio accounting, benchmark comparison, and watermarked output generation.
- Added validation scripts, tests, static dashboard, and GitHub Actions.

## Operating Rules

- Paper trading only.
- No broker connection.
- No hardcoded sector winner.
- No LLM-controlled execution.
- No production use of fallback/synthetic data.
- No generated output without a watermark.
- No learned weights promoted without human approval.

## Research Windows

- Full: `2009-01-01` to latest.
- Train: `2009-01-01` to `2021-12-31`.
- Test: `2022-01-01` to latest.
- Walk-forward: yearly expanding windows.

## V1 Deferrals

- Full autonomous logic mutation.
- Production promotion of learned weights without a separate human approval layer.
- ETF holdings-level overlap unless licensed holdings data is added.
- True historical point-in-time analyst/fundamental histories unless Massive confirms entitlement.
