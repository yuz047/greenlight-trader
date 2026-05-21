import type { Snapshot } from "@/lib/data";

const fmt = (n: number, d = 2) =>
  Number.isFinite(n)
    ? n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
    : "—";

const pcls = (n: number) =>
  !Number.isFinite(n) || n === 0 ? "" : n > 0 ? "num-pos" : "num-neg";

export default function PortfolioOverview({
  snapshots, startingCapital,
}: { snapshots: Snapshot[]; startingCapital: number }) {
  const last = snapshots.at(-1);
  if (!last) {
    return (
      <section className="panel">
        <div className="panel-head">
          <div className="eyebrow">Portfolio overview</div>
        </div>
        <div className="text-sm" style={{ color: "var(--ink-mute)" }}>No data yet — run the engine.</div>
      </section>
    );
  }
  const cumPct = (last.equity / startingCapital - 1) * 100;
  const dailyPct = last.equity > 0 ? (last.daily_pnl / (last.equity - last.daily_pnl)) * 100 : 0;

  const items = [
    { k: "Equity",         v: "$" + fmt(last.equity),         sub: `inception $${fmt(startingCapital, 0)}` },
    { k: "Cash",           v: "$" + fmt(last.cash),           sub: "available" },
    { k: "Market value",   v: "$" + fmt(last.market_value),   sub: "target sleeves" },
    { k: "Daily PnL",
      v: (last.daily_pnl >= 0 ? "+" : "") + "$" + fmt(last.daily_pnl),
      sub: `${dailyPct >= 0 ? "+" : ""}${fmt(dailyPct, 2)}%`,
      cls: pcls(last.daily_pnl) },
    { k: "Cumulative PnL",
      v: (last.cumulative_pnl >= 0 ? "+" : "") + "$" + fmt(last.cumulative_pnl),
      sub: `${cumPct >= 0 ? "+" : ""}${fmt(cumPct, 2)}%`,
      cls: pcls(last.cumulative_pnl) },
    { k: "Drawdown",
      v: fmt(last.drawdown * 100, 2) + "%",
      sub: "from peak",
      cls: last.drawdown > 0 ? "num-neg" : "" },
    { k: "Alpha vs SPY",
      v: `${(last.alpha ?? 0) >= 0 ? "+" : ""}${fmt((last.alpha ?? 0) * 100, 2)}%`,
      sub: `SPY ${fmt((last.benchmark_return ?? 0) * 100, 2)}%`,
      cls: pcls(last.alpha ?? 0) },
    { k: "SPY weight",
      v: fmt((last.spy_core_weight ?? 0) * 100, 1) + "%",
      sub: `${last.n_picks_open ?? 0} non-SPY sleeve${(last.n_picks_open ?? 0) === 1 ? "" : "s"}` },
  ];

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Portfolio overview</div>
          <h2 className="mt-2">${fmt(startingCapital, 0)} adaptive allocation book</h2>
        </div>
        <span className="tag">as of {last.date}</span>
      </div>
      <div className="kpi-grid three">
        {items.map((it) => (
          <div key={it.k} className="kpi-tile">
            <div className="label">{it.k}</div>
            <div className={`value ${it.cls || ""}`}>{it.v}</div>
            <div className="sub">{it.sub}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
