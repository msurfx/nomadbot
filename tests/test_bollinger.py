"""Smoke tests for the Bollinger signal and backtester."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from nomad.signals.bollinger import bollinger_bands, detect_signal, SignalType
from nomad.backtest.runner import backtest_bollinger


def _synth_candles(n: int = 200, seed: int = 7) -> pd.DataFrame:
    """Fake candles with mean-reverting behaviour and occasional band touches."""
    rng = np.random.default_rng(seed)
    base = 100.0
    closes = [base]
    for _ in range(n - 1):
        drift = -0.03 * (closes[-1] - base)   # revert toward base
        shock = rng.normal(0, 0.8)
        closes.append(max(1.0, closes[-1] + drift + shock))
    close = np.array(closes)
    opens = np.concatenate([[base], close[:-1]])
    high = np.maximum(opens, close) + rng.uniform(0.1, 0.5, n)
    low = np.minimum(opens, close) - rng.uniform(0.1, 0.5, n)
    volume = rng.uniform(1000, 3000, n)
    # Spike volume near band touches
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame({
        "open": opens, "high": high, "low": low, "close": close, "volume": volume
    }, index=idx)
    return df


def test_bb_shape():
    df = _synth_candles(100)
    bb = bollinger_bands(df["close"], period=20, num_std=2.0)
    assert set(bb.columns) == {"bb_middle", "bb_upper", "bb_lower", "percent_b", "bandwidth"}
    # Last 20 rows should be fully populated
    assert not bb.iloc[-1].isna().any()
    # Upper >= middle >= lower
    last = bb.iloc[-1]
    assert last["bb_upper"] >= last["bb_middle"] >= last["bb_lower"]


def test_detect_signal_returns_none_or_signal():
    df = _synth_candles(200)
    sig = detect_signal(df)
    assert sig is None or sig.type in (SignalType.LONG, SignalType.SHORT)


def test_backtest_runs_without_error():
    df = _synth_candles(500)
    result = backtest_bollinger(df, starting_capital=1000, risk_per_trade_pct=1.0)
    assert result.ending_capital > 0
    assert isinstance(result.num_trades, int)
    # Equity curve populated for every bar after the warm-up
    assert len(result.equity_curve) > 400


if __name__ == "__main__":
    test_bb_shape()
    test_detect_signal_returns_none_or_signal()
    test_backtest_runs_without_error()
    print("All smoke tests passed.")
