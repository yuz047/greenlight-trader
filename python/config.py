"""Central configuration for Greenlight 2.0.

The constants in this file define the mandate and guardrails. They should stay
boring and explicit: production behavior is deterministic and reviewable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache" / "massive"
WEB_DIR = ROOT / "web"

for path in (DATA_DIR, CACHE_DIR, WEB_DIR):
    path.mkdir(parents=True, exist_ok=True)


def load_local_env(path: Path | None = None) -> None:
    """Load gitignored local env files without overwriting process env."""

    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()


@dataclass(frozen=True)
class Mandate:
    starting_capital: float = 5_000.0
    benchmark: str = "SPY"
    secondary_growth_anchor: str = "QQQ"
    defensive_anchor: str = "SGOV"
    objective: str = "Beat SPY on a risk-adjusted basis."

    max_absolute_drawdown_pct: float = 0.25
    max_relative_drawdown_pct: float = 0.12
    max_single_stock_weight: float = 0.08
    max_etf_weight: float = 0.25
    max_sector_weight: float = 0.35
    max_theme_weight: float = 0.25
    max_top3_weight: float = 0.60
    max_cash_or_defensive_weight: float = 1.00

    min_trade_dollars: float = 25.0
    min_rebalance_days: int = 5
    drift_threshold: float = 0.05
    signal_persistence_days: int = 3
    max_daily_turnover: float = 0.30

    min_price: float = 3.0
    min_avg_dollar_volume: float = 2_000_000.0
    min_market_cap: float = 100_000_000.0
    volatility_floor: float = 0.08
    max_candidates_per_sleeve: int = 8
    critical_stale_days: int = 5


MANDATE = Mandate()


MASSIVE_API_KEY_ENVS = ("MASSIVE_API_KEY", "POLYGON_API_KEY")
MASSIVE_BASE_URL_ENV = "MASSIVE_API_BASE_URL"
DEFAULT_MASSIVE_BASE_URL = "https://api.polygon.io"

DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
DEEPSEEK_MODEL_ENV = "DEEPSEEK_MODEL"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"


CORE_ANCHORS = {
    "SPY": {
        "asset_type": "benchmark",
        "category": "broad_market",
        "sector": "Broad Market",
        "theme": "S&P 500",
        "reason": "permanent benchmark/core anchor",
    },
    "QQQ": {
        "asset_type": "benchmark",
        "category": "growth_anchor",
        "sector": "Broad Growth",
        "theme": "Nasdaq 100",
        "reason": "regime-dependent growth anchor",
    },
    "SGOV": {
        "asset_type": "cash_proxy",
        "category": "defensive",
        "sector": "Cash",
        "theme": "Treasury Bills",
        "reason": "defensive/cash proxy",
    },
}


# Dynamic ETF pool. None of these are permanent allocation winners.
ETF_POOL = {
    "XLK": ("sector", "Technology", "Technology"),
    "XLE": ("sector", "Energy", "Energy"),
    "XLF": ("sector", "Financials", "Financials"),
    "XLV": ("sector", "Health Care", "Health Care"),
    "XLY": ("sector", "Consumer Discretionary", "Consumer Discretionary"),
    "XLP": ("sector", "Consumer Staples", "Consumer Staples"),
    "XLI": ("sector", "Industrials", "Industrials"),
    "XLB": ("sector", "Materials", "Materials"),
    "XLU": ("sector", "Utilities", "Utilities"),
    "XLRE": ("sector", "Real Estate", "Real Estate"),
    "XLC": ("sector", "Communication Services", "Communication Services"),
    "SMH": ("industry", "Technology", "Semiconductors"),
    "XBI": ("industry", "Health Care", "Biotech"),
    "KRE": ("industry", "Financials", "Regional Banks"),
    "IWM": ("broad_market", "Small Cap", "Russell 2000"),
    "IWC": ("broad_market", "Micro Cap", "Micro Cap"),
    "MTUM": ("factor", "Factor", "Momentum"),
    "QUAL": ("factor", "Factor", "Quality"),
    "VLUE": ("factor", "Factor", "Value"),
    "USMV": ("factor", "Factor", "Minimum Volatility"),
    "ARKK": ("theme", "Innovation", "Disruptive Innovation"),
    "ICLN": ("theme", "Clean Energy", "Clean Energy"),
    "BOTZ": ("theme", "Robotics", "Robotics/AI"),
    "HACK": ("theme", "Cybersecurity", "Cybersecurity"),
    "TLT": ("rates", "Rates", "Long Treasuries"),
    "IEF": ("rates", "Rates", "Intermediate Treasuries"),
    "SHY": ("defensive", "Rates", "Short Treasuries"),
    "GLD": ("defensive", "Commodities", "Gold"),
}


STOCK_SEED_POOL = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA",
    "LLY", "JPM", "V", "MA", "COST", "NFLX", "AMD", "CRM", "NOW", "PANW",
    "CRWD", "PLTR", "UBER", "SHOP", "MELI", "GE", "ETN", "VRT", "CEG",
    "ISRG", "VRTX", "REGN", "TMO", "COIN", "HOOD", "SNOW", "DDOG", "NET",
]


DEFAULT_STOCK_SCORE_WEIGHTS = {
    "information": 0.50,
    "leadership": 0.30,
    "timing": 0.20,
}

DEFAULT_ETF_SCORE_WEIGHTS = {
    "leadership": 0.40,
    "regime_fit": 0.25,
    "diversification": 0.20,
    "timing": 0.15,
}


REGIME_BUDGETS = {
    "RISK_ON": {
        "spy": 0.40,
        "qqq": 0.20,
        "dynamic_etf": 0.15,
        "stock": 0.20,
        "defensive": 0.05,
        "agent_experimental": 0.00,
    },
    "NEUTRAL": {
        "spy": 0.50,
        "qqq": 0.10,
        "dynamic_etf": 0.10,
        "stock": 0.10,
        "defensive": 0.20,
        "agent_experimental": 0.00,
    },
    "FEAR": {
        "spy": 0.30,
        "qqq": 0.05,
        "dynamic_etf": 0.05,
        "stock": 0.05,
        "defensive": 0.55,
        "agent_experimental": 0.00,
    },
    "STRESS": {
        "spy": 0.20,
        "qqq": 0.00,
        "dynamic_etf": 0.00,
        "stock": 0.00,
        "defensive": 0.80,
        "agent_experimental": 0.00,
    },
    "DATA_FAILURE": {
        "spy": 0.00,
        "qqq": 0.00,
        "dynamic_etf": 0.00,
        "stock": 0.00,
        "defensive": 1.00,
        "agent_experimental": 0.00,
    },
}


REQUIRED_OUTPUTS = [
    "snapshots.json",
    "portfolio_state.json",
    "candidate_universe.json",
    "candidate_scores.json",
    "selected_etfs.json",
    "target_allocations.json",
    "execution_decisions.json",
    "decision_logs.json",
    "system_status.json",
    "benchmark_metrics.json",
    "benchmark_snapshots.json",
    "weight_reviews.json",
    "review_events.json",
    "learning_report.md",
    "comparison_report.md",
    "ai_reviews.json",
]


HIGH_RISK_SYMBOLS_PATH = ROOT.parent.parent / "high-risk-symbols" / "data" / "symbols.json"


def mandate_dict() -> dict:
    return asdict(MANDATE)


def data_path(name: str) -> Path:
    return DATA_DIR / name
