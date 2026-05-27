import type { CandidateResearch } from "@/lib/data";

const fmt = (n?: number | null, d = 2) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

const pct = (n?: number | null, d = 1) =>
  n == null || !Number.isFinite(n) ? "—" : `${n >= 0 ? "+" : ""}${fmt(n * 100, d)}%`;

const cls = (n?: number | null) =>
  n == null || !Number.isFinite(n) || n === 0 ? "" : n > 0 ? "num-pos" : "num-neg";

const status = (c: CandidateResearch) => {
  const labels = [];
  if (c.healthy_prediction) labels.push("healthy");
  if (c.must_review) labels.push("watch");
  return labels.length ? labels : ["review"];
};

export default function CandidateResearchPanel({ candidates }: { candidates: CandidateResearch[] }) {
  const choices = candidates;
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Live opportunity list</div>
          <h2 className="mt-2">Market-rewarded stocks with healthier forecasts</h2>
        </div>
        <span className="tag">{candidates.length} tracked</span>
      </div>
      {choices.length === 0 ? (
        <div className="text-sm" style={{ color: "var(--ink-mute)" }}>
          No candidate research yet. The next daily run will publish the live list.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="gl">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Symbol</th>
                <th>Status</th>
                <th>Setup</th>
                <th className="text-right">Score</th>
                <th className="text-right">Tech</th>
                <th className="text-right">RS 63d</th>
                <th className="text-right">20d</th>
                <th className="text-right">Upside</th>
                <th className="text-right">Forecast</th>
                <th className="text-right">P/E</th>
              </tr>
            </thead>
            <tbody>
              {choices.map((c) => (
                <tr key={`${c.rank}-${c.symbol}`}>
                  <td><span className="tag">#{c.rank}</span></td>
                  <td className="symbol">{c.symbol}</td>
                  <td>
                    {status(c).map((label) => (
                      <span key={label} className={`pill ml-2 ${label === "healthy" ? "green" : ""}`}>{label}</span>
                    ))}
                  </td>
                  <td><span className="tag">{c.setup || "trend"}</span></td>
                  <td className={`right ${cls(c.opportunity_score)}`}>{fmt(c.opportunity_score, 2)}</td>
                  <td className={`right ${cls(c.technical_score ?? c.market_reward_score)}`}>
                    {fmt(c.technical_score ?? c.market_reward_score, 2)}
                  </td>
                  <td className={`right ${cls(c.relative_strength_63d)}`}>{pct(c.relative_strength_63d)}</td>
                  <td className={`right ${cls(c.return_20d)}`}>{pct(c.return_20d)}</td>
                  <td className={`right ${cls(c.consensus_upside)}`}>{pct(c.consensus_upside)}</td>
                  <td className={`right ${cls(c.forecast_health_score)}`}>{fmt(c.forecast_health_score, 2)}</td>
                  <td className="right">{fmt(c.price_to_earnings, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
