"""Bollinger-band mean-reversion signal with volume and wick-rejection confirmation.

A LONG fires when:
  - Price pokes the lower band (percent-B <= long_pct_b)
  - Volume is >= vol_multiplier * recent average (conviction)
  - The current candle has a lower wick >= 40% of its range and closes green (rejection)

SHORT is the mirror. Size scales with how deep the band touch is.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class SignalType(Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass
class Signal:
    type: SignalType
    price: float
    size_scale: float       # 0.0–1.0, how aggressively to size this entry
    reason: str
    bb_upper: float
    bb_lower: float
    bb_middle: float
    percent_b: float        # 0 at lower, 1 at upper
    volume_ratio: float     # current volume / avg

    # Suggested exits (strategy may override)
    stop: float
    target_1: float         # midline — take 50%
    target_2: float         # opposite band — take remaining 50%


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Compute Bollinger Bands. Returns [bb_middle, bb_upper, bb_lower, percent_b, bandwidth]."""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    percent_b = (close - lower) / (upper - lower)
    bandwidth = (upper - lower) / middle
    return pd.DataFrame({
        "bb_middle": middle,
        "bb_upper": upper,
        "bb_lower": lower,
        "percent_b": percent_b,
        "bandwidth": bandwidth,
    })


def detect_signal(
    candles: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    vol_period: int = 20,
    vol_multiplier: float = 1.5,
    long_pct_b: float = 0.05,
    short_pct_b: float = 0.95,
    min_wick_ratio: float = 0.4,
) -> Optional[Signal]:
    """Check the most recent closed candle for a BB mean-reversion signal.

    Returns None if nothing fires.
    """
    if len(candles) < max(bb_period, vol_period) + 2:
        return None

    bb = bollinger_bands(candles["close"], bb_period, bb_std)
    vol_avg = candles["volume"].rolling(window=vol_period).mean()

    i = -1  # last candle
    row = candles.iloc[i]
    close = float(row["close"])
    high = float(row["high"])
    low = float(row["low"])
    open_ = float(row["open"])
    volume = float(row["volume"])

    bb_upper = float(bb["bb_upper"].iloc[i])
    bb_lower = float(bb["bb_lower"].iloc[i])
    bb_middle = float(bb["bb_middle"].iloc[i])
    pct_b = float(bb["percent_b"].iloc[i])
    v_avg = float(vol_avg.iloc[i])

    if pd.isna(bb_middle) or pd.isna(v_avg) or v_avg == 0:
        return None

    vol_ratio = volume / v_avg
    candle_range = high - low
    if candle_range <= 0:
        return None

    # LONG setup
    if pct_b <= long_pct_b and vol_ratio >= vol_multiplier:
        lower_wick = min(open_, close) - low
        if lower_wick / candle_range >= min_wick_ratio and close > open_:
            size_scale = min(1.0, max(0.3, 1.0 - pct_b * 3))
            return Signal(
                type=SignalType.LONG,
                price=close,
                size_scale=size_scale,
                reason=(
                    f"BB lower touch (%B={pct_b:.2f}), "
                    f"vol {vol_ratio:.1f}x, wick rejection"
                ),
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_middle=bb_middle,
                percent_b=pct_b,
                volume_ratio=vol_ratio,
                stop=bb_lower * 0.995,
                target_1=bb_middle,
                target_2=bb_upper,
            )

    # SHORT setup
    if pct_b >= short_pct_b and vol_ratio >= vol_multiplier:
        upper_wick = high - max(open_, close)
        if upper_wick / candle_range >= min_wick_ratio and close < open_:
            size_scale = min(1.0, max(0.3, (pct_b - 0.67) * 3))
            return Signal(
                type=SignalType.SHORT,
                price=close,
                size_scale=size_scale,
                reason=(
                    f"BB upper touch (%B={pct_b:.2f}), "
                    f"vol {vol_ratio:.1f}x, wick rejection"
                ),
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_middle=bb_middle,
                percent_b=pct_b,
                volume_ratio=vol_ratio,
                stop=bb_upper * 1.005,
                target_1=bb_middle,
                target_2=bb_lower,
            )

    return None
