import type { SystemStatus } from "@/lib/data";

const LIGHT = {
  green:  { label: "GREEN LIGHT",  blurb: "Strategy active, risk normal.", color: "var(--ok)" },
  yellow: { label: "YELLOW LIGHT", blurb: "Trade cautiously, elevated risk.", color: "var(--warn)" },
  red:    { label: "RED LIGHT",    blurb: "Trading paused.", color: "var(--stop)" },
  black:  { label: "BLACK LIGHT",  blurb: "System/data failure, no trading allowed.", color: "var(--ink-soft)" },
} as const;

export default function SystemStatus({ status }: { status: SystemStatus }) {
  const key = (status.light in LIGHT ? status.light : "green") as keyof typeof LIGHT;
  const l = LIGHT[key];
  return (
    <section className={`status-banner ${key}`}>
      <div
        className="light-dot"
        style={{ background: l.color, boxShadow: `0 0 12px ${l.color}88` }}
      />
      <div className="flex-1 min-w-0">
        <div className="eyebrow">System status</div>
        <div className={`label ${key} mt-1`}>{l.label}</div>
        <div className="text-[14px] mt-1" style={{ color: "var(--ink-soft)" }}>
          {status.reason || l.blurb}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="tag">regime · <span className="tag-accent">{status.regime || "n/a"}</span></div>
        <div className="tag mt-1">
          data ·{" "}
          <span className={status.data?.ok ? "num-pos" : "num-neg"}>
            {status.data?.ok ? "ok" : "stale"}
          </span>
          {status.data?.synthetic && (
            <span style={{ color: "var(--warn)" }}> · synthetic</span>
          )}
        </div>
        {status.as_of && <div className="tag mt-1">as of {status.as_of}</div>}
      </div>
    </section>
  );
}
