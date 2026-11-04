"""Run the Bollinger backtest on saved SOL history."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from nomad.backtest.runner import backtest_bollinger


def main() -> int:
    data_path = Path(__file__).parent.parent / "data" / "sol_1h_90d.parquet"
    if not data_path.exists():
        print(f"No data at {data_path}.")
        print("Run: python scripts/fetch_sol_history.py")
        return 1

    candles = pd.read_parquet(data_path)
    print(f"Loaded {len(candles)} candles · {candles.index.min()} → {candles.index.max()}\n")

    print("Running BB mean-reversion backtest (1h, 20·2, vol 1.5x)...")
    result = backtest_bollinger(
        candles,
        starting_capital=1000,
        risk_per_trade_pct=1.5,
        bb_period=20,
        bb_std=2.0,
        vol_multiplier=1.5,
    )

    print("\n" + "=" * 50)
    print("BACKTEST RESULTS")
    print("=" * 50)
    print(result.summary())

    if result.trades:
        print("Trades (most recent 10):")
        for t in result.trades[-10:]:
            ts = t.entry_time.strftime("%Y-%m-%d %H:%M")
            exit_bits = (
                f"{t.exit_reason} @${t.exit_price:.2f}" if t.exit_price
                else "open"
            )
            pnl = f"${t.pnl:+.2f}" if not t.is_open else "..."
            print(f"  {ts}  {t.direction:5s}  entry ${t.entry_price:7.2f}  "
                  f"→ {exit_bits:28s}  {pnl}")

    print("\nTip: tune bb_period / bb_std / vol_multiplier in nomad/backtest/runner.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
