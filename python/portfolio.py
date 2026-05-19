"""Paper-trading book.

The portfolio is the source of truth for cash, open positions, and the
trade log. It is intentionally side-effect-light: ``open_trade`` and
``close_trade`` mutate state, ``mark_to_market`` is a pure read.

State is serialized to JSON in ``data/portfolio_state.json`` between
runs so the engine has memory of its open positions, peak NAV, and
the day's realized PnL.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import date, datetime
import json
import math
import uuid
from pathlib import Path

from config import DATA_DIR, RISK


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class Position:
    symbol: str
    side: str                  # "long"
    quantity: int
    entry_price: float
    entry_time: str
    stop_price: float
    target_price: float
    max_hold_days: int
    strategy_id: str
    thesis: str
    # mutable
    last_price: float = 0.0
    age_days: int = 0

    def notional(self) -> float:
        return self.quantity * self.last_price

    def unrealized_pnl(self) -> float:
        return (self.last_price - self.entry_price) * self.quantity

    def to_dict(self) -> dict:
        d = asdict(self)
        d["unrealized_pnl"] = self.unrealized_pnl()
        d["notional"] = self.notional()
        return d


@dataclass
class Trade:
    trade_id: str
    symbol: str
    side: str
    quantity: int
    entry_time: str
    entry_price: float
    exit_time: Optional[str]
    exit_price: Optional[float]
    pnl: float
    strategy_id: str
    reasoning: str
    exit_reason: Optional[str]
    holding_days: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Portfolio:
    cash: float = RISK.starting_capital
    realized_pnl: float = 0.0
    peak_nav: float = RISK.starting_capital
    positions: Dict[str, Position] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)
    inception: str = field(default_factory=_today)

    # ---- persistence ----------------------------------------------------
    @classmethod
    def path(cls) -> Path:
        return DATA_DIR / "portfolio_state.json"

    @classmethod
    def load(cls) -> "Portfolio":
        p = cls.path()
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        port = cls(
            cash=raw["cash"],
            realized_pnl=raw["realized_pnl"],
            peak_nav=raw["peak_nav"],
            inception=raw.get("inception", _today()),
        )
        port.positions = {
            sym: Position(**p) for sym, p in raw.get("positions", {}).items()
        }
        port.trades = [Trade(**t) for t in raw.get("trades", [])]
        return port

    def save(self) -> None:
        out = {
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "peak_nav": self.peak_nav,
            "inception": self.inception,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "trades": [t.to_dict() for t in self.trades],
        }
        # strip computed fields from positions for round-tripping
        for s, p in out["positions"].items():
            p.pop("unrealized_pnl", None)
            p.pop("notional", None)
        self.path().write_text(json.dumps(out, indent=2, default=str))

    # ---- valuation ------------------------------------------------------
    def mark_to_market(self, prices: Dict[str, float]) -> None:
        for sym, pos in self.positions.items():
            if sym in prices and not math.isnan(prices[sym]):
                pos.last_price = float(prices[sym])

    def nav(self) -> float:
        return self.cash + sum(p.notional() for p in self.positions.values())

    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl() for p in self.positions.values())

    # ---- trade lifecycle ------------------------------------------------
    def open_trade(
        self, *, symbol: str, quantity: int, entry_price: float,
        stop_distance: float, target_distance: float,
        max_hold_days: int, strategy_id: str, thesis: str,
    ) -> Optional[Position]:
        if symbol in self.positions:
            return None
        notional = quantity * entry_price
        if notional > self.cash + 1e-6:
            return None
        self.cash -= notional
        pos = Position(
            symbol=symbol, side="long", quantity=quantity,
            entry_price=entry_price, entry_time=_now(),
            stop_price=entry_price - stop_distance,
            target_price=entry_price + target_distance,
            max_hold_days=max_hold_days,
            strategy_id=strategy_id, thesis=thesis,
            last_price=entry_price, age_days=0,
        )
        self.positions[symbol] = pos
        return pos

    def close_trade(self, symbol: str, exit_price: float, reason: str) -> Optional[Trade]:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None
        self.cash += pos.quantity * exit_price
        pnl = (exit_price - pos.entry_price) * pos.quantity
        self.realized_pnl += pnl
        trade = Trade(
            trade_id=str(uuid.uuid4())[:8],
            symbol=symbol, side=pos.side, quantity=pos.quantity,
            entry_time=pos.entry_time, entry_price=pos.entry_price,
            exit_time=_now(), exit_price=exit_price, pnl=pnl,
            strategy_id=pos.strategy_id, reasoning=pos.thesis,
            exit_reason=reason, holding_days=pos.age_days,
        )
        self.trades.append(trade)
        return trade

    # ---- daily housekeeping --------------------------------------------
    def age_positions(self) -> None:
        for pos in self.positions.values():
            pos.age_days += 1

    def apply_stops_and_targets(self, ohlc: Dict[str, dict]) -> List[Trade]:
        """Close positions whose intraday range hit stop / target / max hold.

        ``ohlc`` maps symbol -> {high, low, close}. We assume worst-case
        stop fill at the stop price (no slippage modeling in V1).
        """
        closed: List[Trade] = []
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            bar = ohlc.get(symbol)
            if not bar:
                continue
            low, high, close = bar["low"], bar["high"], bar["close"]
            # Stop first (conservative)
            if low <= pos.stop_price:
                t = self.close_trade(symbol, pos.stop_price, "stop")
                if t: closed.append(t); continue
            if high >= pos.target_price:
                t = self.close_trade(symbol, pos.target_price, "target")
                if t: closed.append(t); continue
            if pos.age_days >= pos.max_hold_days:
                t = self.close_trade(symbol, close, "max_hold")
                if t: closed.append(t); continue
        return closed

    def update_peak(self) -> None:
        nav = self.nav()
        if nav > self.peak_nav:
            self.peak_nav = nav

    # ---- views ---------------------------------------------------------
    def open_position_exposure(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        return pos.notional() if pos else 0.0
