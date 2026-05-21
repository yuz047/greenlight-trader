"use client";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip,
  ReferenceLine, AreaChart, Area, CartesianGrid,
} from "recharts";
import type { Snapshot } from "@/lib/data";

const fmtUsd = (n: number) =>
  "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });

const AXIS_TICK = { fill: "#767a82", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" };
const TOOLTIP_STYLE = {
  background: "#ffffff",
  border: "1px solid #e6e1d3",
  borderRadius: 8,
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 12,
};

export default function EquityChart({
  snapshots, startingCapital,
}: { snapshots: Snapshot[]; startingCapital: number }) {
  const data = snapshots.map((s) => ({
    date: s.date,
    equity: s.equity,
    benchmark: s.benchmark_equity,
    drawdown: -(s.drawdown * 100),
  }));

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Equity curve</div>
          <h2 className="mt-2">Performance since inception</h2>
        </div>
        <span className="tag">benchmark · ${startingCapital.toLocaleString()}</span>
      </div>

      <div style={{ width: "100%", height: 230 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 5, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#e6e1d3" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={AXIS_TICK} minTickGap={48} stroke="#cfc8b6" />
            <YAxis
              domain={["dataMin - 10", "dataMax + 10"]}
              tick={AXIS_TICK}
              tickFormatter={(v) => fmtUsd(v as number)}
              width={70}
              stroke="#cfc8b6"
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={{ color: "#45494f" }}
              formatter={(v: number) => fmtUsd(v)}
            />
            <ReferenceLine y={startingCapital} stroke="#767a82" strokeDasharray="4 4" />
            <Line type="monotone" dataKey="benchmark" stroke="#767a82" dot={false} strokeWidth={1.5} strokeDasharray="5 4" />
            <Line type="monotone" dataKey="equity" stroke="#1f3a5f" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4">
        <div className="eyebrow mb-1" style={{ color: "var(--ink-mute)" }}>Drawdown</div>
        <div style={{ width: "100%", height: 90 }}>
          <ResponsiveContainer>
            <AreaChart data={data} margin={{ top: 5, right: 12, left: 0, bottom: 0 }}>
              <XAxis dataKey="date" hide />
              <YAxis
                domain={["dataMin", 0]}
                tick={AXIS_TICK}
                width={50}
                stroke="#cfc8b6"
                tickFormatter={(v) => `${(v as number).toFixed(1)}%`}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v: number) => `${v.toFixed(2)}%`}
              />
              <Area
                type="monotone"
                dataKey="drawdown"
                stroke="#9b2c1f"
                fill="#9b2c1f22"
                strokeWidth={1.5}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}
