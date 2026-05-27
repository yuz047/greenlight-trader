# GreenLight Trader

A small AI-supervised paper-trading research system.
It runs a $5,000 controlled-risk portfolio, generates daily allocation
choices from a broad tech, semiconductor, mega-cap, and discovery universe,
gates every trade through a strict risk engine, and writes a human-readable
end-of-day review.

**Survival first.** Strategy selection, sizing, and the EOD reviewer all
optimize for risk-adjusted return on a small book — not absolute return.

> Paper trading only. The engine never connects to a broker.
> Not investment advice.

---

## What it does

Every weekday after the US close:

1. Pulls fresh OHLCV for the watchlist from yfinance.
2. Recomputes signals (SMA, RSI, ATR, 20-day high, volume z-score).
3. Tags the market regime from SPY's 50/200 SMAs and 200d drawdown.
4. Pulls Yahoo Finance RSS headlines and scores them through a small
   positive/negative lexicon.
5. Runs every active strategy across the watchlist.
6. Ranks the resulting candidates by composite score.
7. Pushes them through a risk gate — 1 % per-trade, 10 % drawdown shutdown,
   max 3 open positions, 35 % single-name exposure, no leverage.
8. Marks the book to market, fires stops / targets / max-hold exits.
9. Generates an EOD review (Claude Haiku via the Anthropic API if a key is
   present; otherwise fills a deterministic template with the same fields).
10. Writes JSON snapshots to `data/` and (optionally) mirrors them into a
    Supabase Postgres database.

A static dashboard reads those JSON files and renders system status,
portfolio state, the equity curve, open positions, the tomorrow pitch
sheet, realized risk metrics, recent closed trades, and the AI review log.

---

## Architecture

```
GitHub Actions (weeknight after the US close)
        │
        ▼
Python engine ── yfinance (OHLCV) ── Yahoo RSS (sentiment)
   data → signals → strategies/* → risk → portfolio
                          │
                          ├── EOD review (Anthropic, w/ template fallback)
                          ▼
                  data/*.json ──► Supabase (optional)
                                       │
                                       ▼
                         Public read-only dashboard
```

The Python engine is the source of truth. The dashboard is a static page
that fetches the JSON snapshots over HTTPS. A Postgres mirror is available
for projects that prefer relational reads.

---

## Repo layout

```
greenlight-trader/
├── python/
│   ├── config.py            # watchlist, risk caps, active strategy ids
│   ├── data.py              # yfinance loader + CSV cache + synthetic fallback
│   ├── signals.py           # SMA, RSI(Wilder), ATR, 20d high, volume ratio
│   ├── strategies/          # one file per strategy (auto-discovered)
│   │   ├── _types.py
│   │   ├── momentum_breakout_v1.py
│   │   ├── mean_reversion_v1.py
│   │   └── stock_pitcher_v1.py
│   ├── risk.py              # position sizing + account-level caps + traffic light
│   ├── portfolio.py         # paper book, realized/unrealized PnL, stop/target/MH
│   ├── backtest.py          # walk-forward sim (uses the live risk engine)
│   ├── news.py              # Yahoo RSS pull + lexicon sentiment
│   ├── llm_review.py        # EOD review — Anthropic if keyed, template otherwise
│   ├── db.py                # Supabase REST writer + JSON writer
│   ├── seed_history.py      # one-shot ~2y backtest → seeds data/*.json
│   └── run_daily.py         # daily orchestrator (entry point for the cron)
├── supabase/
│   └── schema.sql           # 5 tables with read-only RLS for the public anon key
├── web/                     # Next.js + Tailwind + Recharts variant (optional)
├── data/                    # JSON snapshots the dashboard reads
└── .github/workflows/daily.yml
```

---

## Strategies

The strategy package is **hot-swappable**: drop a `*.py` file into
`python/strategies/`, expose a `MANIFEST` dict and a `run()` entrypoint,
list its id in `config.ACTIVE_IDS`. The package auto-discovers everything
on import; no central register to edit. Old versions stay in-tree for
audit and comparison backtests.

### `stock_pitcher_v1` — cross-sectional ranker

A multi-factor ranker that picks tomorrow's candidates from the watchlist.
For every name the pitcher computes:

| Factor | Captures |
|---|---|
| Trend t-stat (60d) | slope / stderr of OLS on log(close) — persistent trend |
| R² (60d) | quality of the trend line |
| 63d relative strength vs SPY | excess return over the benchmark |
| Risk-adjusted momentum (20d) | 20d return ÷ 20d realized vol |

The four factors are z-scored across the universe and averaged into a
composite. Names that clear `composite z > 0.6`, `R² > 0.25`, and
`RS > −5 %` are kept; the top 3 by rank go to the risk gate.

Sizing uses `stop = 1.5·ATR(14)` and a target derived from the regression
slope projected 5 days forward, clipped to `[1, 4]·ATR`.

### `momentum_breakout_v1` — 20-day breakout overlay

Long entry when close prints above the prior 20-day high on volume
≥ 1.5× the 20-day average, while SPY is not in `risk_off` or `distressed`
and headline sentiment is non-negative. Stop = 1·ATR, target = 2·ATR,
max hold 5 days.

### `mean_reversion_v1` — oversold reversion

Long entry when RSI(14) < 30 and the close is within 2 % of the 50-day
SMA, while SPY is not in `distressed`. Stop = 1·ATR, target = 1·ATR
(1:1 R/R), max hold 3 days.

### Strategy governance

The EOD reviewer can *propose* rule changes — those proposals appear in
the AI decision log and in `data/ai_reviews.json`. It cannot apply them.
To accept a proposal: add a new versioned file (e.g.
`momentum_breakout_v1_1.py`) next to the old one, run a comparison
backtest, switch `config.ACTIVE_IDS`. This is deliberate friction.

---

## Risk framework

| Cap | Value |
|---|---:|
| Starting capital | $5,000 |
| Max risk per trade | 1.0 % of NAV |
| Max daily loss | 2.0 % of NAV |
| Max portfolio drawdown (shutdown) | 10.0 % |
| Max open positions | 3 |
| Max single-position exposure | 35 % of NAV |
| Leverage | none |

A traffic light is recomputed on every run:

- **Green** — risk normal, strategy active.
- **Yellow** — at 70 % of either the daily-loss or drawdown cap; new
  entries proceed cautiously.
- **Red** — daily-loss or drawdown cap breached. New entries paused;
  existing positions still stop / target / max-hold normally.
- **Black** — data feed failure. Trading halted.

---

## Daily workflow

```
20:30 ET (weekdays)
      │
      ▼
1. Load portfolio state            (data/portfolio_state.json)
2. Discover live candidates        (broad watchlist + Massive movers when enabled)
3. Pull fresh OHLCV                (yfinance, daily, auto-adjusted)
4. Enrich opportunity list         (Massive ratios + Benzinga consensus when enabled)
5. Pull headline sentiment         (Yahoo RSS + lexicon, optional)
6. Mark-to-market open positions   (today's close)
7. Apply stops / targets / MH      (intraday bar; stop precedes target)
8. Generate allocation targets     (SPY/QQQ/SMH/stocks/SHY/cash)
9. Append snapshot + close trades  (data/snapshots.json, data/trades.json)
10. Generate EOD review            (Anthropic or template)
11. Persist JSON + Supabase mirror (if env vars present)
```

The backtest in `python/backtest.py` runs the same risk engine and the
same strategy registry against historical data. Live and backtest paths
differ only in entry timing: the backtest opens on the next day's open;
the live job opens on today's close because the cron runs after the
session.

`data/portfolio_state.json` is intentionally persisted with the other
JSON outputs. The scheduled GitHub Action starts from a fresh checkout,
so this file is required to continue the paper book instead of
cold-starting the account back at `$5,000`.

---

## Run it yourself

Requires Python 3.11+. yfinance and pandas need an outbound connection;
GitHub Actions runners work out of the box.

```bash
git clone https://github.com/<your-fork>/greenlight-trader.git
cd greenlight-trader
pip install -r python/requirements.txt
cd python
python seed_history.py         # ~2y backtest → data/*.json
python run_daily.py            # appends today
```

Open `web/` for the Next.js variant, or build your own static page that
fetches the JSON files from `data/`. A self-contained example written in
plain HTML + Chart.js lives in the personal-site repo this project was
spun out of.

### Environment variables

All are optional. The engine runs without any of them.

| Variable | Effect when set |
|---|---|
| `ANTHROPIC_API_KEY` | EOD review goes to Claude Haiku instead of the template |
| `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | Engine mirrors writes to Postgres |
| `MASSIVE_API_KEY` or `POLYGON_API_KEY` | Adds Massive top movers, financial ratios, and Benzinga consensus ratings when the plan allows those datasets |

Local runs also reuse `/Users/yunhanzhang/Desktop/works/high-risk-symbols/.env.massive`
when those variables are not already exported. The secret file is shared in
place and must not be copied or committed.

---

## Compliance and risk disclaimer

This is a research and demonstration project. It is not investment advice.
Nothing here is suitable for live trading without substantial additional
work — broker integration, order management, regulatory review, monitoring,
and a much longer forward-test track record. The starting balance is
$5,000 of simulated capital; the system never connects to a real broker.

---

## License

MIT.
