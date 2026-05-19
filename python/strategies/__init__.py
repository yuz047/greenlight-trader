"""Strategy registry — auto-discovers every module in this package.

To add a new strategy:

1. Drop ``my_strategy_v1.py`` into this folder.
2. Make sure it exposes:
       MANIFEST = {"id": "my_strategy_v1", "version": "1.0",
                   "rules": "...", "params": {...}, "kind": "signal"}
       def run(symbol, df, params, *, regime, sentiment, universe=None): ...
3. Add the id to ``ACTIVE_IDS`` in ``config.py``.

That's it — no other code needs to change. ``backtest.py`` and
``run_daily.py`` consult the registry via ``fire_all`` and ``manifests_for``.
"""
from __future__ import annotations
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from ._types import Signal


REGISTRY: Dict[str, dict] = {}  # id -> {"manifest": dict, "run": callable, "module": str}


def _discover() -> None:
    """Import every *.py module in this package (skipping private)."""
    pkg_dir = Path(__file__).parent
    for info in pkgutil.iter_modules([str(pkg_dir)]):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        manifest = getattr(mod, "MANIFEST", None)
        run = getattr(mod, "run", None)
        if not (isinstance(manifest, dict) and callable(run)):
            continue
        sid = manifest.get("id")
        if not sid:
            continue
        REGISTRY[sid] = {"manifest": manifest, "run": run, "module": info.name}


def manifests_for(ids: List[str]) -> List[dict]:
    out = []
    for sid in ids:
        entry = REGISTRY.get(sid)
        if not entry:
            continue
        m = dict(entry["manifest"])
        m["module"] = entry["module"]
        out.append(m)
    return out


def fire_all(
    enriched: Dict[str, pd.DataFrame],
    *, regime: str, sentiment: Dict[str, float],
    active_ids: List[str],
    universe: Optional[Dict[str, pd.DataFrame]] = None,
) -> List[Signal]:
    """Run every active strategy across every symbol; return sorted Signals.

    Some strategies (e.g. the stock pitcher) need cross-sectional context;
    we pass the full enriched ``universe`` in as a kwarg so they can rank.
    """
    out: List[Signal] = []
    universe = universe or enriched
    for sid in active_ids:
        entry = REGISTRY.get(sid)
        if not entry:
            continue
        params = entry["manifest"].get("params", {})
        fn = entry["run"]
        # Pass `universe` only if the strategy accepts it (keeps the simple
        # rule-based strategies free of cross-sectional plumbing).
        sig = inspect.signature(fn)
        kwargs = {"regime": regime, "sentiment": 0.0}
        if "universe" in sig.parameters:
            for sym, df in enriched.items():
                kwargs["sentiment"] = float(sentiment.get(sym, 0.0))
                kwargs["universe"] = universe
                res = fn(sym, df, params, **kwargs)
                if res is not None:
                    out.append(res)
        else:
            for sym, df in enriched.items():
                kwargs["sentiment"] = float(sentiment.get(sym, 0.0))
                res = fn(sym, df, params, **kwargs)
                if res is not None:
                    out.append(res)
    out.sort(key=lambda s: s.score, reverse=True)
    return out


_discover()
