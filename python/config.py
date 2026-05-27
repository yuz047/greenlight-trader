"""Central config for GreenLight Trader.

V2 mandate: enhanced-index relative to SPY.
  - Target return:        SPY + 10% over 2 years (≈ +5% / year alpha)
  - Max relative drawdown: trailing SPY by no more than 5%

The book holds SPY as a baseline and substitutes portions with
high-conviction pitcher picks. The risk gate enforces the relative
drawdown cap, not an absolute one — SPY is the floor, not cash.
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
CORE_UNIVERSE = [
    "SPY", "QQQ", "SHY", "^VIX",
    "SMH", "NVDA", "AVGO", "AMD", "TSM",
    "GOOGL", "MSFT", "AMZN", "META", "AAPL", "TSLA",
]

# Must-watch mega-cap/liquid leaders. They are not automatic buys, but they
# should never disappear from the daily choice set just because a short-term
# technical score falls below smaller momentum names.
MEGA_CAP_UNIVERSE = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
    "TSM", "BRK-B", "WMT", "JPM", "ORCL", "V", "LLY",
]

# Broader opportunity book. These are not automatic buys; they are the
# daily discovery pool scored against price action, valuation/quality, and
# optional Massive/Benzinga analyst data.
DISCOVERY_UNIVERSE = [
    # Semiconductors / AI infrastructure
    "ARM", "ASML", "MU", "LRCX", "KLAC", "AMAT", "MRVL", "MPWR", "ON", "NXPI", "SNDK",
    # Software / cyber / data
    "PLTR", "CRM", "NOW", "SNOW", "DDOG", "NET", "CRWD", "PANW", "ZS", "MDB", "ADBE",
    # Internet / platforms / consumer tech
    "UBER", "ABNB", "SHOP", "MELI", "NFLX", "SPOT", "BKNG",
    # Fintech / exchanges
    "V", "MA", "AXP", "COIN", "HOOD", "CME", "ICE",
    # Industrials and energy tied to electrification / AI buildout
    "GE", "ETN", "VRT", "CEG", "TLN", "PWR", "EME",
    # Healthcare growth / quality
    "LLY", "NVO", "ISRG", "VRTX", "REGN", "TMO",
]

WATCHLIST = sorted(set(CORE_UNIVERSE + MEGA_CAP_UNIVERSE))
BENCHMARK = "SPY"

# --- Relative mandate (V2) ---------------------------------------------
@dataclass(frozen=True)
class Mandate:
    starting_capital: float = 5_000.0
    benchmark: str = "SPY"

    # Performance mandate
    target_alpha_pct: float = 0.10           # SPY + 10% over the test window
    max_relative_drawdown_pct: float = 0.08  # allow safety sleeves room during snapback rallies

    # Risk caps (now relative, with SPY as baseline)
    max_picks_open: int = 6                  # several small sleeves, not one big bet
    pick_weight_per_position: float = 0.10   # default pick is 10% of NAV
    min_pick_weight_per_position: float = 0.05
    spy_core_min_weight: float = 0.25        # leave room for tech/semis or safety sleeves

    # Pick selection
    pick_conviction_min: float = 1.0         # composite z >= 1.0 to be considered
    pick_max_hold_days: int = 30
    pick_signal_decay_z: float = 0.5         # exit pick if its z falls below this

    # Per-pick relative stop: each pick must beat SPY on its own.
    # If pick trails SPY by `pick_relative_stop_pct` after `pick_relative_stop_grace_days`,
    # force exit. Keeps individual picks from dragging the book.
    pick_relative_stop_pct: float = 0.08      # avoid shaking out long-horizon QQQ/SMH sleeves
    pick_relative_stop_grace_days: int = 10   # give thematic sleeves time to work

    # Portfolio-wide gate thresholds, as fractions of max_relative_drawdown_pct
    yellow_gate_fraction: float = 0.4   # yellow when relative DD ≥ 0.4 × 5% = 2.0%
    red_gate_fraction: float = 0.8      # red    when relative DD ≥ 0.8 × 5% = 4.0%

    # Misc
    min_dollar_position: float = 25.0

MANDATE = Mandate()

# Legacy alias — older modules still reference `RISK`. New code uses MANDATE.
RISK = MANDATE

# --- Active strategies -------------------------------------------------
# The two rule-based strategies (momentum_breakout_v1, mean_reversion_v1)
# and the first-gen pitcher are kept in-tree for audit, but disabled in V2.
# v3 makes allocation decisions directly: semis/tech when attractively
# priced, SHY when stress is high, SPY as the default ballast.
ACTIVE_IDS = [
    "adaptive_tech_semis_v1",
]

# --- Backtest defaults --------------------------------------------------
BACKTEST_DAYS = 504  # ~2 trading years

# --- Supabase / LLM env ------------------------------------------------
SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"
ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"
MASSIVE_KEY_ENV = "MASSIVE_API_KEY"
POLYGON_KEY_ENV = "POLYGON_API_KEY"
MASSIVE_BASE_URL_ENV = "MASSIVE_API_BASE_URL"

def risk_as_dict() -> dict:
    return asdict(MANDATE)
