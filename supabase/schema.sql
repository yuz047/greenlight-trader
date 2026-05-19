-- GreenLight Trader — Supabase schema
-- Run this once in your Supabase project's SQL editor.

create table if not exists portfolio_snapshots (
    id              text primary key,           -- = date (yyyy-mm-dd)
    date            date not null,
    equity          numeric not null,
    cash            numeric not null,
    market_value    numeric not null,
    daily_pnl       numeric not null,
    cumulative_pnl  numeric not null,
    drawdown        numeric not null,
    inserted_at     timestamptz default now()
);

create index if not exists ix_snapshots_date on portfolio_snapshots (date);

create table if not exists trades (
    trade_id      text primary key,
    symbol        text not null,
    side          text not null,
    quantity      integer not null,
    entry_time    timestamptz,
    entry_price   numeric,
    exit_time     timestamptz,
    exit_price    numeric,
    pnl           numeric,
    strategy_id   text,
    reasoning     text,
    exit_reason   text,
    holding_days  integer,
    inserted_at   timestamptz default now()
);

create index if not exists ix_trades_exit_time on trades (exit_time);
create index if not exists ix_trades_strategy on trades (strategy_id);

create table if not exists positions (
    id              text primary key,           -- = symbol
    symbol          text not null,
    side            text not null,
    quantity        integer not null,
    entry_price     numeric not null,
    entry_time      timestamptz,
    last_price      numeric,
    stop_price      numeric,
    target_price    numeric,
    max_hold_days   integer,
    age_days        integer,
    strategy_id     text,
    thesis          text,
    unrealized_pnl  numeric,
    notional        numeric,
    updated_at      timestamptz default now()
);

create table if not exists strategy_versions (
    id               text primary key,        -- = strategy_id@version
    strategy_id      text not null,
    version          text not null,
    rules            text,
    parameters       jsonb,
    status           text default 'active',
    backtest_result  jsonb,
    created_at       date default now()
);

create table if not exists ai_reviews (
    review_date       date primary key,
    summary           text,
    mistakes          jsonb,
    proposed_changes  jsonb,
    next_day_plan     text,
    light             text,
    light_reason      text,
    source            text
);

-- ---- Row Level Security: public read-only -----------------------------
alter table portfolio_snapshots enable row level security;
alter table trades              enable row level security;
alter table positions           enable row level security;
alter table strategy_versions   enable row level security;
alter table ai_reviews          enable row level security;

-- Anyone (including the anon key used by the Vercel frontend) can SELECT.
-- Writes are gated to the service role key, which lives only in GH Actions.
create policy if not exists "public_read_snapshots"  on portfolio_snapshots for select using (true);
create policy if not exists "public_read_trades"     on trades              for select using (true);
create policy if not exists "public_read_positions"  on positions           for select using (true);
create policy if not exists "public_read_strategies" on strategy_versions   for select using (true);
create policy if not exists "public_read_reviews"    on ai_reviews          for select using (true);
