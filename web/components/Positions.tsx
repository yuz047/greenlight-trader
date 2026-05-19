import type { Position } from "@/lib/data";

const fmt = (n?: number | null, d = 2) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const pcls = (n: number) =>
  !Number.isFinite(n) || n === 0 ? "" : n > 0 ? "num-pos" : "num-neg";

export default function Positions({ positions }: { positions: Position[] }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Current positions</div>
          <h2 className="mt-2">Open book</h2>
        </div>
        <span className="tag">{positions.length} open</span>
      </div>
      {positions.length === 0 ? (
        <div className="text-sm" style={{ color: "var(--ink-mute)" }}>No open positions.</div>
      ) : (
        <div className="table-wrap">
          <table className="gl">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Entry</th>
                <th className="text-right">Last</th>
                <th className="text-right">Stop</th>
                <th className="text-right">Target</th>
                <th className="text-right">Unrealized</th>
                <th>Strategy</th>
                <th>Thesis</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.symbol}>
                  <td className="symbol">{p.symbol}</td>
                  <td>{p.side}</td>
                  <td className="right">{p.quantity}</td>
                  <td className="right">${fmt(p.entry_price)}</td>
                  <td className="right">${fmt(p.last_price)}</td>
                  <td className="right">${fmt(p.stop_price)}</td>
                  <td className="right">${fmt(p.target_price)}</td>
                  <td className={`right ${pcls(p.unrealized_pnl)}`}>${fmt(p.unrealized_pnl)}</td>
                  <td><span className="tag tag-accent">{p.strategy_id}</span></td>
                  <td className="max-w-[320px] truncate" title={p.thesis}>{p.thesis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
