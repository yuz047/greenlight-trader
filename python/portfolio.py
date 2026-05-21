"""Paper-trading book — V2: SPY-anchored with alpha sleeves.

The book is *always* invested. Default state is 100% SPY. When the
pitcher emits a high-conviction pick, ``pick_weight_per_position`` of
NAV is swapped out of SPY into the pick. When the pick exits (stop /
target / max hold / signal decay / relative-DD override), SPY is
bought back to restore the target SPY weight.

The point is to track SPY closely and only deviate when there's a
defensible reason — that's how the mandate of "SPY + 10% with max −5%
relative drawdown" is met.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import date, datetime
import json, math, uuid
from pathlib import Path

from config import DATA_DIR, MANDATE, BENCHMARK


def _today() -> str: return date.today().isoformat()
def _now() -> str:   return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class Position:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    entry_time: str
    stop_price: float
    target_price: float
    max_hold_days: int
    strategy_id: str
    thesis: str
    last_price: float = 0.0
    age_days: int = 0
    is_core: bool = False  # True for the SPY baseline; False for alpha picks
    target_weight: float = 0.0

    def notional(self) -> float: return self.quantity * self.last_price
    def unrealized_pnl(self) -> float: return (self.last_price - self.entry_price) * self.quantity
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
    quantity: float
    entry_time: str
    entry_price: float
    exit_time: Optional[str]
    exit_price: Optional[float]
    pnl: float
    strategy_id: str
    reasoning: str
    exit_reason: Optional[str]
    holding_days: int
    # Alpha attribution: SPY return over the same window. Lets us see whether
    # the pick actually beat the benchmark it was replacing.
    spy_return_over_hold: Optional[float] = None
    alpha_vs_spy: Optional[float] = None

    def to_dict(self) -> dict: return asdict(self)


@dataclass
class Portfolio:
    cash: float = MANDATE.starting_capital
    realized_pnl: float = 0.0
    peak_relative_outperformance: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)
    inception: str = field(default_factory=_today)

    # ---- persistence ---------------------------------------------------
    @classmethod
    def path(cls) -> Path: return DATA_DIR / "portfolio_state.json"

    @classmethod
    def load(cls) -> "Portfolio":
        p = cls.path()
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        port = cls(
            cash=raw["cash"],
            realized_pnl=raw.get("realized_pnl", 0.0),
            peak_relative_outperformance=raw.get("peak_relative_outperformance", 0.0),
            inception=raw.get("inception", _today()),
        )
        port.positions = {
            sym: Position(**{k: v for k, v in p.items() if k in Position.__dataclass_fields__})
            for sym, p in raw.get("positions", {}).items()
        }
        port.trades = [
            Trade(**{k: v for k, v in t.items() if k in Trade.__dataclass_fields__})
            for t in raw.get("trades", [])
        ]
        return port

    def save(self) -> None:
        out = {
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "peak_relative_outperformance": self.peak_relative_outperformance,
            "inception": self.inception,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "trades": [t.to_dict() for t in self.trades],
        }
        for s, p in out["positions"].items():
            p.pop("unrealized_pnl", None); p.pop("notional", None)
        self.path().write_text(json.dumps(out, indent=2, default=str))

    # ---- valuation -----------------------------------------------------
    def mark_to_market(self, prices: Dict[str, float]) -> None:
        for sym, pos in self.positions.items():
            if sym in prices and not math.isnan(prices[sym]):
                pos.last_price = float(prices[sym])

    def nav(self) -> float:
        return self.cash + sum(p.notional() for p in self.positions.values())

    def core_notional(self) -> float:
        core = self.positions.get(BENCHMARK)
        return core.notional() if core else 0.0

    def picks(self) -> List[Position]:
        return [p for s, p in self.positions.items() if s != BENCHMARK]

    def rebalance_to_targets(
        self,
        targets: Dict[str, float],
        prices: Dict[str, float],
        *,
        strategy_id: str,
        thesis: str,
    ) -> None:
        """Rebalance the book to explicit target weights.

        ``CASH`` is allowed as a pseudo-symbol. All other targets need a
        current price. This path is used by allocation strategies that should
        hold sleeves persistently instead of opening short-lived picks.
        """
        clean = {
            sym: max(0.0, float(weight))
            for sym, weight in targets.items()
            if sym != "CASH" and weight > 0 and prices.get(sym, 0.0) > 0
        }
        cash_weight = max(0.0, float(targets.get("CASH", 0.0)))
        total_weight = sum(clean.values()) + cash_weight
        if total_weight > 1.0:
            scale = 1.0 / total_weight
            clean = {sym: weight * scale for sym, weight in clean.items()}
            cash_weight *= scale

        nav = self.nav()
        target_notional = {sym: weight * nav for sym, weight in clean.items()}

        # Sell removed or overweight positions first.
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = prices.get(sym, pos.last_price)
            if price <= 0:
                continue
            pos.last_price = price
            desired = target_notional.get(sym, 0.0)
            current = pos.notional()
            if current <= desired + MANDATE.min_dollar_position:
                continue
            sell_notional = current - desired
            shares_to_sell = min(pos.quantity, sell_notional / price)
            pos.quantity -= shares_to_sell
            self.cash += shares_to_sell * price
            if pos.quantity * price < MANDATE.min_dollar_position:
                self.cash += pos.quantity * price
                self.positions.pop(sym, None)

        # Buy underweight targets with available cash.
        for sym, desired in target_notional.items():
            price = prices.get(sym, 0.0)
            if price <= 0:
                continue
            current = self.positions[sym].notional() if sym in self.positions else 0.0
            buy_notional = desired - current
            if buy_notional < MANDATE.min_dollar_position:
                continue
            buy_notional = min(buy_notional, self.cash)
            if buy_notional < MANDATE.min_dollar_position:
                continue
            shares_to_buy = buy_notional / price
            if sym in self.positions:
                pos = self.positions[sym]
                new_qty = pos.quantity + shares_to_buy
                pos.entry_price = (
                    (pos.entry_price * pos.quantity + price * shares_to_buy) / new_qty
                )
                pos.quantity = new_qty
                pos.last_price = price
                pos.target_weight = clean[sym]
                pos.is_core = True
            else:
                self.positions[sym] = Position(
                    symbol=sym, side="long", quantity=shares_to_buy,
                    entry_price=price, entry_time=_now(),
                    stop_price=0.0, target_price=0.0, max_hold_days=10_000,
                    strategy_id=strategy_id, thesis=thesis,
                    last_price=price, age_days=0, is_core=True,
                    target_weight=clean[sym],
                )
            self.cash -= buy_notional

        for sym, weight in clean.items():
            if sym in self.positions:
                self.positions[sym].target_weight = weight
                self.positions[sym].is_core = True

    # ---- SPY core --------------------------------------------------
    def rebalance_to_core(self, spy_price: float) -> None:
        """Make sure 100% of available NAV is in SPY when no picks active.

        Called at portfolio inception and whenever a pick exits.
        """
        if spy_price <= 0: return
        # If we're already long SPY, top up; otherwise create the core.
        nav = self.nav()
        target_spy_weight = self._target_spy_weight()
        target_spy_notional = target_spy_weight * nav
        existing_notional = self.core_notional()
        diff = target_spy_notional - existing_notional
        if abs(diff) < MANDATE.min_dollar_position:
            return
        if diff > 0:
            # Buy more SPY
            shares_to_buy = diff / spy_price
            if shares_to_buy * spy_price <= self.cash + 1e-6:
                if BENCHMARK in self.positions:
                    pos = self.positions[BENCHMARK]
                    new_qty = pos.quantity + shares_to_buy
                    # Weight-average the entry price
                    pos.entry_price = (
                        (pos.entry_price * pos.quantity + spy_price * shares_to_buy) / new_qty
                    )
                    pos.quantity = new_qty
                    pos.last_price = spy_price
                else:
                    self.positions[BENCHMARK] = Position(
                        symbol=BENCHMARK, side="long",
                        quantity=shares_to_buy, entry_price=spy_price,
                        entry_time=_now(),
                        stop_price=0.0, target_price=0.0, max_hold_days=10_000,
                        strategy_id="spy_core_baseline",
                        thesis="SPY baseline — always held except when relative DD forces exit.",
                        last_price=spy_price, age_days=0, is_core=True,
                    )
                self.cash -= shares_to_buy * spy_price
        else:
            # Sell some SPY back to free cash for picks
            shares_to_sell = -diff / spy_price
            pos = self.positions.get(BENCHMARK)
            if pos is not None:
                shares_to_sell = min(shares_to_sell, pos.quantity)
                pos.quantity -= shares_to_sell
                self.cash += shares_to_sell * spy_price

    def _target_spy_weight(self) -> float:
        active_pick_weight = sum(
            p.target_weight if p.target_weight > 0 else MANDATE.pick_weight_per_position
            for p in self.positions.values()
            if not p.is_core
        )
        return max(MANDATE.spy_core_min_weight, 1.0 - active_pick_weight)

    # ---- pick lifecycle ------------------------------------------------
    def open_pick(
        self, *, symbol: str, entry_price: float, stop_distance: float,
        target_distance: float, max_hold_days: int, strategy_id: str,
        thesis: str, spy_price_at_entry: float, target_weight: Optional[float] = None,
    ) -> Optional[Position]:
        if symbol in self.positions or symbol == BENCHMARK:
            return None
        if entry_price <= 0:
            return None
        nav = self.nav()
        weight = target_weight if target_weight is not None else MANDATE.pick_weight_per_position
        weight = max(MANDATE.min_pick_weight_per_position, float(weight))
        pick_notional = weight * nav
        if pick_notional < MANDATE.min_dollar_position:
            return None
        # Free up cash by selling SPY shares equal to pick notional
        spy_pos = self.positions.get(BENCHMARK)
        if spy_pos is None or spy_pos.notional() < pick_notional:
            return None
        spy_shares_to_sell = pick_notional / spy_price_at_entry
        if spy_shares_to_sell > spy_pos.quantity:
            return None
        spy_pos.quantity -= spy_shares_to_sell
        self.cash += spy_shares_to_sell * spy_price_at_entry
        # Buy the pick
        quantity = pick_notional / entry_price
        if quantity * entry_price > self.cash + 1e-6:
            # roll back the SPY sale and bail
            spy_pos.quantity += spy_shares_to_sell
            self.cash -= spy_shares_to_sell * spy_price_at_entry
            return None
        self.cash -= quantity * entry_price
        pos = Position(
            symbol=symbol, side="long", quantity=quantity,
            entry_price=entry_price, entry_time=_now(),
            stop_price=entry_price - stop_distance,
            target_price=entry_price + target_distance,
            max_hold_days=max_hold_days,
            strategy_id=strategy_id, thesis=thesis,
            last_price=entry_price, age_days=0, is_core=False,
            target_weight=weight,
        )
        # Stash SPY entry price for alpha attribution
        pos.thesis = pos.thesis + f" (SPY@entry=${spy_price_at_entry:.2f})"
        self.positions[symbol] = pos
        return pos

    def close_pick(
        self, symbol: str, exit_price: float, reason: str,
        spy_price_at_exit: float,
    ) -> Optional[Trade]:
        pos = self.positions.pop(symbol, None)
        if pos is None or pos.is_core:
            return None
        proceeds = pos.quantity * exit_price
        self.cash += proceeds
        pnl = (exit_price - pos.entry_price) * pos.quantity

        # Alpha attribution
        # Parse SPY@entry from the thesis (set in open_pick)
        spy_entry = None
        try:
            import re
            m = re.search(r"SPY@entry=\$([\d\.]+)", pos.thesis)
            if m: spy_entry = float(m.group(1))
        except Exception: pass
        spy_ret = None; alpha = None
        if spy_entry and spy_price_at_exit > 0:
            pick_ret = exit_price / pos.entry_price - 1.0
            spy_ret = spy_price_at_exit / spy_entry - 1.0
            alpha = pick_ret - spy_ret
        self.realized_pnl += pnl

        trade = Trade(
            trade_id=str(uuid.uuid4())[:8],
            symbol=symbol, side=pos.side, quantity=pos.quantity,
            entry_time=pos.entry_time, entry_price=pos.entry_price,
            exit_time=_now(), exit_price=exit_price, pnl=pnl,
            strategy_id=pos.strategy_id, reasoning=pos.thesis,
            exit_reason=reason, holding_days=pos.age_days,
            spy_return_over_hold=spy_ret, alpha_vs_spy=alpha,
        )
        self.trades.append(trade)
        return trade

    # ---- daily housekeeping --------------------------------------------
    def age_positions(self) -> None:
        for pos in self.positions.values():
            if not pos.is_core:
                pos.age_days += 1

    def _pick_spy_entry(self, pos: Position) -> Optional[float]:
        """Extract the SPY price at the time this pick was opened.

        It's stashed at the tail of the thesis string by open_pick().
        Returns None if we can't recover it.
        """
        import re
        m = re.search(r"SPY@entry=\$([\d\.]+)", pos.thesis)
        return float(m.group(1)) if m else None

    def apply_exits(
        self, ohlc: Dict[str, dict],
        *, rank_lookup: Dict[str, dict],
        decay_z: float,
        spy_price: float,
    ) -> List[Trade]:
        """Close picks via stop / target / max-hold / signal-decay / per-pick rel stop.

        Stops fill at stop_price (conservative). Targets at target_price.
        Max-hold and signal-decay exits fill at today's close. The per-pick
        relative stop fires when a pick has been alive at least
        ``pick_relative_stop_grace_days`` and is trailing SPY by more than
        ``pick_relative_stop_pct`` since entry — keeps any single pick
        from dragging the book past the portfolio-wide cap.
        """
        closed: List[Trade] = []
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            if pos.is_core or symbol == BENCHMARK:
                continue
            bar = ohlc.get(symbol)
            if not bar:
                continue
            low, high, close = bar["low"], bar["high"], bar["close"]
            if low <= pos.stop_price:
                t = self.close_pick(symbol, pos.stop_price, "stop", spy_price)
                if t: closed.append(t); continue
            if high >= pos.target_price:
                t = self.close_pick(symbol, pos.target_price, "target", spy_price)
                if t: closed.append(t); continue
            if pos.age_days >= pos.max_hold_days:
                t = self.close_pick(symbol, close, "max_hold", spy_price)
                if t: closed.append(t); continue
            # Signal-decay exit
            r = rank_lookup.get(symbol)
            if r is not None and r.get("composite", 0.0) < decay_z:
                t = self.close_pick(symbol, close, "signal_decay", spy_price)
                if t: closed.append(t); continue
            # Per-pick relative stop — only after the grace period
            if pos.age_days >= MANDATE.pick_relative_stop_grace_days and spy_price > 0:
                spy_entry = self._pick_spy_entry(pos)
                if spy_entry and spy_entry > 0:
                    pick_ret = close / pos.entry_price - 1.0
                    spy_ret = spy_price / spy_entry - 1.0
                    rel_pick = pick_ret - spy_ret
                    if rel_pick <= -MANDATE.pick_relative_stop_pct:
                        t = self.close_pick(symbol, close, "rel_stop", spy_price)
                        if t: closed.append(t); continue
        return closed
