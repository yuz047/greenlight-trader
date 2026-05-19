"""Shared types for the strategies package.

Each strategy module exposes:
- ``MANIFEST`` — dict with id, version, rules text, default params, kind
- ``run(symbol, df, params, *, regime, sentiment, universe)`` — returns ``Signal | None``
  (the optional ``universe`` arg gives a strategy access to cross-sectional data
  when it needs to rank against peers, e.g. the stock pitcher).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class Signal:
    symbol: str
    strategy_id: str
    side: str
    rationale: str
    stop_distance: float
    target_distance: float
    max_hold_days: int
    score: float
    # extra fields used by pitches (next-day candidate list)
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
