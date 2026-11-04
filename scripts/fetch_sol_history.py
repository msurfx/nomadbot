"""Fetch 90 days of SOL 1h candles from Birdeye and save to parquet."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from nomad.data.birdeye import BirdeyeClient, TOKENS, BirdeyeError


def main() -> int:
    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "sol_1h_90d.parquet"

    try:
        client = BirdeyeClient()
    except BirdeyeError as e:
        print(f"Error: {e}")
        return 1

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=90)

    print(f"Fetching SOL 1h candles from {start.date()} to {end.date()}...")
    try:
        df = client.ohlcv(TOKENS["SOL"], "1H", start=start, end=end)
    except BirdeyeError as e:
        print(f"Birdeye error: {e}")
        return 1

    if df.empty:
        print("No data returned.")
        return 1

    df.to_parquet(out_path)
    print(f"Saved {len(df)} candles → {out_path}")
    print(f"Range: {df.index.min()} → {df.index.max()}")
    print(f"Price: ${df['low'].min():.2f} low → ${df['high'].max():.2f} high")
    return 0


if __name__ == "__main__":
    sys.exit(main())
