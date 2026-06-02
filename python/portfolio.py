"""Paper portfolio accounting."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from config import DATA_DIR, MANDATE
from data_contracts import read_json, write_json


@dataclass
class Position:
    symbol: str
    shares: float
    avg_price: float
    market_price: float
    asset_type: str = "stock"
    sector: str | None = None
    theme: str | None = None

    @property
    def market_value(self) -> float:
        return self.shares * self.market_price


@dataclass
class PaperPortfolio:
    cash: float = MANDATE.starting_capital
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    peak_nav: float = MANDATE.starting_capital
    last_rebalance_date: str | None = None
    benchmark_equity: float = MANDATE.starting_capital
    peak_relative_outperformance: float = 0.0
    relative_drawdown_pct: float = 0.0

    @classmethod
    def path(cls) -> Path:
        return DATA_DIR / "portfolio_state.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "PaperPortfolio":
        path = path or cls.path()
        payload = read_json(path, default=None)
        if not payload:
            return cls()
        positions = {
            symbol: Position(
                symbol=symbol,
                shares=float(row.get("shares", 0.0)),
                avg_price=float(row.get("avg_price", row.get("market_price", 0.0))),
                market_price=float(row.get("market_price", row.get("avg_price", 0.0))),
                asset_type=row.get("asset_type", "stock"),
                sector=row.get("sector"),
                theme=row.get("theme"),
            )
            for symbol, row in payload.get("positions", {}).items()
        }
        return cls(
            cash=float(payload.get("cash", MANDATE.starting_capital)),
            positions=positions,
            realized_pnl=float(payload.get("realized_pnl", 0.0)),
            peak_nav=float(payload.get("peak_nav", MANDATE.starting_capital)),
            last_rebalance_date=payload.get("last_rebalance_date"),
            benchmark_equity=float(payload.get("benchmark_equity", MANDATE.starting_capital)),
            peak_relative_outperformance=float(payload.get("peak_relative_outperformance", 0.0)),
            relative_drawdown_pct=float(payload.get("relative_drawdown_pct", 0.0)),
        )

    def save(self, path: Path | None = None) -> None:
        write_json(path or self.path(), self.snapshot())

    def nav(self) -> float:
        return self.cash + sum(position.market_value for position in self.positions.values())

    def weights(self) -> dict[str, float]:
        nav = self.nav()
        if nav <= 0:
            return {}
        out = {symbol: position.market_value / nav for symbol, position in self.positions.items()}
        if self.cash > 0:
            out["CASH"] = self.cash / nav
        return {symbol: round(weight, 8) for symbol, weight in out.items() if weight > 0.000001}

    def mark_to_market(self, prices: dict[str, float]) -> None:
        for symbol, price in prices.items():
            if symbol in self.positions and price and price > 0:
                self.positions[symbol].market_price = float(price)
        self.peak_nav = max(self.peak_nav, self.nav())

    def snapshot(self) -> dict[str, Any]:
        nav = self.nav()
        return {
            "watermark": "SYSTEMATIC_TEMPLATE_OUTPUT",
            "date": date.today().isoformat(),
            "cash": round(self.cash, 6),
            "nav": round(nav, 6),
            "peak_nav": round(max(self.peak_nav, nav), 6),
            "realized_pnl": round(self.realized_pnl, 6),
            "last_rebalance_date": self.last_rebalance_date,
            "benchmark_equity": round(self.benchmark_equity, 6),
            "peak_relative_outperformance": round(self.peak_relative_outperformance, 6),
            "relative_drawdown_pct": round(self.relative_drawdown_pct, 6),
            "weights": self.weights(),
            "positions": {
                symbol: {
                    "shares": round(position.shares, 8),
                    "avg_price": round(position.avg_price, 6),
                    "market_price": round(position.market_price, 6),
                    "market_value": round(position.market_value, 6),
                    "asset_type": position.asset_type,
                    "sector": position.sector,
                    "theme": position.theme,
                }
                for symbol, position in sorted(self.positions.items())
            },
        }

    def rebalance_to_targets(
        self,
        target_allocations: list[dict[str, Any]],
        prices: dict[str, float],
        execution_decision: dict[str, Any],
        as_of: str,
    ) -> list[dict[str, Any]]:
        decision = execution_decision.get("execution_decision", {}).get("decision")
        if decision not in ("EXECUTE", "RISK_REDUCE"):
            return []

        nav = self.nav()
        targets = {row["symbol"]: float(row["weight"]) for row in target_allocations}
        meta = {row["symbol"]: row for row in target_allocations}
        orders: list[dict[str, Any]] = []
        all_symbols = set(self.positions) | set(targets)

        sells = []
        buys = []
        for symbol in sorted(all_symbols):
            price = float(prices.get(symbol) or 0.0)
            if price <= 0:
                continue
            current_value = self.positions.get(symbol).market_value if symbol in self.positions else 0.0
            target_value = nav * targets.get(symbol, 0.0)
            delta = target_value - current_value
            if abs(delta) < MANDATE.min_trade_dollars:
                continue
            if delta < 0:
                sells.append((symbol, price, delta))
            else:
                buys.append((symbol, price, delta))

        for symbol, price, delta in sells:
            orders.append(self._apply_trade(symbol, price, delta, meta.get(symbol, {})))
        for symbol, price, delta in buys:
            if self.cash <= MANDATE.min_trade_dollars:
                break
            delta = min(delta, self.cash)
            if delta >= MANDATE.min_trade_dollars:
                orders.append(self._apply_trade(symbol, price, delta, meta.get(symbol, {})))

        if orders:
            self.last_rebalance_date = as_of
            self.peak_nav = max(self.peak_nav, self.nav())
        return orders

    def _apply_trade(self, symbol: str, price: float, dollar_delta: float, meta: dict[str, Any]) -> dict[str, Any]:
        slippage_bps = 2.0
        side = "BUY" if dollar_delta > 0 else "SELL"
        effective_price = price * (1 + slippage_bps / 10_000) if side == "BUY" else price * (1 - slippage_bps / 10_000)
        shares_delta = dollar_delta / effective_price

        if side == "SELL":
            existing = self.positions.get(symbol)
            if not existing:
                return {"symbol": symbol, "side": side, "shares": 0.0, "price": price, "notional": 0.0, "reason": "no_position"}
            shares_to_sell = min(abs(shares_delta), existing.shares)
            proceeds = shares_to_sell * effective_price
            self.cash += proceeds
            self.realized_pnl += shares_to_sell * (effective_price - existing.avg_price)
            existing.shares -= shares_to_sell
            existing.market_price = price
            if existing.shares <= 1e-8:
                self.positions.pop(symbol, None)
            notional = proceeds
            shares = shares_to_sell
        else:
            cost = min(abs(dollar_delta), self.cash)
            shares = cost / effective_price
            existing = self.positions.get(symbol)
            if existing:
                old_cost = existing.shares * existing.avg_price
                new_cost = shares * effective_price
                existing.shares += shares
                existing.avg_price = (old_cost + new_cost) / existing.shares
                existing.market_price = price
            else:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    shares=shares,
                    avg_price=effective_price,
                    market_price=price,
                    asset_type=meta.get("asset_type", "stock"),
                    sector=meta.get("sector"),
                    theme=meta.get("theme"),
                )
            self.cash -= cost
            notional = cost

        return {
            "symbol": symbol,
            "side": side,
            "shares": round(shares, 8),
            "price": round(effective_price, 6),
            "notional": round(notional, 6),
            "slippage_bps": slippage_bps,
            "watermark": "SYSTEMATIC_TEMPLATE_OUTPUT",
        }
