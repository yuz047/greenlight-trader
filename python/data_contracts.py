"""Normalized data contracts for Greenlight Trader."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), indent=2, sort_keys=True) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


@dataclass
class PriceBar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    source: str = "massive"
    data_quality_flag: str = "ok"


@dataclass
class TickerProfile:
    symbol: str
    asset_type: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    exchange: str | None = None
    currency: str = "USD"
    source: str = "massive"
    data_quality_flag: str = "ok"


@dataclass
class NewsItem:
    symbol: str
    published_utc: str
    title: str
    source: str
    url: str | None = None
    sentiment: float | None = None
    data_quality_flag: str = "ok"


@dataclass
class AnalystSnapshot:
    symbol: str
    as_of: str
    rating_score: float | None = None
    upside_pct: float | None = None
    rating_distribution: dict[str, int] = field(default_factory=dict)
    point_in_time_available: bool = False
    data_quality_flag: str = "unavailable"


@dataclass
class FundamentalSnapshot:
    symbol: str
    as_of: str
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    roic: float | None = None
    free_cash_flow_signal: float | None = None
    valuation_reasonableness: float | None = None
    point_in_time_available: bool = False
    data_quality_flag: str = "unavailable"


@dataclass
class EarningsEvent:
    symbol: str
    report_date: str
    timing: str | None = None
    source: str = "massive"
    point_in_time_available: bool = False
    data_quality_flag: str = "unavailable"


@dataclass
class CandidateFeatureRow:
    symbol: str
    asset_type: str
    as_of: str
    sector: str | None = None
    industry: str | None = None
    theme: str | None = None
    category: str | None = None
    market_cap: float | None = None
    avg_dollar_volume: float | None = None
    price: float | None = None
    analyst_upside: float | None = None
    analyst_rating: float | None = None
    analyst_revision: float | None = None
    rating_distribution: dict[str, int] = field(default_factory=dict)
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    margins: float | None = None
    roe: float | None = None
    roa: float | None = None
    roic: float | None = None
    free_cash_flow_signal: float | None = None
    valuation_reasonableness: float | None = None
    news_sentiment: float | None = None
    news_volume: int = 0
    earnings_proximity_days: int | None = None
    relative_strength_spy: float | None = None
    relative_strength_qqq: float | None = None
    momentum_20d: float | None = None
    momentum_63d: float | None = None
    momentum_126d: float | None = None
    above_50dma: bool | None = None
    above_200dma: bool | None = None
    drawdown_from_high: float | None = None
    sector_theme_leadership: float | None = None
    volatility_adjusted_momentum: float | None = None
    rsi: float | None = None
    atr: float | None = None
    volume_zscore: float | None = None
    distance_from_50dma: float | None = None
    pullback_flag: bool = False
    breakout_flag: bool = False
    extension_flag: bool = False
    realized_volatility: float | None = None
    beta_spy: float | None = None
    beta_qqq: float | None = None
    correlation_spy: float | None = None
    correlation_qqq: float | None = None
    correlation_portfolio: float | None = None
    event_risk: float = 0.0
    liquidity_score: float = 0.0
    high_risk_symbol_flag: bool = False
    data_quality_flag: str = "ok"
    data_quality_multiplier: float = 1.0
    investable_flag: bool = True
    missing_data_count: int = 0


@dataclass
class CandidateScore:
    symbol: str
    asset_type: str
    as_of: str
    final_score: float
    information_score: float = 0.0
    leadership_score: float = 0.0
    timing_score: float = 0.0
    regime_fit_score: float = 0.0
    diversification_score: float = 0.0
    risk_penalty: float = 0.0
    investable_flag: bool = True
    timing_multiplier: float = 1.0
    data_quality_multiplier: float = 1.0
    wait_flag: bool = False
    explanations: list[str] = field(default_factory=list)


@dataclass
class TargetAllocation:
    symbol: str
    weight: float
    sleeve: str
    reason: str
    asset_type: str
    sector: str | None = None
    theme: str | None = None


@dataclass
class RiskStatus:
    as_of: str
    light: str
    reasons: list[str]
    data_health: dict[str, Any]
    absolute_drawdown_pct: float = 0.0
    relative_drawdown_pct: float = 0.0
    concentration: dict[str, float] = field(default_factory=dict)
    allow_new_alpha_entries: bool = True


@dataclass
class ExecutionDecision:
    as_of: str
    decision: str
    reason: str
    orders: list[dict[str, Any]] = field(default_factory=list)
    turnover: float = 0.0
    drift: float = 0.0


@dataclass
class DecisionLog:
    date: str
    market_regime: str
    risk_light: str
    data_health: dict[str, Any]
    universe_size: int
    selected_etfs: list[dict[str, Any]]
    rejected_etfs: list[dict[str, Any]]
    top_stock_candidates: list[dict[str, Any]]
    candidate_score_summary: dict[str, Any]
    current_allocation: dict[str, float]
    target_allocation: dict[str, float]
    systematic_decision: dict[str, Any]
    agent_led_decision: dict[str, Any]
    execution_decision: str
    execution_reason: str
    orders: list[dict[str, Any]]
    portfolio_snapshot: dict[str, Any]
    benchmark_snapshot: dict[str, Any]
    watermarks: list[str]


@dataclass
class EndpointAvailability:
    endpoint: str
    available: bool
    checked_at: str
    reason: str = ""
    plan_dependent: bool = False
    point_in_time_safe: bool = True
