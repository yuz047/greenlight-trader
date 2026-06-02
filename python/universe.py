"""Daily universe construction."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from config import CORE_ANCHORS, DATA_DIR, ETF_POOL, HIGH_RISK_SYMBOLS_PATH, MANDATE, STOCK_SEED_POOL
from data_contracts import read_json, write_json
from massive_client import MassiveClient
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def load_high_risk_symbol_set() -> set[str]:
    payload = read_json(HIGH_RISK_SYMBOLS_PATH, default=[])
    rows: list[dict[str, Any]]
    if isinstance(payload, dict):
        rows = payload.get("symbols") or payload.get("rows") or payload.get("data") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    flagged: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        verdict = str(row.get("verdict") or row.get("combined_verdict") or row.get("risk_label") or "").lower()
        is_flagged = bool(row.get("high_risk") or row.get("flagged") or row.get("is_high_risk"))
        if symbol and (is_flagged or "risk" in verdict or "pca" in verdict or "rule" in verdict):
            flagged.add(symbol)
    return flagged


def build_universe(
    as_of: str | None = None,
    client: MassiveClient | None = None,
    current_holdings: list[str] | None = None,
    hydrate_profiles: bool = False,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    client = client or MassiveClient()
    current_holdings = [s.upper() for s in (current_holdings or [])]
    high_risk = load_high_risk_symbol_set()

    rows: dict[str, dict[str, Any]] = {}

    for symbol, meta in CORE_ANCHORS.items():
        rows[symbol] = {
            "symbol": symbol,
            "asset_type": meta["asset_type"],
            "reason_included": meta["reason"],
            "source": "config.core_anchor",
            "sector": meta["sector"],
            "industry": None,
            "theme": meta["theme"],
            "category": meta["category"],
            "market_cap": None,
            "avg_dollar_volume": None,
            "data_quality_flag": "pending_price_validation",
            "high_risk_symbol_flag": False,
        }

    for symbol, (category, sector, theme) in ETF_POOL.items():
        rows.setdefault(
            symbol,
            {
                "symbol": symbol,
                "asset_type": "etf",
                "reason_included": "dynamic_etf_pool_candidate",
                "source": "config.dynamic_etf_pool",
                "sector": sector,
                "industry": None,
                "theme": theme,
                "category": category,
                "market_cap": None,
                "avg_dollar_volume": None,
                "data_quality_flag": "pending_price_validation",
                "high_risk_symbol_flag": False,
            },
        )

    for symbol in sorted(set(STOCK_SEED_POOL + current_holdings)):
        rows.setdefault(
            symbol,
            {
                "symbol": symbol,
                "asset_type": "stock",
                "reason_included": "seed_quality_or_current_holding",
                "source": "config.stock_seed_pool",
                "sector": None,
                "industry": None,
                "theme": None,
                "category": None,
                "market_cap": None,
                "avg_dollar_volume": None,
                "data_quality_flag": "pending_profile_and_price_validation",
                "high_risk_symbol_flag": symbol in high_risk,
            },
        )

    for symbol in current_holdings:
        if symbol not in rows:
            rows[symbol] = {
                "symbol": symbol,
                "asset_type": "stock",
                "reason_included": "current_holding",
                "source": "portfolio.current_holdings",
                "sector": None,
                "industry": None,
                "theme": None,
                "category": None,
                "market_cap": None,
                "avg_dollar_volume": None,
                "data_quality_flag": "pending_profile_and_price_validation",
                "high_risk_symbol_flag": symbol in high_risk,
            }

    for direction in ("gainers", "losers"):
        for mover in client.get_market_movers(direction)[:25]:
            symbol = str(mover.get("ticker") or mover.get("symbol") or "").upper()
            if not symbol or "." in symbol:
                continue
            rows.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "asset_type": "stock",
                    "reason_included": f"massive_market_mover_{direction}",
                    "source": "massive.market_movers",
                    "sector": None,
                    "industry": None,
                    "theme": None,
                    "category": None,
                    "market_cap": None,
                    "avg_dollar_volume": None,
                    "data_quality_flag": "pending_profile_and_price_validation",
                    "high_risk_symbol_flag": symbol in high_risk,
                },
            )

    if hydrate_profiles and client.has_key:
        for row in rows.values():
            profile = client.get_ticker_profile(row["symbol"])
            if profile:
                profile_dict = asdict(profile)
                row["asset_type"] = "etf" if profile_dict["asset_type"] == "etf" and row["asset_type"] != "benchmark" else row["asset_type"]
                row["sector"] = row["sector"] or profile_dict.get("sector")
                row["industry"] = row["industry"] or profile_dict.get("industry")
                row["market_cap"] = profile_dict.get("market_cap")
                row["source"] += "+massive.profile"
                row["data_quality_flag"] = profile_dict.get("data_quality_flag", "ok")

    candidates = sorted(rows.values(), key=lambda r: (r["asset_type"], r["symbol"]))
    return add_watermark(
        {
            "as_of": as_of,
            "mandate": {
                "benchmark": MANDATE.benchmark,
                "secondary_growth_anchor": MANDATE.secondary_growth_anchor,
                "defensive_anchor": MANDATE.defensive_anchor,
            },
            "candidates": candidates,
            "high_risk_symbol_count": len(high_risk),
            "endpoint_availability": client.availability_report(),
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def write_candidate_universe(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "candidate_universe.json", payload)


def candidate_symbols(universe_payload: dict[str, Any], include_vix: bool = True) -> list[str]:
    symbols = [row["symbol"] for row in universe_payload.get("candidates", [])]
    if include_vix and "^VIX" not in symbols:
        symbols.append("^VIX")
    return sorted(set(symbols))
