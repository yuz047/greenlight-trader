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
          <div className="eyebrow">GreenLight Trader · adaptive allocation lab</div>
          <h1>
            A ${startingCapital.toLocaleString()} paper portfolio,
            <br />
            rotating through SPY, tech, semis, safety, and cash.
          </h1>
          <p className="lede">
            GreenLight Trader is an end-of-day research system. The engine ingests OHLCV,
            VIX, and trend data, then sets target weights across SPY, QQQ, SMH, selective
            tech/semiconductor sleeves, SHY, and cash. It avoids stretched entries, keeps
            single-stock bets small, and gets more defensive during major drops.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <span className="pill">paper trading</span>
            <span className="pill">${startingCapital.toLocaleString()} book</span>
            <span className="pill">adaptive tech/semis</span>
            <span className="pill">VIX stress gate</span>
            <span className="pill">cash reserve</span>
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
