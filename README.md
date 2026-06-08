# Greenlight 2.0

Greenlight 2.0 is a Massive-first, systematic, sparse-execution paper trading allocator.
It observes daily, discovers stocks and ETFs dynamically, scores candidates with
information, leadership, timing, and risk features, then produces deterministic
target weights subject to strict risk and execution gates.

Paper trading only. No broker connection. Not investment advice.

## Design Principles

- Massive/Polygon is the primary data source.
- SPY is the permanent benchmark/core anchor.
- QQQ is a regime-dependent growth anchor, not a permanent winner.
- Cash/SHY/SGOV are defensive proxies.
- Sector, industry, factor, theme, rates, and defensive ETFs must earn allocation dynamically.
- The production track is deterministic.
- Agent-led decisions are experimental, watermarked, compared, and never executable.
- Every generated report, memo, decision, and validation output is watermarked.
- Backtests must avoid lookahead. Unavailable historical point-in-time data is marked unavailable.

## Layout

```text
greenlight-trader/
├── python/
│   ├── config.py
│   ├── data_contracts.py
│   ├── massive_client.py
│   ├── universe.py
│   ├── etf_selector.py
│   ├── features.py
│   ├── regime.py
│   ├── scoring.py
│   ├── allocator.py
│   ├── exposure.py
│   ├── risk.py
│   ├── execution_policy.py
│   ├── portfolio.py
│   ├── backtest.py
│   ├── run_daily.py
│   ├── strategy_benchmarks.py
│   ├── weight_learning.py
│   ├── weight_registry.py
│   ├── weight_review.py
│   ├── agent_decision.py
│   ├── watermark.py
│   ├── decision_log.py
│   ├── ai_review.py
│   ├── comparison_report.py
│   ├── validate_outputs.py
│   ├── validate_watermarks.py
│   ├── validate_dashboard_data.py
│   └── tests/
├── data/
├── web/
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── .github/workflows/
```

This repository contains only the current Greenlight 2.0 implementation.

## Local Setup

```bash
cd "AI Trader/greenlight-trader"
python -m venv .venv
source .venv/bin/activate
pip install -r python/requirements.txt
```

Live Massive/Polygon data requires one of:

```bash
export MASSIVE_API_KEY="..."
# or
export POLYGON_API_KEY="..."
```

Optional GenAI memos use DeepSeek:

```bash
export DEEPSEEK_API_KEY="..."
export DEEPSEEK_MODEL="deepseek-v4-pro"
```

You can also put these values in a local `.env` file. `.env` is gitignored.

Without a key, the engine writes deterministic synthetic fallback data, marks
data health as fallback/synthetic, sets risk to `BLACK`, and refuses production
execution. This keeps local validation and dashboard development runnable while
making it impossible to mistake fallback output for live tradable data.

## Run Daily Mode

```bash
cd "AI Trader/greenlight-trader"
PYTHONPATH=python python python/run_daily.py
PYTHONPATH=python python python/validate_outputs.py
PYTHONPATH=python python python/validate_watermarks.py
PYTHONPATH=python python python/validate_dashboard_data.py
```

Daily mode writes:

```text
data/snapshots.json
data/portfolio_state.json
data/candidate_universe.json
data/candidate_scores.json
data/selected_etfs.json
data/target_allocations.json
data/execution_decisions.json
data/decision_logs.json
data/system_status.json
data/benchmark_metrics.json
data/benchmark_snapshots.json
data/weight_reviews.json
data/review_events.json
data/learning_report.md
data/comparison_report.md
data/ai_reviews.json
```

## Run Backtest

Full mandate window:

```bash
cd "AI Trader/greenlight-trader"
PYTHONPATH=python python python/backtest.py \
  --start-date 2009-01-01 \
  --train-start 2009-01-01 \
  --train-end 2021-12-31 \
  --invest-start 2022-01-01 \
  --end-date "$(date -u +%F)" \
  --rolling-train-years 3 \
  --ai-memo-mode deepseek \
  --ai-memo-frequency monthly \
  --no-synthetic-fallback
```

Research windows:

- Train: `2009-01-01` to `2021-12-31`
- Test: `2022-01-01` to latest available date
- Walk-forward: daily replay with rolling retraining; published result uses a 3-year rolling window

Fast smoke test:

```bash
PYTHONPATH=python python python/backtest.py --start-date 2024-01-01 --end-date 2024-04-30 --max-symbols 18
```

## Dashboard

The dashboard is static and GitHub Pages compatible. It reads only committed
`data/*.json` files and never calls Massive from the browser.

Local preview:

```bash
cd "AI Trader/greenlight-trader"
python -m http.server 8000
```

Open `http://localhost:8000/web/`.

## GitHub Secrets

Required for live daily runs:

- `MASSIVE_API_KEY` or `POLYGON_API_KEY`

Optional:

- `MASSIVE_API_BASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`

No frontend secret is required or allowed.

## GitHub Actions

- `.github/workflows/daily.yml`: scheduled daily after the US close, runs live mode when repository secrets are configured, validates outputs and watermarks, commits updated `data/*.json`.
- `.github/workflows/backtest.yml`: manual backtest with `start_date` and optional `end_date` inputs, clamps to the latest available market bar, uploads artifacts.
- `.github/workflows/publish-dashboard.yml`: deploys the static dashboard at the GitHub Pages root and keeps `/web/` available.

## Massive Endpoints Used

The client records endpoint availability under `data/system_status.json`.

- `/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from}/{to}` for OHLCV aggregates.
- `/v3/reference/tickers/{ticker}` for ticker metadata and company profile fields.
- `/v3/reference/tickers` for reference ticker discovery when enabled.
- `/v2/reference/news` for news metadata when available.
- `/vX/reference/financials` for financial snapshots when available.
- `/v2/snapshot/locale/us/markets/stocks/{direction}` for market movers when available.

Plan-dependent or historically incomplete endpoints are explicitly marked
unavailable instead of being forward-filled into historical backtests.

If Massive/Polygon index bars are unavailable for VIX under the current plan,
Greenlight fetches `^VIX` daily bars from Yahoo as a VIX-only secondary source.
This is recorded in `data_health.secondary_source_symbols`; equities and ETFs
remain Massive-first and do not use Yahoo fallback.

## Known Limitations

- The repository ships with deterministic synthetic fallback output for local
  testing; live decisions require Massive/Polygon data.
- Historical analyst, ratings, price target, and fundamentals are used only
  when the API response confirms availability at the requested date.
- ETF overlap is approximated through correlation; holdings-level ETF
  overlap is left for a later data entitlement.
- The agent-led track is a structured experimental mirror, not an autonomous
  trading agent.
