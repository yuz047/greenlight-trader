import type { Trade } from "@/lib/data";

const fmt = (n?: number | null, d = 2) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const pcls = (n: number) =>
  !Number.isFinite(n) || n === 0 ? "" : n > 0 ? "num-pos" : "num-neg";

export default function TradesTable({ trades }: { trades: Trade[] }) {
  const recent = [...trades]
    .filter((t) => t.exit_time)
    .sort((a, b) => (a.exit_time! < b.exit_time! ? 1 : -1))
    .slice(0, 25);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Trades &amp; reasoning</div>
          <h2 className="mt-2">Closed trades · most recent first</h2>
        </div>
        <span className="tag">last {recent.length}</span>
      </div>
      {recent.length === 0 ? (
        <div className="text-sm" style={{ color: "var(--ink-mute)" }}>No closed trades yet.</div>
      ) : (
        <div className="table-wrap">
          <table className="gl">
            <thead>
              <tr>
                <th>Exit</th>
                <th>Symbol</th>
                <th>Strategy</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Entry</th>
                <th className="text-right">Exit</th>
                <th className="text-right">PnL</th>
                <th className="text-right">Days</th>
                <th>Reason</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((t) => (
                <tr key={t.trade_id}>
                  <td><span className="tag">{t.exit_time?.slice(0, 10)}</span></td>
                  <td className="symbol">{t.symbol}</td>
                  <td><span className="tag tag-accent">{t.strategy_id}</span></td>
                  <td className="right">{t.quantity}</td>
                  <td className="right">${fmt(t.entry_price)}</td>
                  <td className="right">${fmt(t.exit_price)}</td>
                  <td className={`right ${pcls(t.pnl)}`}>${fmt(t.pnl)}</td>
                  <td className="right">{t.holding_days}</td>
                  <td><span className="tag">{t.exit_reason}</span></td>
                  <td className="max-w-[380px] truncate" title={t.reasoning}>{t.reasoning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
