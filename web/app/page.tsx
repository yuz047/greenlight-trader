import { loadDashboard } from "@/lib/data";
import SystemStatus from "@/components/SystemStatus";
import PortfolioOverview from "@/components/PortfolioOverview";
import EquityChart from "@/components/EquityChart";
import Positions from "@/components/Positions";
import TradesTable from "@/components/TradesTable";
import RiskDashboard from "@/components/RiskDashboard";
import BacktestDashboard from "@/components/BacktestDashboard";
import DecisionLog from "@/components/DecisionLog";

export const revalidate = 60; // re-fetch from Supabase at most once a minute

const fmtUsd = (n: number, digits = 0) =>
  "$" + n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

const fmtPct = (n: number, digits = 1) =>
  `${n >= 0 ? "+" : ""}${(n * 100).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;

export default async function Home() {
  const d = await loadDashboard();
  const startingCapital = (d.riskConfig.starting_capital as number) || 5000;
  const last = d.snapshots.at(-1);
  const equity = last?.equity ?? startingCapital;
  const alpha = last?.alpha ?? ((d.metrics.alpha_total as number) || 0);
  const portfolioReturn = last?.portfolio_return ?? (equity / startingCapital - 1);
  const cashWeight = last && last.equity > 0 ? last.cash / last.equity : 0;
  const allocation = [
    { symbol: "SPY", weight: last?.spy_core_weight ?? 0 },
    ...d.positions.map((p) => ({ symbol: p.symbol, weight: p.target_weight ?? 0 })),
    { symbol: "CASH", weight: cashWeight },
  ].filter((sleeve) => sleeve.weight > 0.005);

  return (
    <main>
      <section className="container">
        <div className="page-head trader-hero">
          <div className="hero-grid">
            <div className="hero-copy">
              <div className="eyebrow">Adaptive allocation lab · {d.source}</div>
              <h1>GreenLight Trader</h1>
              <p className="lede">
                A {fmtUsd(startingCapital)} paper book that shifts between SPY ballast,
                QQQ and semiconductor exposure, safety sleeves, and cash when volatility
                says the next dollar should wait.
              </p>
            </div>

            <div className="hero-readout" aria-label="Current portfolio readout">
              <div>
                <div className="label">Equity</div>
                <div className="value">{fmtUsd(equity, 2)}</div>
              </div>
              <div>
                <div className="label">Return</div>
                <div className={`value ${portfolioReturn >= 0 ? "num-pos" : "num-neg"}`}>
                  {fmtPct(portfolioReturn, 2)}
                </div>
              </div>
              <div>
                <div className="label">Alpha vs SPY</div>
                <div className={`value ${alpha >= 0 ? "num-pos" : "num-neg"}`}>
                  {fmtPct(alpha, 2)}
                </div>
              </div>
              <div>
                <div className="label">Regime</div>
                <div className="value">{d.status.regime || "n/a"}</div>
              </div>
            </div>
          </div>

          <div className="hero-allocation" aria-label="Current target allocation">
            <div className="allocation-head">
              <span className="eyebrow">Current target</span>
              <span className="tag">as of {last?.date || d.status.as_of || "n/a"}</span>
            </div>
            <div className="allocation-track">
              {allocation.map((sleeve) => (
                <div
                  key={sleeve.symbol}
                  className={`allocation-segment ${sleeve.symbol.toLowerCase()}`}
                  style={{ width: `${Math.max(sleeve.weight * 100, 2)}%` }}
                  title={`${sleeve.symbol} ${(sleeve.weight * 100).toFixed(1)}%`}
                />
              ))}
            </div>
            <div className="allocation-legend">
              {allocation.map((sleeve) => (
                <span key={sleeve.symbol}>
                  {sleeve.symbol} {(sleeve.weight * 100).toFixed(0)}%
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="container" style={{ paddingTop: 28, paddingBottom: 8 }}>
        <SystemStatus status={d.status} />
      </section>

      <section className="container" style={{ paddingTop: 16, paddingBottom: 8 }}>
        <div className="grid lg:grid-cols-2 gap-4">
          <PortfolioOverview snapshots={d.snapshots} startingCapital={startingCapital} />
          <EquityChart snapshots={d.snapshots} startingCapital={startingCapital} />
        </div>
      </section>

      <section className="container" style={{ paddingTop: 16, paddingBottom: 8 }}>
        <Positions positions={d.positions} />
      </section>

      <section className="container" style={{ paddingTop: 16, paddingBottom: 8 }}>
        <div className="grid lg:grid-cols-2 gap-4">
          <RiskDashboard metrics={d.metrics} riskConfig={d.riskConfig} />
          <BacktestDashboard strategies={d.strategies} />
        </div>
      </section>

      <section className="container" style={{ paddingTop: 16, paddingBottom: 8 }}>
        <TradesTable trades={d.trades} />
      </section>

      <section className="container" style={{ paddingTop: 16, paddingBottom: 28 }}>
        <DecisionLog reviews={d.reviews} />
      </section>
    </main>
  );
}
