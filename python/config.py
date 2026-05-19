"""Central config for GreenLight Trader.

Everything that the system treats as a tunable knob lives here so that
risk caps, the watchlist, and the active strategy versions are obvious
and auditable in one place.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path

# --- Paths --------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- Universe -----------------------------------------------------------
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN"]
BENCHMARK = "SPY"

# --- Account-level risk caps (V1, $1,000 book) --------------------------
@dataclass(frozen=True)
class RiskCaps:
    starting_capital: float = 1_000.0
    max_risk_per_trade_pct: float = 0.01      # 1.0%
    max_daily_loss_pct: float = 0.02          # 2.0%
    max_drawdown_pct: float = 0.10            # 10.0% — hard stop
    max_open_positions: int = 3
    max_single_position_pct: float = 0.35     # 35% NAV per name
    min_dollar_position: float = 50.0         # don't bother with <$50 trades

RISK = RiskCaps()

# --- Active strategies --------------------------------------------------
# Strategy logic lives in the python/strategies/ package and is auto-discovered.
# To swap or add a strategy: drop a new file into strategies/, give it a unique
# MANIFEST.id, and list the id here. Nothing else needs to change.
ACTIVE_IDS = [
    "momentum_breakout_v1",
    "mean_reversion_v1",
    "stock_pitcher_v1",
]

# --- Backtest defaults --------------------------------------------------
BACKTEST_DAYS = 504  # ~2 trading years

# --- Supabase / LLM env -------------------------------------------------
# These are read from env at runtime; nothing secret lives in this file.
SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"
ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"

def risk_as_dict() -> dict:
    return asdict(RISK)
