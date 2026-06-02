"""Watermarked deterministic reviews and optional AI memo shells."""
from __future__ import annotations

from datetime import date
import json
import os
from typing import Any

import requests

from config import (
    DATA_DIR,
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_BASE_URL_ENV,
    DEEPSEEK_MODEL_ENV,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
)
from data_contracts import read_json, write_json
from watermark import AI_GENERATED_MEMO, SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark, watermarked_text


def build_systematic_review(
    decision_log: dict[str, Any],
    comparison_summary: dict[str, Any] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or decision_log.get("date") or date.today().isoformat()
    comparison_summary = comparison_summary or {}
    body = {
        "as_of": as_of,
        "memo_type": "systematic_template",
        "risk_light": decision_log.get("risk_light"),
        "market_regime": decision_log.get("market_regime"),
        "execution_decision": decision_log.get("execution_decision"),
        "execution_reason": decision_log.get("execution_reason"),
        "selected_etfs": [row.get("symbol") for row in decision_log.get("selected_etfs", [])],
        "top_stock_candidates": [row.get("symbol") for row in decision_log.get("top_stock_candidates", [])],
        "benchmark_verdict": comparison_summary.get("verdict", {}),
    }
    return add_watermark(body, SYSTEMATIC_TEMPLATE_OUTPUT)


def build_ai_memo(review: dict[str, Any], use_provider: bool = True) -> str:
    deepseek_text = _deepseek_memo(review) if use_provider else None
    if deepseek_text:
        body = (
            f"Provider: DeepSeek\n"
            f"Model: {os.getenv(DEEPSEEK_MODEL_ENV, DEFAULT_DEEPSEEK_MODEL)}\n"
            "Thinking: enabled\n"
            "Reasoning effort: high\n\n"
            f"{deepseek_text}\n\n"
            "Agent policy note: this memo may summarize and flag risks, but it may "
            "not execute, override risk, or mutate allocation logic."
        )
        return watermarked_text("Greenlight 2.0 AI Memo", body, AI_GENERATED_MEMO)

    body = (
        "Provider: deterministic fallback\n\n"
        f"Date: {review.get('as_of')}\n\n"
        f"Regime: {review.get('market_regime')}\n"
        f"Risk light: {review.get('risk_light')}\n"
        f"Execution: {review.get('execution_decision')} - {review.get('execution_reason')}\n\n"
        "Agent policy note: this memo may summarize and flag risks, but it may "
        "not execute, override risk, or mutate allocation logic."
    )
    return watermarked_text("Greenlight 2.0 AI Memo", body, AI_GENERATED_MEMO)


def append_ai_review(review: dict[str, Any], memo_text: str) -> dict[str, Any]:
    path = DATA_DIR / "ai_reviews.json"
    existing = read_json(path, default={"watermark": SYSTEMATIC_TEMPLATE_OUTPUT, "reviews": []})
    reviews = existing.get("reviews", []) if isinstance(existing, dict) else []
    reviews.append({"systematic_review": review, "memo": memo_text, "watermark": AI_GENERATED_MEMO})
    payload = add_watermark({"reviews": reviews[-50:]}, SYSTEMATIC_TEMPLATE_OUTPUT)
    write_json(path, payload)
    return payload


def _deepseek_memo(review: dict[str, Any]) -> str | None:
    api_key = os.getenv(DEEPSEEK_API_KEY_ENV)
    if not api_key:
        return None

    base_url = os.getenv(DEEPSEEK_BASE_URL_ENV, DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
    model = os.getenv(DEEPSEEK_MODEL_ENV, DEFAULT_DEEPSEEK_MODEL)
    safe_review = {
        "as_of": review.get("as_of"),
        "risk_light": review.get("risk_light"),
        "market_regime": review.get("market_regime"),
        "execution_decision": review.get("execution_decision"),
        "execution_reason": review.get("execution_reason"),
        "selected_etfs": review.get("selected_etfs"),
        "top_stock_candidates": review.get("top_stock_candidates"),
        "benchmark_verdict": review.get("benchmark_verdict"),
    }
    prompt = (
        "Write a concise Greenlight 2.0 end-of-day memo using only this JSON. Return the final memo only. "
        "Do not add unsupported market facts, do not recommend executable trades, "
        "and do not override risk controls. Mention uncertainty when data is weak.\n\n"
        f"{json.dumps(safe_review, sort_keys=True)}"
    )
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You summarize structured trading-system output. You cannot execute trades or modify strategy logic.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
                "max_tokens": 1200,
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["choices"][0]["message"]["content"].strip()
    except Exception:
        return None

    return text or None
