import type { Review } from "@/lib/data";

export default function DecisionLog({ reviews }: { reviews: Review[] }) {
  const ordered = [...reviews]
    .sort((a, b) => (a.review_date < b.review_date ? 1 : -1))
    .slice(0, 5);

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">AI decision log</div>
          <h2 className="mt-2">End-of-day reviews</h2>
        </div>
      </div>
      {ordered.length === 0 ? (
        <div className="text-sm" style={{ color: "var(--ink-mute)" }}>No reviews yet.</div>
      ) : (
        <div className="space-y-4">
          {ordered.map((r) => {
            const lightCls =
              r.light === "green"  ? "green" :
              r.light === "yellow" ? "yellow" :
              r.light === "red"    ? "red"    : "black";
            return (
              <article key={r.review_date} className="callout">
                <header className="flex items-baseline justify-between gap-3 mb-2">
                  <div className="tag">
                    <span style={{ color: "var(--ink-soft)" }}>{r.review_date}</span>
                    {" · EOD review"}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="tag">via {r.source}</span>
                    <span className={`pill ${lightCls}`}>{r.light?.toUpperCase()}</span>
                  </div>
                </header>

                <p style={{
                  margin: 0, color: "var(--ink)",
                  fontSize: 15.5, lineHeight: 1.6,
                }}>
                  {r.summary}
                </p>

                {Array.isArray(r.mistakes) && r.mistakes.length > 0 && (
                  <div className="mt-3">
                    <div className="eyebrow mb-1" style={{ color: "var(--stop)" }}>Mistakes</div>
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {r.mistakes.map((m, i) => (
                        <li
                          key={i}
                          style={{
                            color: "var(--ink-soft)", fontSize: 14.5, lineHeight: 1.6,
                            margin: "4px 0",
                          }}
                        >
                          {typeof m === "string" ? m : JSON.stringify(m)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {Array.isArray(r.proposed_changes) && r.proposed_changes.length > 0 && (
                  <div className="mt-3 note-left">
                    <div className="eyebrow mb-1" style={{ color: "var(--accent)" }}>
                      Proposed · needs backtest approval
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {r.proposed_changes.map((c: any, i) => (
                        <li
                          key={i}
                          style={{
                            color: "var(--ink)", fontSize: 14.5, lineHeight: 1.6,
                            margin: "4px 0",
                          }}
                        >
                          <strong style={{ color: "var(--accent)" }}>
                            {c.strategy || c.strategy_id || "strategy"}
                          </strong>
                          {": "}{c.change}{" — "}
                          <span style={{ color: "var(--ink-soft)" }}>{c.reason}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {r.next_day_plan && (
                  <div className="mt-3">
                    <div className="eyebrow mb-1" style={{ color: "var(--ink-mute)" }}>
                      Next day plan
                    </div>
                    <p style={{
                      margin: 0, color: "var(--ink-soft)",
                      fontSize: 14.5, lineHeight: 1.6,
                    }}>
                      {r.next_day_plan}
                    </p>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
