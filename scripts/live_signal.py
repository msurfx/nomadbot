"""Pull recent SOL candles from Birdeye and check for a live signal."""
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
from nomad.data.jupiter_price import get_price
from nomad.signals.bollinger import detect_signal, bollinger_bands


def main() -> int:
    try:
        client = BirdeyeClient()
    except BirdeyeError as e:
        print(f"Error: {e}")
        return 1

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=5)

    print("Pulling SOL 1h candles from Birdeye...")
    try:
        candles = client.ohlcv(TOKENS["SOL"], "1H", start=start, end=end)
    except BirdeyeError as e:
        print(f"Birdeye error: {e}")
        return 1

    if len(candles) < 22:
        print(f"Not enough candles ({len(candles)}) for BB(20).")
        return 1

    jup = get_price("SOL/USD")
    print(f"Loaded {len(candles)} candles. Last close ${candles['close'].iloc[-1]:.2f}")
    print(f"Jupiter live: ${jup.price:,.4f}\n")

    signal = detect_signal(candles)
    if signal is None:
        bb = bollinger_bands(candles["close"])
        last_pct_b = bb["percent_b"].iloc[-1]
        print("No signal right now.")
        print(f"  Current %B: {last_pct_b:.2f}  (long <=0.05, short >=0.95)")
        return 0

    print(f"SIGNAL: {signal.type.value.upper()} at ${signal.price:.2f}")
    print(f"  Reason:    {signal.reason}")
    print(f"  Size:      {signal.size_scale:.2f}x of max")
    print(f"  Stop:      ${signal.stop:.2f}")
    print(f"  Target 1:  ${signal.target_1:.2f} (midline, close 50%)")
    print(f"  Target 2:  ${signal.target_2:.2f} (opposite band)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
