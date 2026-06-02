"""Validate required watermarks."""
from __future__ import annotations

import json
import sys

from config import DATA_DIR, REQUIRED_OUTPUTS
from watermark import VALID_WATERMARKS, find_watermarks


def main() -> None:
    failures = []
    for name in REQUIRED_OUTPUTS:
        path = DATA_DIR / name
        if not path.exists():
            failures.append(f"missing {name}")
            continue
        if path.suffix == ".json":
            payload = json.loads(path.read_text())
            found = find_watermarks(payload)
        else:
            text = path.read_text()
            found = {wm for wm in VALID_WATERMARKS if wm in text}
        if not found:
            failures.append(f"missing watermark in {name}")
    if failures:
        raise SystemExit("\n".join(failures))
    print("watermark validation passed")


if __name__ == "__main__":
    main()
