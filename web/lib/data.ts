// Dashboard data layer.
// At build/request time we either:
//   - read from Supabase (if NEXT_PUBLIC_SUPABASE_URL + ANON_KEY are set), or
//   - read the JSON snapshots in ../data/ that the Python engine writes.
//
// The page itself doesn't care which source it gets — both branches return
// the same shape.

import fs from "node:fs";
import path from "node:path";

export type Snapshot = {
  date: string;
  equity: number;
  cash: number;
  market_value: number;
  daily_pnl: number;
  cumulative_pnl: number;
  drawdown: number;
  benchmark_equity?: number;
  portfolio_return?: number;
  benchmark_return?: number;
  alpha?: number;
  relative_drawdown?: number;
  spy_core_weight?: number;
  n_picks_open?: number;
};

export type Trade = {
  trade_id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_time?: string | null;
  entry_price?: number | null;
  exit_time?: string | null;
  exit_price?: number | null;
  pnl: number;
  strategy_id: string;
  reasoning: string;
  exit_reason?: string | null;
  holding_days: number;
};

export type Position = {
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  last_price: number;
  stop_price: number;
  target_price: number;
  max_hold_days: number;
  age_days: number;
  strategy_id: string;
  thesis: string;
  unrealized_pnl: number;
  notional: number;
  target_weight?: number;
  is_core?: boolean;
};

export type StrategyVersion = {
  strategy_id: string;
  version: string;
  rules: string;
  parameters: Record<string, unknown>;
  status: string;
  backtest_result?: Record<string, number | null>;
  created_at?: string;
};

export type CandidateResearch = {
  rank: number;
  symbol: string;
  opportunity_score: number;
  market_reward_score: number;
  forecast_health_score: number;
  valuation_health_score: number;
  quality_health_score: number;
  healthy_prediction: boolean;
  relative_strength_63d?: number | null;
  return_20d?: number | null;
  volume_ratio_20d?: number | null;
  extension_sma50?: number | null;
  consensus_upside?: number | null;
  consensus_price_target?: number | null;
  price_to_earnings?: number | null;
  price_to_sales?: number | null;
  return_on_equity?: number | null;
  source?: string;
};

export type Review = {
  review_date: string;
  summary: string;
  mistakes: string[] | Record<string, unknown>[];
  proposed_changes: Record<string, unknown>[];
  next_day_plan: string;
  light: "green" | "yellow" | "red" | "black" | string;
  light_reason: string;
  source: string;
};

export type SystemStatus = {
  light: "green" | "yellow" | "red" | "black" | string;
  reason: string;
  daily_loss_pct: number;
  drawdown_pct: number;
  peak_nav: number;
  as_of?: string;
  regime?: string;
  data?: { ok: boolean; synthetic?: boolean; stale_tickers?: number; as_of?: string };
};

export type Dashboard = {
  snapshots: Snapshot[];
  trades: Trade[];
  positions: Position[];
  strategies: StrategyVersion[];
  reviews: Review[];
  status: SystemStatus;
  metrics: Record<string, number | null>;
  riskConfig: Record<string, number>;
  decisionLog: any[];
  candidateResearch: CandidateResearch[];
  source: "supabase" | "local";
};

const DATA_DIR = path.join(process.cwd(), "..", "data");

function readJson<T>(name: string, fallback: T): T {
  const p = path.join(DATA_DIR, `${name}.json`);
  try {
    if (!fs.existsSync(p)) return fallback;
    return JSON.parse(fs.readFileSync(p, "utf8")) as T;
  } catch {
    return fallback;
  }
}

async function fromSupabase(): Promise<Dashboard | null> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  const { createClient } = await import("@supabase/supabase-js");
  const sb = createClient(url, key);

  const [snaps, trades, positions, strategies, reviews] = await Promise.all([
    sb.from("portfolio_snapshots").select("*").order("date", { ascending: true }),
    sb.from("trades").select("*").order("exit_time", { ascending: false }).limit(200),
    sb.from("positions").select("*"),
    sb.from("strategy_versions").select("*"),
    sb.from("ai_reviews").select("*").order("review_date", { ascending: false }).limit(10),
  ]);

  if (snaps.error) return null;
  const last = reviews.data?.[0];
  const localStatus = readJson<SystemStatus>("system_status", {} as any);
  const status: SystemStatus = {
    light: (last?.light as any) || (localStatus.light as any) || "green",
    reason: last?.light_reason || localStatus.reason || "",
    daily_loss_pct: localStatus.daily_loss_pct ?? 0,
    drawdown_pct: localStatus.drawdown_pct ?? 0,
    peak_nav: localStatus.peak_nav ?? 0,
    regime: localStatus.regime,
    data: localStatus.data,
  };

  return {
    snapshots: (snaps.data || []) as Snapshot[],
    trades: (trades.data || []) as Trade[],
    positions: (positions.data || []) as Position[],
    strategies: (strategies.data || []) as StrategyVersion[],
    reviews: (reviews.data || []) as Review[],
    status,
    metrics: readJson("metrics", {}),
    riskConfig: readJson("risk_config", {}),
    decisionLog: readJson("decision_log", []),
    candidateResearch: readJson("candidate_research", []),
    source: "supabase",
  };
}

function fromLocal(): Dashboard {
  return {
    snapshots: readJson<Snapshot[]>("snapshots", []),
    trades: readJson<Trade[]>("trades", []),
    positions: readJson<Position[]>("positions", []),
    strategies: readJson<StrategyVersion[]>("strategy_versions", []),
    reviews: readJson<Review[]>("ai_reviews", []),
    status: readJson<SystemStatus>("system_status", {
      light: "green", reason: "",
      daily_loss_pct: 0, drawdown_pct: 0, peak_nav: 0,
    }),
    metrics: readJson("metrics", {}),
    riskConfig: readJson("risk_config", {}),
    decisionLog: readJson("decision_log", []),
    candidateResearch: readJson("candidate_research", []),
    source: "local",
  };
}

export async function loadDashboard(): Promise<Dashboard> {
  const remote = await fromSupabase();
  if (remote && remote.snapshots.length) return remote;
  return fromLocal();
}
