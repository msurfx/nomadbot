"""Walk-forward backtester for the Bollinger-band mean-reversion strategy.

Sizes each trade so that the stop distance equals `risk_per_trade_pct` of
current equity (position-size risk sizing), and manages two targets:
  T1 at the BB midline — closes 50% of the position
  T2 at the opposite BB band — closes the remaining 50%
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ..signals.bollinger import bollinger_bands


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: str              # "long" | "short"
    entry_price: float
    size: float                 # units of the asset
    stop: float
    target_1: float
    target_2: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    partial_pnl: float = 0.0    # realised on T1 fill
    partial_closed: bool = False

    @property
    def is_open(self) -> bool:
        return self.exit_time is None


@dataclass
class BacktestResult:
    starting_capital: float
    ending_capital: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        return (self.ending_capital / self.starting_capital - 1) * 100

    @property
    def num_trades(self) -> int:
        return len([t for t in self.trades if not t.is_open])

    @property
    def win_rate(self) -> float:
        closed = [t for t in self.trades if not t.is_open]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.pnl > 0)
        return wins / len(closed) * 100

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades if not t.is_open)

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0][1]
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)
        return max_dd

    def summary(self) -> str:
        return (
            f"Starting capital:  ${self.starting_capital:,.2f}\n"
            f"Ending capital:    ${self.ending_capital:,.2f}\n"
            f"Total return:      {self.total_return_pct:+.2f}%\n"
            f"Trades closed:     {self.num_trades}\n"
            f"Win rate:          {self.win_rate:.1f}%\n"
            f"Max drawdown:      {self.max_drawdown_pct:.2f}%\n"
        )


def backtest_bollinger(
    candles: pd.DataFrame,
    starting_capital: float = 1000,
    risk_per_trade_pct: float = 1.5,
    bb_period: int = 20,
    bb_std: float = 2.0,
    vol_period: int = 20,
    vol_multiplier: float = 1.5,
    long_pct_b: float = 0.05,
    short_pct_b: float = 0.95,
    min_wick_ratio: float = 0.4,
    allow_short: bool = True,
) -> BacktestResult:
    """Walk-forward backtest. One trade at a time, no overlapping positions."""
    bb = bollinger_bands(candles["close"], bb_period, bb_std)
    vol_avg = candles["volume"].rolling(window=vol_period).mean()

    result = BacktestResult(starting_capital=starting_capital)
    capital = starting_capital
    open_trade: Optional[Trade] = None

    start_i = max(bb_period, vol_period) + 1

    for i in range(start_i, len(candles)):
        row = candles.iloc[i]
        ts = candles.index[i]
        bb_row = bb.iloc[i]

        # --- 1) Manage any open trade ---
        if open_trade is not None:
            high = float(row["high"])
            low = float(row["low"])

            if open_trade.direction == "long":
                # Stop hit first (conservative: assume stop fills if low <= stop)
                if low <= open_trade.stop:
                    exit_price = open_trade.stop
                    remaining = open_trade.size * (1 if not open_trade.partial_closed else 0.5)
                    open_trade.pnl = (
                        open_trade.partial_pnl
                        + remaining * (exit_price - open_trade.entry_price)
                    )
                    open_trade.exit_price = exit_price
                    open_trade.exit_time = ts
                    open_trade.exit_reason = "stop"
                    capital += open_trade.pnl
                    result.trades.append(open_trade)
                    open_trade = None
                # T1 (midline) — close 50%
                elif not open_trade.partial_closed and high >= open_trade.target_1:
                    half = open_trade.size * 0.5
                    open_trade.partial_pnl = half * (open_trade.target_1 - open_trade.entry_price)
                    open_trade.partial_closed = True
                    # Move stop to breakeven after T1
                    open_trade.stop = max(open_trade.stop, open_trade.entry_price)
                # T2 (upper band)
                elif open_trade.partial_closed and high >= open_trade.target_2:
                    half = open_trade.size * 0.5
                    exit_price = open_trade.target_2
                    open_trade.pnl = (
                        open_trade.partial_pnl
                        + half * (exit_price - open_trade.entry_price)
                    )
                    open_trade.exit_price = exit_price
                    open_trade.exit_time = ts
                    open_trade.exit_reason = "target_2"
                    capital += open_trade.pnl
                    result.trades.append(open_trade)
                    open_trade = None
            else:  # short
                if high >= open_trade.stop:
                    exit_price = open_trade.stop
                    remaining = open_trade.size * (1 if not open_trade.partial_closed else 0.5)
                    open_trade.pnl = (
                        open_trade.partial_pnl
                        + remaining * (open_trade.entry_price - exit_price)
                    )
                    open_trade.exit_price = exit_price
                    open_trade.exit_time = ts
                    open_trade.exit_reason = "stop"
                    capital += open_trade.pnl
                    result.trades.append(open_trade)
                    open_trade = None
                elif not open_trade.partial_closed and low <= open_trade.target_1:
                    half = open_trade.size * 0.5
                    open_trade.partial_pnl = half * (open_trade.entry_price - open_trade.target_1)
                    open_trade.partial_closed = True
                    open_trade.stop = min(open_trade.stop, open_trade.entry_price)
                elif open_trade.partial_closed and low <= open_trade.target_2:
                    half = open_trade.size * 0.5
                    exit_price = open_trade.target_2
                    open_trade.pnl = (
                        open_trade.partial_pnl
                        + half * (open_trade.entry_price - exit_price)
                    )
                    open_trade.exit_price = exit_price
                    open_trade.exit_time = ts
                    open_trade.exit_reason = "target_2"
                    capital += open_trade.pnl
                    result.trades.append(open_trade)
                    open_trade = None

        # Track equity after any exits
        result.equity_curve.append((ts, capital))

        if open_trade is not None:
            continue
        if pd.isna(bb_row["bb_middle"]) or pd.isna(vol_avg.iloc[i]):
            continue

        # --- 2) Look for a new entry ---
        high = float(row["high"])
        low = float(row["low"])
        open_p = float(row["open"])
        close = float(row["close"])
        volume = float(row["volume"])
        v_avg = float(vol_avg.iloc[i])
        if v_avg == 0:
            continue
        vol_ratio = volume / v_avg
        candle_range = high - low
        if candle_range <= 0:
            continue

        pct_b = float(bb_row["percent_b"])
        bb_mid = float(bb_row["bb_middle"])
        bb_up = float(bb_row["bb_upper"])
        bb_lo = float(bb_row["bb_lower"])

        # Long entry
        if pct_b <= long_pct_b and vol_ratio >= vol_multiplier:
            lower_wick = min(open_p, close) - low
            if lower_wick / candle_range >= min_wick_ratio and close > open_p:
                stop = bb_lo * 0.995
                risk_per_unit = close - stop
                if risk_per_unit > 0:
                    risk_dollars = capital * risk_per_trade_pct / 100
                    size = risk_dollars / risk_per_unit
                    open_trade = Trade(
                        entry_time=ts,
                        direction="long",
                        entry_price=close,
                        size=size,
                        stop=stop,
                        target_1=bb_mid,
                        target_2=bb_up,
                    )
                    continue

        # Short entry
        if allow_short and pct_b >= short_pct_b and vol_ratio >= vol_multiplier:
            upper_wick = high - max(open_p, close)
            if upper_wick / candle_range >= min_wick_ratio and close < open_p:
                stop = bb_up * 1.005
                risk_per_unit = stop - close
                if risk_per_unit > 0:
                    risk_dollars = capital * risk_per_trade_pct / 100
                    size = risk_dollars / risk_per_unit
                    open_trade = Trade(
                        entry_time=ts,
                        direction="short",
                        entry_price=close,
                        size=size,
                        stop=stop,
                        target_1=bb_mid,
                        target_2=bb_lo,
                    )

    # Close any still-open trade at the last close
    if open_trade is not None:
        last_ts = candles.index[-1]
        last_price = float(candles["close"].iloc[-1])
        remaining = open_trade.size * (1 if not open_trade.partial_closed else 0.5)
        if open_trade.direction == "long":
            open_trade.pnl = open_trade.partial_pnl + remaining * (last_price - open_trade.entry_price)
        else:
            open_trade.pnl = open_trade.partial_pnl + remaining * (open_trade.entry_price - last_price)
        open_trade.exit_price = last_price
        open_trade.exit_time = last_ts
        open_trade.exit_reason = "end_of_data"
        capital += open_trade.pnl
        result.trades.append(open_trade)

    result.ending_capital = capital
    return result
