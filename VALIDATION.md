# Local migration validation — 2026-10-06 UTC

Scope: private yfinance replacement of the active daily/production-replay/benchmark price path. No main-branch merge or deployment. Downloaded prices and generated runtime outputs are excluded from source control.

## Evidence

| Check | Result |
| --- | --- |
| Initial real Yahoo price probe | 69 unique symbols downloaded successfully; all actual required windows complete |
| Required windows | Forward 68/68; replay 16/16; benchmarks 13/13 (overlapping symbols) |
| Observed HTTP responses | 138 chart requests returned 200; no 403/429; one anonymous-session initialization endpoint returned 404 |
| Fresh adapter smoke | SPY, 24 daily bars, live source healthy, through 2026-10-05 |
| Full private pipeline | Daily allocator → production replay extension → 13 benchmarks → dashboard artifact builder → output, watermark, dashboard validators: PASS |
| Recovery baseline | Frozen 2026-06-26 positions from `164c8a3`; raw-close revaluation matched original baseline NAV within $0.00001 |
| First recovery decision | `NO_TRADE`, no orders; old June signals excluded from October persistence |
| Same-session rerun | Portfolio state and production replay SHA-256 unchanged |
| Research replay | Eight real-cache symbols, 24 NYSE sessions from 2026-09-01 through 2026-10-05; network explicitly disabled; calendar dates exact; healthy, no synthetic data |
| Regression suite | 37 tests passed; six NumPy correlation warnings on zero-variance deterministic test fixtures |
| Dashboard | Loaded private runtime files in localhost browser; source/provenance, NO_TRADE and 1,193-point curves rendered; no JavaScript errors |

Initial downloads ran about 12:48–12:55 UTC. Subsequent migration tests reused these private histories. The latest completed US session was 2026-10-05. Python 3.12.14, yfinance 1.7.0, pandas 3.0.6, NumPy 2.5.3, exchange_calendars 4.13.2, pytest 9.1.1 were used.

The regression suite covers split-only Close versus dividend-adjusted Adj Close, share-split accounting and dividend ledger idempotence, empty/stale/partial data, VIX holiday cleanup, exchange close/holidays, 403 and 429 circuit behavior, transport interception before yfinance cookie retries, recovery signal dates, benchmark gaps, daily DATA_HALT state preservation, and replay preflight failure before any forward portfolio write. Test fixtures are distinct from the real-cache E2E evidence.

## Boundaries

The 2009–2021 training and complete strategy replay were not regenerated. Existing historical production results through the explicit June 2 baseline are preserved and identified; only the extension is newly validated with yfinance. The separate research replay uses an explicit eight-symbol cap and is not claimed to prove the full-universe historical strategy.

Market-wide movers/profile/news/fundamental hydration remains disabled. No Yahoo screen is presented as equivalent to the old Massive snapshot. Dividends are recorded without cash credit to preserve the original price-return convention. This is not a total-return accounting migration.

PR CI and cloud manual workflows have not run until the branch is uploaded. Workflows have read-only permissions and do not deploy Pages, commit runtime data, or upload market-data artifacts. Original repository main and the existing deployment were left untouched.

The existing GitHub connector reports `pull=true`, `push=false`. Local upload outcome is recorded separately in the handoff; this file does not assert a remote upload succeeded.
