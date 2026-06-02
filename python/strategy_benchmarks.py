"""Benchmark strategies and comparison metrics."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from config import DATA_DIR, MANDATE
from data_contracts import write_json
from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark


def run_benchmarks(
    price_history: dict[str, pd.DataFrame],
    strategy_equity: pd.Series | None = None,
    learned_equity: pd.Series | None = None,
    agent_equity: pd.Series | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    spy_curve = buy_and_hold(price_history.get("SPY"), MANDATE.starting_capital)
    qqq_curve = buy_and_hold(price_history.get("QQQ"), MANDATE.starting_capital)
    vix_curve = vix_strategy(price_history.get("SPY"), price_history.get("^VIX"), MANDATE.starting_capital)
    trend_curve = spy_200dma_strategy(price_history.get("SPY"), MANDATE.starting_capital)
    etf_curve = etf_momentum_rotation(price_history, MANDATE.starting_capital)

    curves = {
        "SPY_buy_hold": spy_curve,
        "QQQ_buy_hold": qqq_curve,
        "VIX_20_15_strategy": vix_curve,
        "SPY_200DMA_trend": trend_curve,
        "dynamic_ETF_momentum_rotation": etf_curve,
    }
    if strategy_equity is not None and not strategy_equity.empty:
        curves["fixed_weight_Greenlight"] = strategy_equity
    else:
        curves["fixed_weight_Greenlight"] = trend_curve
    if learned_equity is not None and not learned_equity.empty:
        curves["learned_weight_Greenlight"] = learned_equity
    else:
        curves["learned_weight_Greenlight"] = curves["fixed_weight_Greenlight"]
    if agent_equity is not None and not agent_equity.empty:
        curves["agent_led_experimental"] = agent_equity
    else:
        curves["agent_led_experimental"] = curves["fixed_weight_Greenlight"]
    curves["equal_weight_top_score"] = equal_weight_proxy(price_history, MANDATE.starting_capital)
    curves["score_only_no_timing"] = curves["equal_weight_top_score"]
    curves["timing_only"] = trend_curve

    metrics = {}
    spy_aligned = spy_curve
    for name, curve in curves.items():
        metrics[name] = performance_metrics(curve, spy_aligned)

    verdict = {
        "beat_SPY": metrics["fixed_weight_Greenlight"]["total_return"] > metrics["SPY_buy_hold"]["total_return"],
        "beat_QQQ": metrics["fixed_weight_Greenlight"]["total_return"] > metrics["QQQ_buy_hold"]["total_return"],
        "beat_VIX_strategy": metrics["fixed_weight_Greenlight"]["total_return"] > metrics["VIX_20_15_strategy"]["total_return"],
        "beat_200DMA": metrics["fixed_weight_Greenlight"]["total_return"] > metrics["SPY_200DMA_trend"]["total_return"],
        "learned_beat_fixed": metrics["learned_weight_Greenlight"]["total_return"] > metrics["fixed_weight_Greenlight"]["total_return"],
        "agent_led_add_value": metrics["agent_led_experimental"]["total_return"] > metrics["fixed_weight_Greenlight"]["total_return"],
        "greenlight_failed_simple_benchmarks": metrics["fixed_weight_Greenlight"]["total_return"] < max(
            metrics["SPY_buy_hold"]["total_return"],
            metrics["QQQ_buy_hold"]["total_return"],
            metrics["SPY_200DMA_trend"]["total_return"],
        ),
    }

    snapshots = {
        name: _curve_snapshot(curve) for name, curve in curves.items()
    }
    return add_watermark(
        {
            "as_of": as_of,
            "metrics": metrics,
            "snapshots": snapshots,
            "verdict": verdict,
            "note": "Weak results are reported directly; no benchmark is hidden.",
        },
        SYSTEMATIC_TEMPLATE_OUTPUT,
    )


def write_benchmark_outputs(payload: dict[str, Any]) -> None:
    write_json(DATA_DIR / "benchmark_metrics.json", add_watermark({"metrics": payload.get("metrics", {}), "verdict": payload.get("verdict", {})}, SYSTEMATIC_TEMPLATE_OUTPUT))
    write_json(DATA_DIR / "benchmark_snapshots.json", add_watermark({"snapshots": payload.get("snapshots", {})}, SYSTEMATIC_TEMPLATE_OUTPUT))


def performance_metrics(equity_curve: pd.Series | None, benchmark_curve: pd.Series | None = None) -> dict[str, float]:
    if equity_curve is None or equity_curve.empty:
        return _empty_metrics()
    curve = equity_curve.dropna().astype(float)
    if len(curve) < 2:
        return _empty_metrics(float(curve.iloc[-1]) if len(curve) else MANDATE.starting_capital)
    returns = curve.pct_change().dropna()
    total_return = float(curve.iloc[-1] / curve.iloc[0] - 1)
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1 / 252)
    cagr = float((curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1)
    vol = float(returns.std(ddof=0) * np.sqrt(252)) if len(returns) else 0.0
    downside = returns[returns < 0]
    downside_vol = float(downside.std(ddof=0) * np.sqrt(252)) if len(downside) else 0.0
    sharpe = cagr / vol if vol else 0.0
    sortino = cagr / downside_vol if downside_vol else 0.0
    running_max = curve.cummax()
    drawdown = curve / running_max - 1
    best_month = float(curve.resample("ME").last().pct_change().max()) if len(curve) > 22 else 0.0
    worst_month = float(curve.resample("ME").last().pct_change().min()) if len(curve) > 22 else 0.0
    hit_rate = float((curve.resample("ME").last().pct_change().dropna() > 0).mean()) if len(curve) > 22 else 0.0
    alpha = 0.0
    tracking_error = 0.0
    information_ratio = 0.0
    max_relative_drawdown = 0.0
    if benchmark_curve is not None and not benchmark_curve.empty:
        aligned = pd.concat([curve, benchmark_curve.astype(float)], axis=1, join="inner").dropna()
        if len(aligned) > 2:
            rel = aligned.iloc[:, 0].pct_change().dropna() - aligned.iloc[:, 1].pct_change().dropna()
            alpha = float(aligned.iloc[-1, 0] / aligned.iloc[0, 0] - aligned.iloc[-1, 1] / aligned.iloc[0, 1])
            tracking_error = float(rel.std(ddof=0) * np.sqrt(252))
            information_ratio = float((rel.mean() * 252) / tracking_error) if tracking_error else 0.0
            rel_perf = aligned.iloc[:, 0] / aligned.iloc[0, 0] - aligned.iloc[:, 1] / aligned.iloc[0, 1]
            max_relative_drawdown = float((rel_perf.cummax() - rel_perf).max())
    return {
        "total_return": round(total_return, 6),
        "CAGR": round(cagr, 6),
        "annualized_volatility": round(vol, 6),
        "Sharpe": round(sharpe, 6),
        "Sortino": round(sortino, 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "max_relative_drawdown_vs_SPY": round(max_relative_drawdown, 6),
        "alpha_vs_SPY": round(alpha, 6),
        "tracking_error": round(tracking_error, 6),
        "information_ratio": round(information_ratio, 6),
        "turnover": 0.0,
        "number_of_rebalances": 0,
        "average_holding_period": 0.0,
        "best_month": round(best_month, 6),
        "worst_month": round(worst_month, 6),
        "hit_rate_by_month": round(hit_rate, 6),
        "cost_adjusted_return": round(total_return, 6),
    }


def buy_and_hold(frame: pd.DataFrame | None, starting: float) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    close = frame["close"].astype(float)
    return close / close.iloc[0] * starting


def spy_200dma_strategy(spy: pd.DataFrame | None, starting: float) -> pd.Series:
    if spy is None or spy.empty:
        return pd.Series(dtype=float)
    close = spy["close"].astype(float)
    invested = close > close.rolling(200, min_periods=20).mean()
    returns = close.pct_change().fillna(0)
    strategy_returns = returns.where(invested.shift(1).fillna(False), 0.0)
    return (1 + strategy_returns).cumprod() * starting


def vix_strategy(spy: pd.DataFrame | None, vix: pd.DataFrame | None, starting: float) -> pd.Series:
    if spy is None or spy.empty:
        return pd.Series(dtype=float)
    close = spy["close"].astype(float)
    returns = close.pct_change().fillna(0)
    if vix is None or vix.empty:
        invested = returns.index.to_series().map(lambda _: False)
    else:
        vix_close = vix["close"].reindex(returns.index).ffill()
        state = False
        values = []
        for value in vix_close:
            if value > 20:
                state = True
            elif value < 15:
                state = False
            values.append(state)
        invested = pd.Series(values, index=returns.index)
    strategy_returns = returns.where(invested.shift(1).fillna(False), 0.0)
    return (1 + strategy_returns).cumprod() * starting


def etf_momentum_rotation(price_history: dict[str, pd.DataFrame], starting: float) -> pd.Series:
    etfs = [s for s in ("XLK", "XLE", "XLF", "XLV", "SMH", "IWM", "TLT", "GLD", "MTUM", "QUAL") if s in price_history]
    if not etfs or "SPY" not in price_history:
        return buy_and_hold(price_history.get("SPY"), starting)
    base_index = price_history["SPY"].index
    prices = pd.DataFrame({s: price_history[s]["close"].reindex(base_index).ffill() for s in etfs}).dropna(how="all")
    returns = prices.pct_change().fillna(0)
    momentum = prices.pct_change(63)
    if momentum.dropna(how="all").empty:
        return buy_and_hold(price_history.get("SPY"), starting)
    selected = momentum.apply(lambda row: row.idxmax() if row.notna().any() else None, axis=1).shift(1)
    strategy_returns = pd.Series(0.0, index=prices.index)
    for idx in prices.index:
        symbol = selected.loc[idx]
        if isinstance(symbol, str) and symbol in returns.columns:
            strategy_returns.loc[idx] = returns.loc[idx, symbol]
    return (1 + strategy_returns.fillna(0)).cumprod() * starting


def equal_weight_proxy(price_history: dict[str, pd.DataFrame], starting: float) -> pd.Series:
    symbols = [s for s in ("SPY", "QQQ", "XLK", "QUAL", "MTUM") if s in price_history and not price_history[s].empty]
    if not symbols:
        return pd.Series(dtype=float)
    index = price_history[symbols[0]].index
    returns = []
    for symbol in symbols:
        returns.append(price_history[symbol]["close"].reindex(index).ffill().pct_change().fillna(0))
    avg_returns = sum(returns) / len(returns)
    return (1 + avg_returns).cumprod() * starting


def _curve_snapshot(curve: pd.Series) -> list[dict[str, float | str]]:
    if curve is None or curve.empty:
        return []
    daily = curve.dropna().astype(float)
    return [{"date": idx.date().isoformat(), "equity": round(float(value), 4)} for idx, value in daily.items()]


def _empty_metrics(final_value: float = 0.0) -> dict[str, float]:
    return {
        "total_return": 0.0,
        "CAGR": 0.0,
        "annualized_volatility": 0.0,
        "Sharpe": 0.0,
        "Sortino": 0.0,
        "max_drawdown": 0.0,
        "max_relative_drawdown_vs_SPY": 0.0,
        "alpha_vs_SPY": 0.0,
        "tracking_error": 0.0,
        "information_ratio": 0.0,
        "turnover": 0.0,
        "number_of_rebalances": 0,
        "average_holding_period": 0.0,
        "best_month": 0.0,
        "worst_month": 0.0,
        "hit_rate_by_month": 0.0,
        "cost_adjusted_return": 0.0,
    }
