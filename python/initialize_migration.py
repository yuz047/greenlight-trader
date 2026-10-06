"""Restore an explicit trustworthy baseline into private runtime storage."""
from __future__ import annotations
import argparse
import json
import subprocess
from config import DATA_DIR, ROOT

TRUSTED_COMMIT = "164c8a307449d6ce63e7f70bb829515b4c5eae31"


def initialize(commit: str = TRUSTED_COMMIT) -> dict:
    if DATA_DIR == (ROOT / "data").resolve():
        raise ValueError("Refusing to overwrite committed public production data")
    if (DATA_DIR / "portfolio_state.json").exists():
        raise ValueError("Runtime already initialized; select a fresh GREENLIGHT_DATA_DIR")
    files = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "--name-only", commit + ":data"], text=True).splitlines()
    for name in files:
        if name.endswith((".json", ".md")) and "/" not in name:
            payload = subprocess.check_output(["git", "-C", str(ROOT), "show", commit + ":data/" + name])
            (DATA_DIR / name).write_bytes(payload)
    path = DATA_DIR / "portfolio_state.json"
    state = json.loads(path.read_text())
    provenance = {"commit": commit, "date": state["date"], "original_nav": state["nav"],
                  "method": "restore_trusted_positions_then_revalue;no_missing_intervening_trades_invented"}
    state["recovery_provenance"] = provenance
    path.write_text(json.dumps(state, indent=2) + "\n")
    (DATA_DIR / "migration_provenance.json").write_text(json.dumps({"watermark": "SYSTEMATIC_TEMPLATE_OUTPUT", **provenance}, indent=2) + "\n")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=TRUSTED_COMMIT)
    print(json.dumps(initialize(parser.parse_args().baseline)))
