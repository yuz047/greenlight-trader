"""Import the user's real diagnostic CSVs into the private provider cache."""
import argparse
from pathlib import Path
import pandas as pd
from yfinance_client import YFinanceClient

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    client = YFinanceClient()
    count = 0
    for path in sorted(args.input_dir.glob("*-raw.csv")):
        symbol = path.name.removesuffix("-raw.csv").replace("index-", "^")
        frame = pd.read_csv(path, index_col=0)
        # Preserve exchange-local dates even across daylight-saving offsets.
        frame.index = pd.to_datetime(frame.index.str[:10])
        client.store_history(symbol, frame, args.start, args.end)
        count += 1
    print(f"Imported {count} real-symbol histories into private cache; no network requests")
