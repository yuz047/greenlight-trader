# Local migration validation — 2026-10-06 UTC

Scope: private yfinance replacement of the active daily/production-replay/benchmark price path. No main-branch merge or deployment. Downloaded prices and generated runtime outputs are excluded from source control.

## Evidence

| Check | Result |
| --- | --- |
| Initial real Yahoo price probe | 69 unique symbols downloaded successfully; all actual required windows complete |
| Required windows | Forward 68/68; replay 16/16; benchmarks 13/13 (overlapping symbols) |
| Observed HTTP responses | 138 chart requests returned 200; no 403/429; one anonymous-session initialization endpoint returned 404 |
| Fresh adapter smoke | SPY, 24 daily bars, live source healthy, through 2026-10-05 |
| Full private pipeline | After the risk timing repair, fresh trusted baseline: daily allocator, production replay extension, 13 benchmarks, dashboard builder and three validators all PASS using real cached histories, with network disabled |
| Recovery baseline | Frozen 2026-06-26 positions from `164c8a3`; raw-close revaluation matched original baseline NAV within $0.00001 |
| First recovery decision | `NO_TRADE`, no orders; old June signals excluded from October persistence |
| Final risk consistency | Portfolio, risk and snapshot use October 5 NAV $5,249.950196 and SPY equity $5,322.300280; observed relative drawdown 2.2646% agrees across outputs |
| Missing daily valuation path | 68 NYSE sessions (June 29 through October 2) are absent; full-period drawdown is null, observed-snapshot drawdown is 0%, and the limitation is displayed |
| Same-session rerun | Portfolio state and production replay SHA-256 unchanged |
| Research replay | Eight real-cache symbols, 24 NYSE sessions from 2026-09-01 through 2026-10-05; network explicitly disabled; calendar dates exact; healthy, no synthetic data |
| Regression suite | 42 tests passed; six NumPy correlation warnings on zero-variance deterministic test fixtures |
| Dashboard | Loaded private runtime files in localhost browser; source/provenance, NO_TRADE and 1,193-point curves rendered; no JavaScript errors |

Initial downloads ran about 12:48–12:55 UTC. Subsequent migration tests reused these private histories. The latest completed US session was 2026-10-05. Python 3.12.14, yfinance 1.7.0, pandas 3.0.6, NumPy 2.5.3, exchange_calendars 4.13.2, pytest 9.1.1 were used.

The regression suite covers split-only Close versus dividend-adjusted Adj Close, share-split accounting and dividend ledger idempotence, empty/stale/partial data, VIX holiday cleanup, exchange close/holidays, 403 and 429 circuit behavior, transport interception before yfinance cookie retries, recovery signal dates, benchmark gaps, daily DATA_HALT state preservation, and replay preflight failure before any forward portfolio write. Added checks cover a benchmark advance before risk, final risk after transaction costs, unknown recovery drawdown, rejection of an inconsistent risk report, and the shared SPY/QQQ price-return dividend convention. Test fixtures are distinct from the real-cache E2E evidence.

## Same-date vendor reconciliation

The trusted June 26 commit retains genuine Massive Close quotes and derived features, with healthy endpoint evidence, no synthetic data, and only VIX using Yahoo fallback. Those 67 ordinary-symbol quotes were compared to Yahoo native daily histories downloaded on October 6. Of these, 66 match at the cent level without conversion. CRWD was 701.09 in the June snapshot and 175.2725067 in the October download: the Yahoo action record identifies a 4:1 split on July 2. Expressing the older quote in that later share unit yields 175.2725, so all 67 match to cents; the maximum residual is $0.0000293. This conversion is confined to diagnostic comparison and does not re-adjust Yahoo Close.

For SPY, QQQ, SGOV, AAPL and BOTZ, Yahoo has all 289 expected NYSE sessions from May 2, 2025 to June 26, 2026. Massive raw OHLCV for this window was not retained, so complete paired OHLCV, missing-session and split-volume equivalence cannot be certified. The saved 20-day average dollar volume differs by -0.0476% for QQQ and up to -0.5557% across the compared universe (CEG). There were no mismatches among 402 compared boolean feature flags, but this does not certify target weights or complete decision equivalence. All comparisons used native daily histories and the original candidate metadata; no minute resampling, dividend-volume conversion, or fitted price scaling was performed.

Revaluing the original 16 June 26 positions at the same Yahoo Close prices changes NAV by only $0.00000612. Substituting Adj Close without dividend accounting instead reduces that NAV by $12.580665. This identifies a material basis error rather than a reason to force the two providers' values to match. Old and new snapshots must share a date, price-return policy, action units, and retrieval vintage before comparison.

## Boundaries

The 2009–2021 training and complete strategy replay were not regenerated. Existing historical production results through the explicit June 2 baseline are preserved and identified; only the extension is newly validated with yfinance. The separate research replay uses an explicit eight-symbol cap and is not claimed to prove the full-universe historical strategy.

Market-wide movers/profile/news/fundamental hydration remains disabled. No Yahoo screen is presented as equivalent to the old Massive snapshot. Dividends are recorded without cash credit to preserve the original price-return convention. This is not a total-return accounting migration.

PR CI and cloud manual workflows have not run until the branch is uploaded. Workflows have read-only permissions and do not deploy Pages, commit runtime data, or upload market-data artifacts. Original repository main and the existing deployment were left untouched.

The existing GitHub connector reports `pull=true`, `push=false`. Local upload outcome is recorded separately in the handoff; this file does not assert a remote upload succeeded.
