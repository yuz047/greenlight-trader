"""Supabase persistence + local JSON fallback.

The engine always writes to ``data/*.json`` regardless — those files
are committed to the repo and are what the Vercel dashboard reads when
no Supabase env is set. If ``SUPABASE_URL`` and
``SUPABASE_SERVICE_ROLE_KEY`` are present we also upsert into Postgres
via the REST API.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

import requests

from config import DATA_DIR, SUPABASE_URL_ENV, SUPABASE_KEY_ENV


# ---- JSON --------------------------------------------------------------

def write_json(name: str, payload: Any) -> Path:
    p = DATA_DIR / f"{name}.json"
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


def read_json(name: str, default=None):
    p = DATA_DIR / f"{name}.json"
    if not p.exists():
        return default
    return json.loads(p.read_text())


# ---- Supabase ----------------------------------------------------------

def _supabase_env():
    return os.environ.get(SUPABASE_URL_ENV), os.environ.get(SUPABASE_KEY_ENV)


def supabase_enabled() -> bool:
    url, key = _supabase_env()
    return bool(url and key)


def _headers(key: str, *, prefer_resolution: str = "merge-duplicates") -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": f"resolution={prefer_resolution}",
    }


def upsert(table: str, rows: Iterable[dict], on_conflict: str | None = None) -> dict:
    """POST rows to Supabase with upsert semantics. No-op if env not set."""
    rows = list(rows)
    if not rows:
        return {"ok": True, "rows": 0, "skipped": True}
    url, key = _supabase_env()
    if not url or not key:
        return {"ok": True, "rows": len(rows), "skipped": True, "reason": "no supabase env"}
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
    if on_conflict:
        endpoint += f"?on_conflict={on_conflict}"
    try:
        resp = requests.post(endpoint, headers=_headers(key), json=rows, timeout=20)
        if resp.status_code >= 300:
            return {"ok": False, "status": resp.status_code, "body": resp.text[:300]}
        return {"ok": True, "rows": len(rows)}
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}


def replace_table(table: str, rows: Iterable[dict], pk: str) -> dict:
    """Simple replace pattern: upsert all rows, delete missing PKs.

    For our small tables (positions, strategy_versions) this is the
    easiest way to keep Supabase in sync with the engine's view.
    """
    rows = list(rows)
    url, key = _supabase_env()
    if not url or not key:
        return {"ok": True, "rows": len(rows), "skipped": True, "reason": "no supabase env"}
    # Upsert (on_conflict on the PK)
    up = upsert(table, rows, on_conflict=pk)
    if not up.get("ok"):
        return up
    # Delete rows whose PK is not in `rows`
    if rows:
        keep = ",".join(f'"{r[pk]}"' for r in rows)
        del_url = f"{url.rstrip('/')}/rest/v1/{table}?{pk}=not.in.({keep})"
    else:
        del_url = f"{url.rstrip('/')}/rest/v1/{table}"
    try:
        resp = requests.delete(del_url, headers=_headers(key), timeout=20)
        return {"ok": resp.status_code < 300, "status": resp.status_code, "rows_kept": len(rows)}
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}
