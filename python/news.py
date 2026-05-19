"""Lightweight news + sentiment.

Pulls Yahoo Finance per-symbol RSS feeds (no API key needed) and runs
a tiny lexicon over the headlines. Returns a sentiment score in
[-1, +1] per symbol. The goal is a *coarse* prior for the strategy
layer, not a real NLP system.

If the network is unavailable we return zeros — the rest of the
pipeline treats that as "neutral" and trades on technicals alone.
"""
from __future__ import annotations
from typing import Dict, List
import time

_POSITIVE = {
    "beat", "beats", "surge", "surges", "soar", "soared", "rally", "rallies",
    "gain", "gains", "rise", "rises", "upgrade", "upgraded", "record", "strong",
    "growth", "raises", "raised", "buyback", "approves", "approved",
    "outperform", "bullish", "expands", "expanded", "wins", "won", "profit",
    "profits", "exceeds", "topped",
}
_NEGATIVE = {
    "miss", "misses", "plunge", "plunges", "drop", "drops", "fall", "falls",
    "downgrade", "downgraded", "cut", "cuts", "loss", "losses", "weak",
    "warns", "warning", "lawsuit", "investigation", "probe", "recall",
    "bearish", "halts", "halted", "delays", "delayed", "fraud", "scandal",
    "layoffs", "layoff",
}

_YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


def _score_headlines(headlines: List[str]) -> float:
    if not headlines:
        return 0.0
    score = 0
    for h in headlines:
        words = {w.strip(".,:!?\"'()").lower() for w in h.split()}
        pos = len(words & _POSITIVE)
        neg = len(words & _NEGATIVE)
        score += (pos - neg)
    # Normalize to roughly [-1, 1] using soft clipping
    return max(-1.0, min(1.0, score / (3 * len(headlines))))


def fetch_headlines(ticker: str, timeout: float = 4.0, max_items: int = 8) -> List[str]:
    try:
        import feedparser  # type: ignore
    except Exception:
        return []
    try:
        feed = feedparser.parse(_YAHOO_RSS.format(ticker=ticker))
        return [entry.title for entry in feed.entries[:max_items]]
    except Exception:
        return []


def sentiment_for_universe(tickers: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    headlines_by_symbol: Dict[str, List[str]] = {}
    for t in tickers:
        headlines = fetch_headlines(t)
        headlines_by_symbol[t] = headlines
        out[t] = _score_headlines(headlines)
        # Small pause to be polite to Yahoo's feed
        time.sleep(0.2)
    return out, headlines_by_symbol  # type: ignore[return-value]


if __name__ == "__main__":
    s, hs = sentiment_for_universe(["AAPL", "TSLA"])
    for t in s:
        print(t, s[t])
        for h in hs[t][:3]:
            print("  ·", h)
