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

export default async function Home() {
  const d = await loadDashboard();
  const startingCapital = (d.riskConfig.starting_capital as number) || 1000;

  return (
    <main>
      <section className="container">
        <div className="page-head">
          <div className="eyebrow">GreenLight Trader · paper-trading lab</div>
          <h1>
            A $1,000 controlled-risk portfolio,
            <br />
            run by an AI trader with the discipline turned up.
          </h1>
          <p className="lede">
            GreenLight Trader is an end-of-day research system. The engine ingests free OHLCV
            and headline sentiment, generates rule-based candidates, filters them through a
            strict risk gate, and writes a human-readable EOD review every weekday after the
            US close. Capital preservation first — this is research, not investment advice.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <span className="pill">paper trading</span>
            <span className="pill">$1,000 book</span>
            <span className="pill">2 strategies</span>
            <span className="pill">1% risk per trade</span>
            <span className="pill">10% drawdown stop</span>
            <span className="pill">via {d.source}</span>
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
