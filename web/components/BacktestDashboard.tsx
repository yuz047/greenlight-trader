import type { StrategyVersion } from "@/lib/data";

const fmt = (n: number | null | undefined, d = 2) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export default function BacktestDashboard({ strategies }: { strategies: StrategyVersion[] }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Strategies &amp; backtest</div>
          <h2 className="mt-2">Active versions</h2>
        </div>
      </div>
      {strategies.length === 0 ? (
        <div className="text-sm" style={{ color: "var(--ink-mute)" }}>No strategies recorded.</div>
      ) : (
        <div className="space-y-3">
          {strategies.map((s) => {
            const r = s.backtest_result || {};
            const rows = [
              ["Total return", fmt(((r.total_return as number) ?? 0) * 100, 2) + "%"],
              ["CAGR",         fmt(((r.cagr as number) ?? 0) * 100, 2) + "%"],
              ["Sharpe",       fmt(r.sharpe as number, 2)],
              ["Max DD",       fmt(((r.max_drawdown as number) ?? 0) * 100, 2) + "%"],
              ["Win rate",     fmt(((r.win_rate as number) ?? 0) * 100, 1) + "%"],
              ["# trades",     String(r.n_trades ?? "—")],
            ];
            return (
              <article
                key={s.strategy_id + s.version}
                className="border rounded-md p-4"
                style={{ borderColor: "var(--rule)", background: "var(--paper)" }}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <div>
                    <div className="eyebrow">v{s.version}</div>
                    <h3
                      className="font-display"
                      style={{
                        fontFamily: "var(--serif)", fontWeight: 600,
                        fontSize: 19, letterSpacing: "-0.01em",
                        margin: "6px 0 0", color: "var(--ink)",
                      }}
                    >
                      {s.strategy_id}
                    </h3>
                  </div>
                  <span className={`pill ${s.status === "active" ? "green" : ""}`}>{s.status}</span>
                </div>
                <p className="text-sm mt-2" style={{ color: "var(--ink-soft)" }}>{s.rules}</p>
                <div className="kpi-grid three mt-3" style={{ gap: 8 }}>
                  {rows.map(([k, v]) => (
                    <div
                      key={k as string}
                      style={{
                        padding: "8px 12px",
                        border: "1px solid var(--rule)",
                        borderRadius: 8,
                        background: "var(--panel)",
                      }}
                    >
                      <div className="label" style={{
                        fontFamily: "var(--mono)", fontSize: 10.5,
                        letterSpacing: "0.14em", textTransform: "uppercase",
                        color: "var(--ink-mute)",
                      }}>{k}</div>
                      <div className="value" style={{
                        fontFamily: "var(--display)", fontWeight: 600,
                        fontSize: 16, marginTop: 2,
                        fontVariantNumeric: "tabular-nums",
                      }}>{v}</div>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
