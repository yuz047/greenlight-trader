type Metrics = Record<string, number | null>;
type RiskCfg = Record<string, number>;

const fmt = (n: number | null | undefined, d = 2) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export default function RiskDashboard({
  metrics, riskConfig,
}: { metrics: Metrics; riskConfig: RiskCfg }) {
  const items = [
    { k: "Sharpe (ann.)",  v: fmt(metrics.sharpe as number, 2) },
    { k: "Sortino (ann.)", v: fmt(metrics.sortino as number, 2) },
    { k: "Alpha total",    v: fmt((metrics.alpha_total as number) * 100, 2) + "%" },
    { k: "Info ratio",     v: fmt(metrics.info_ratio as number, 2) },
    { k: "Max drawdown",   v: fmt((metrics.max_drawdown as number) * 100, 2) + "%" },
    { k: "Max rel. DD",    v: fmt((metrics.max_relative_drawdown as number) * 100, 2) + "%" },
    { k: "Vol (ann.)",     v: fmt((metrics.vol_annualized as number) * 100, 2) + "%" },
    { k: "Benchmark",      v: fmt((metrics.benchmark_total_return as number) * 100, 2) + "%" },
    { k: "# Trades",       v: String(metrics.n_trades ?? 0) },
  ];

  const caps = [
    { k: "Target alpha",        v: fmt(riskConfig.target_alpha_pct * 100, 1) + "%" },
    { k: "Max relative DD",     v: fmt(riskConfig.max_relative_drawdown_pct * 100, 1) + "%" },
    { k: "Max sleeves",         v: String(riskConfig.max_picks_open ?? "—") },
    { k: "Default sleeve",      v: fmt(riskConfig.pick_weight_per_position * 100, 1) + "%" },
    { k: "Min SPY ballast",     v: fmt(riskConfig.spy_core_min_weight * 100, 0) + "%" },
  ];

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Risk dashboard</div>
          <h2 className="mt-2">Realized risk &amp; in-force caps</h2>
        </div>
      </div>
      <div className="kpi-grid five">
        {items.map((it) => (
          <div key={it.k} className="kpi-tile">
            <div className="label">{it.k}</div>
            <div className="value">{it.v}</div>
          </div>
        ))}
      </div>
      <div className="mt-5">
        <div className="eyebrow mb-2" style={{ color: "var(--ink-mute)" }}>Risk caps in force</div>
        <div className="kpi-grid five risk-cap-grid">
          {caps.map((c) => (
            <div key={c.k} className="kpi-tile accent">
              <div className="label">{c.k}</div>
              <div className="value">{c.v}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
