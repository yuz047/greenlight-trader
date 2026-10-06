# Greenlight Trader: private yfinance replacement

This branch replaces the active Massive/Polygon price path with `yfinance` daily histories. It runs independently of the original project and does not need a Massive API key. The original upstream version is pinned in [archives/README.md](archives/README.md).

The supported migration flow is: restore the explicit trustworthy paper-portfolio baseline, validate every required price window, run today's allocator, extend the existing production replay, rebuild benchmarks and dashboard contracts, and validate the outputs. Runtime prices, caches, portfolio state, and generated dashboard data stay in gitignored `.runtime/`.

## Local setup (PowerShell, Python 3.12)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
$env:PYTHONPATH = (Join-Path $PWD 'python')
git fetch --depth=1 origin 164c8a307449d6ce63e7f70bb829515b4c5eae31
.\.venv\Scripts\python.exe python/initialize_migration.py
.\.venv\Scripts\python.exe python/run_pipeline.py
.\.venv\Scripts\python.exe python/preview_server.py
```

Open http://127.0.0.1:8765/web/ for the private dashboard. `initialize_migration.py` refuses to replace an existing runtime portfolio. A supplied local copy may already be initialized; skip initialization in that case. Do not serve committed `data/` as if it were the current migration output.

On Linux/macOS, use `.venv/bin/python` and `export PYTHONPATH=python`. Set `GREENLIGHT_DATA_DIR` and `GREENLIGHT_CACHE_DIR` before starting Python to isolate another run. To reuse existing diagnostic CSVs without requests:

```powershell
.\.venv\Scripts\python.exe python/seed_diagnostic_cache.py PATH_TO_PRIVATE_EVIDENCE --start 2022-01-03 --end 2026-10-05
```

Each later session needs updated histories. Requests are sequential with at least five seconds between them. A 429 opens a persisted 60-second cooldown; a 401/403 stops further uncached requests in that invocation. There is no immediate retry or synthetic fallback. Yahoo availability is not guaranteed.

## Price and accounting policy

- Call history with `auto_adjust=False`, daily bars, actions enabled, and repair disabled. Research uses Yahoo `Close`, which is split adjusted, and never substitutes the dividend-adjusted `Adj Close`. This preserves the original split-only price-return convention.
- Actual paper holdings remain share based. Split events adjust quantity and average cost once. Dividend events are recorded with zero cash credit, explicitly preserving the original price-return convention. The ledger discloses the excluded amount. Changing to total return requires separate strategy validation.
- Recovery starts from commit `164c8a3` (2026-06-26). It restores those positions and revalues them with real histories. It does not invent trades during the missing interval. Old June signals cannot satisfy October signal persistence.
- The production replay preserves its existing historical prefix and recomputes the extension from its explicit 2026-06-02 allocation. That curve is a research replay, separate from forward paper holdings.
- Session dates come from the NYSE calendar. VIX holiday rows with completely empty OHLC are discarded; missing actual market sessions halt validation. Zero VIX volume is permitted. VWAP is unavailable and stays null.

Historical split-adjusted prices depend on the download vintage. A later split changes Yahoo's earlier Close even with `auto_adjust=False`. Keep the action dates and source retrieval date when comparing old Massive snapshots. Do not split-adjust Yahoo Close a second time. Historical share-based accounting and absolute price thresholds need prices expressed in that decision date's share unit; the complete historical strategy has not been certified against a second vendor. Never apply dividend adjustment factors to Volume.

Daily risk now advances SPY's price-return benchmark before the execution decision. The final report reevaluates risk after transaction costs, with a separate pre-execution basis retained in `execution_decisions.json`. Portfolio, risk, and system status use the same valuation date and benchmark. A missing recovery valuation path reports full-period absolute drawdown as null and records the missing sessions. The existing gates continue to use observed snapshots; a GREEN observation does not certify the unobserved interval. Relative drawdown also refers to the observed relative peak.

## Data fault behavior and feature scope

`run_pipeline.py` checks all forward, replay, and benchmark windows before the daily portfolio can change. Missing, partial, or stale bars cause `DATA_HALT`: portfolio state, NAV, snapshots, and replay curves remain unchanged. Only failure status and risk/execution notices are written. Successful same-session repetition does not repeat trades or rewrite the portfolio/replay curve.

This version uses the configured stock/ETF universe plus existing holdings. Market-wide gainers/losers discovery and profile hydration are disabled and reported as such; a Yahoo screener is not represented as an equivalent Massive snapshot. No new news, fundamentals, or AI-provider integration is claimed.

The full 2009-onward research retraining was not revalidated. Strict histories can halt before ETF inception; do not manufacture pre-inception SGOV/CEG data. A real-cache, eight-symbol research replay was checked separately; see [VALIDATION.md](VALIDATION.md).

## Tests and automation

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'python')
.\.venv\Scripts\python.exe -m pytest -q python/tests
```

The PR workflow runs offline regression tests with deterministic fixtures. Manual daily/backtest workflows use ephemeral runner storage, have read-only repository permissions, and do not commit prices, upload runtime artifacts, or deploy Pages. Automatic daily publication and the Pages publisher are removed from this experimental branch. Original `main` is unchanged until a separately reviewed merge.

Yahoo raw histories, derived outputs, anonymous cookies, `.env`, `.venv`, and runtime caches must not be added to Git. The yfinance code license does not grant rights to redistribute provider data; evaluate intended use separately before publishing generated market data.
