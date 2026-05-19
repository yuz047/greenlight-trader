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
    { k: "Max drawdown",   v: fmt((metrics.max_drawdown as number) * 100, 2) + "%" },
    { k: "Vol (ann.)",     v: fmt((metrics.vol_annualized as number) * 100, 2) + "%" },
    { k: "Win rate",       v: fmt((metrics.win_rate as number) * 100, 1) + "%" },
    { k: "Profit factor",  v: metrics.profit_factor == null ? "—" : fmt(metrics.profit_factor as number, 2) },
    { k: "Avg win",        v: "$" + fmt(metrics.avg_win as number) },
    { k: "Avg loss",       v: "$" + fmt(metrics.avg_loss as number) },
    { k: "Largest loss",   v: "$" + fmt(metrics.largest_loss as number) },
    { k: "# Trades",       v: String(metrics.n_trades ?? "—") },
  ];

  const caps = [
    { k: "Risk / trade",        v: fmt(riskConfig.max_risk_per_trade_pct * 100, 2) + "%" },
    { k: "Daily loss cap",      v: fmt(riskConfig.max_daily_loss_pct * 100, 2) + "%" },
    { k: "Max drawdown cap",    v: fmt(riskConfig.max_drawdown_pct * 100, 2) + "%" },
    { k: "Max open positions",  v: String(riskConfig.max_open_positions ?? "—") },
    { k: "Max single position", v: fmt(riskConfig.max_single_position_pct * 100, 0) + "%" },
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
        <div className="kpi-grid five">
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
