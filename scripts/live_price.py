"""Live price watcher via Jupiter Price API. No key needed."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nomad.data.jupiter_price import get_prices


def main() -> int:
    symbols = ["SOL/USD", "JUP/USD", "JTO/USD", "WIF/USD"]
    print(f"Watching {', '.join(symbols)} via Jupiter. Ctrl-C to stop.\n")
    try:
        while True:
            try:
                prices = get_prices(symbols)
                parts = []
                for sym in symbols:
                    p = prices.get(sym)
                    parts.append(f"{sym} ${p.price:,.4f}" if p else f"{sym} -")
                print(f"\r{' . '.join(parts)}   ", end="", flush=True)
            except Exception as e:
                print(f"\rerror: {e}   ", end="", flush=True)
            time.sleep(2.5)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
