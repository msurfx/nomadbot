"""Serve the Nomad Bot dashboard locally, plus prices, candles, and wallet info.

Usage:  python scripts/serve_dashboard.py
Then open: http://localhost:8787

Data sources (all no-auth free tiers):
  prices     — CoinGecko
  candles    — CryptoCompare (primary) with CoinGecko fallback
  wallet     — Helius if HELIUS_API_KEY in .env, else public Solana mainnet RPC
"""
from __future__ import annotations

import json
import os
import sys
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# HTML lives in /public (Vercel serves /public/* statically; local server
# reads the same files). Falls back to /dashboard if /public is missing.
PUBLIC_DIR = ROOT / "public"
LEGACY_DIR = ROOT / "dashboard"
_HTML_ROOT = PUBLIC_DIR if PUBLIC_DIR.exists() else LEGACY_DIR
DASHBOARD = _HTML_ROOT / "index.html"
ABOUT = _HTML_ROOT / "about.html"
PORT = 8787

COINGECKO = "https://api.coingecko.com/api/v3"
COINGECKO_IDS = {
    "SOL/USD": "solana",
    "BTC/USD": "bitcoin",
    "ETH/USD": "ethereum",
    "JUP/USD": "jupiter-exchange-solana",
    "ZEC/USD": "zcash",
}

CRYPTOCOMPARE = "https://min-api.cryptocompare.com/data/v2"
TIMEFRAMES_CC = {
    "1m":  ("histominute", 1,   300),
    "5m":  ("histominute", 5,   288),
    "15m": ("histominute", 15,  192),
    "1h":  ("histohour",   1,   168),
    "4h":  ("histohour",   4,   180),
    "1d":  ("histoday",    1,   120),
}

# Kraken REST OHLC — primary (reliable, no auth, true interval control)
KRAKEN = "https://api.kraken.com/0/public/OHLC"
KRAKEN_INTERVAL_MIN = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
KRAKEN_PAIRS = {
    "SOL": "SOLUSD",
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "ZEC": "ZECUSD",
    # JUP isn't on Kraken; falls through to CoinGecko
}

# Jupiter-style TF -> CoinGecko days (CG picks the resolution for us)
TIMEFRAMES_CG = {
    "1m":  1,
    "5m":  1,
    "15m": 1,
    "1h":  7,
    "4h":  30,
    "1d":  90,
}

# Solana RPC: Helius if available, else public (slower, rate-limited).
HELIUS_KEY = os.environ.get("HELIUS_API_KEY", "").strip()
if HELIUS_KEY:
    SOLANA_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"
    print(f"  RPC: Helius (key set)")
else:
    SOLANA_RPC = "https://api.mainnet-beta.solana.com"
    print(f"  RPC: public mainnet-beta (rate limited — set HELIUS_API_KEY in .env for better)")

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# Ticker icon sources
ICON_URLS = {
    "SOL": "https://assets.coingecko.com/coins/images/4128/small/solana.png",
    "BTC": "https://assets.coingecko.com/coins/images/1/small/bitcoin.png",
    "ETH": "https://assets.coingecko.com/coins/images/279/small/ethereum.png",
    "JUP": "https://assets.coingecko.com/coins/images/34188/small/jup.png",
    "ZEC": "https://assets.coingecko.com/coins/images/486/small/circle-zcash-color.png",
}
ICON_FALLBACK_COLOR = {
    "SOL": "#9945FF", "JUP": "#FBA43A", "BTC": "#F7931A",
    "ETH": "#627EEA", "ZEC": "#F7B618",
}

# In-memory armed trades (per-session; cleared on server restart).
_armed_trades: list[dict] = []
_trade_id_counter = 0

_cache: dict[str, tuple[float, bytes]] = {}


def cached(key: str, ttl: float, fetch):
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    body = fetch()
    _cache[key] = (now + ttl, body)
    return body


def fetch_prices() -> dict:
    ids = ",".join(COINGECKO_IDS.values())
    r = requests.get(
        f"{COINGECKO}/simple/price",
        params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    out = {}
    for sym, cg_id in COINGECKO_IDS.items():
        info = data.get(cg_id, {})
        if "usd" in info:
            out[sym] = {"price": info["usd"], "change_24h": info.get("usd_24h_change")}
    return out


def fetch_candles_cc(symbol: str, tf: str) -> list[dict]:
    endpoint, aggregate, limit = TIMEFRAMES_CC[tf]
    base = symbol.split("/")[0]
    r = requests.get(
        f"{CRYPTOCOMPARE}/{endpoint}",
        params={"fsym": base, "tsym": "USD", "limit": limit, "aggregate": aggregate},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("Response") != "Success":
        raise RuntimeError(body.get("Message") or "cryptocompare error")
    bars = body["Data"]["Data"]
    out = []
    for bar in bars:
        if (bar.get("open") in (0, None)) and (bar.get("close") in (0, None)):
            continue
        out.append({
            "time": int(bar["time"]),
            "open": bar["open"], "high": bar["high"],
            "low": bar["low"], "close": bar["close"],
            "volume": bar.get("volumefrom", 0) or 0,
        })
    return out


def fetch_candles_cg(symbol: str, tf: str) -> list[dict]:
    """CoinGecko fallback. OHLC endpoint has no volume, so we pull volume from
    /market_chart and best-effort-match it to each candle by nearest timestamp.
    """
    days = TIMEFRAMES_CG.get(tf, 7)
    cg_id = COINGECKO_IDS.get(symbol)
    if not cg_id:
        raise ValueError(f"unknown symbol {symbol}")
    r = requests.get(
        f"{COINGECKO}/coins/{cg_id}/ohlc",
        params={"vs_currency": "usd", "days": days},
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json()
    candles = [
        {"time": int(row[0] / 1000), "open": row[1], "high": row[2],
         "low": row[3], "close": row[4], "volume": 0}
        for row in rows
    ]

    # Best-effort volume: /market_chart returns [[ms, usd_volume], ...]
    try:
        rv = requests.get(
            f"{COINGECKO}/coins/{cg_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
            timeout=15,
        )
        rv.raise_for_status()
        vol_rows = rv.json().get("total_volumes", [])
        if vol_rows and candles:
            vol_by_sec = [(int(v[0] / 1000), float(v[1])) for v in vol_rows]
            # Scale USD volume to a "base-asset-shaped" number using close price
            # so the histogram's magnitudes feel right relative to OHLC
            j = 0
            for c in candles:
                while j < len(vol_by_sec) - 1 and vol_by_sec[j + 1][0] <= c["time"]:
                    j += 1
                usd_vol = vol_by_sec[j][1]
                c["volume"] = usd_vol / max(c["close"], 1e-9)
    except Exception as e:
        print(f"  [candles] coingecko volume lookup failed: {e}", file=sys.stderr)

    return candles


def fetch_candles_kraken(symbol: str, tf: str) -> list[dict]:
    interval = KRAKEN_INTERVAL_MIN.get(tf)
    if not interval:
        raise ValueError(f"kraken: no interval for {tf}")
    base = symbol.split("/")[0]
    pair = KRAKEN_PAIRS.get(base)
    if not pair:
        raise ValueError(f"kraken: no pair for {base}")

    r = requests.get(
        KRAKEN,
        params={"pair": pair, "interval": interval},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"kraken: {body['error']}")
    result = body.get("result", {})
    # Pair key is pair-dependent (e.g. SOLUSD, XXBTZUSD). Grab the first list.
    bars = None
    for key, val in result.items():
        if key != "last" and isinstance(val, list):
            bars = val
            break
    if not bars:
        raise RuntimeError("kraken: no bars in result")

    return [
        {
            "time": int(bar[0]),
            "open": float(bar[1]),
            "high": float(bar[2]),
            "low": float(bar[3]),
            "close": float(bar[4]),
            "volume": float(bar[6]),
        }
        for bar in bars
    ]


def fetch_candles(symbol: str, tf: str) -> list[dict]:
    """Primary: Kraken (real interval control, no auth). Fallback: CoinGecko."""
    if tf not in TIMEFRAMES_CC:
        raise ValueError(f"unknown timeframe {tf}; try {list(TIMEFRAMES_CC)}")

    # Kraken first — proper intraday intervals with volume
    try:
        out = fetch_candles_kraken(symbol, tf)
        if out:
            return out
    except Exception as e:
        print(f"  [candles] kraken failed, trying cryptocompare: {e}", file=sys.stderr)

    # CryptoCompare second (requires key now, but try)
    try:
        out = fetch_candles_cc(symbol, tf)
        if out:
            return out
    except Exception as e:
        print(f"  [candles] cryptocompare failed, falling back to coingecko: {e}",
              file=sys.stderr)

    return fetch_candles_cg(symbol, tf)


def rpc_call(method: str, params: list) -> dict:
    r = requests.post(
        SOLANA_RPC,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message") or "rpc error")
    return body["result"]


@lru_cache(maxsize=32)
def fetch_icon(sym: str) -> tuple[bytes, str]:
    """Return (bytes, content_type) for a token icon. Falls back to inline SVG."""
    url = ICON_URLS.get(sym)
    if url:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            ctype = "image/png" if url.lower().endswith(".png") else "image/svg+xml"
            return r.content, ctype
        except Exception as e:
            print(f"  [icon] {sym} fetch failed, using fallback: {e}", file=sys.stderr)
    color = ICON_FALLBACK_COLOR.get(sym, "#9945FF")
    letter = sym[:1]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<circle cx="16" cy="16" r="16" fill="{color}"/>'
        f'<text x="16" y="22" text-anchor="middle" font-family="sans-serif" '
        f'font-size="16" font-weight="700" fill="#fff">{letter}</text>'
        f"</svg>"
    )
    return svg.encode(), "image/svg+xml"


def arm_trade(cfg: dict) -> dict:
    """Validate and store an armed trade configuration. No execution yet —
    actual order submission to Drift is the next build phase."""
    global _trade_id_counter
    required = ["market", "direction", "collateral_usd", "leverage", "trigger"]
    for k in required:
        if k not in cfg:
            raise ValueError(f"missing {k}")
    direction = cfg["direction"].lower()
    if direction not in ("long", "short"):
        raise ValueError("direction must be long or short")
    try:
        collateral = float(cfg["collateral_usd"])
        leverage = float(cfg["leverage"])
    except (TypeError, ValueError):
        raise ValueError("collateral and leverage must be numbers")
    if collateral <= 0 or leverage < 1 or leverage > 100:
        raise ValueError("collateral > 0 and leverage in [1, 100]")

    _trade_id_counter += 1
    entry = {
        "id": _trade_id_counter,
        "ts": int(time.time()),
        "market": cfg["market"],
        "direction": direction,
        "collateral_usd": collateral,
        "leverage": leverage,
        "position_usd": collateral * leverage,
        "trigger": cfg["trigger"],         # e.g. "bb_capitulation_1m" or "market"
        "stop_pct": float(cfg.get("stop_pct", 2.5)),
        "take_profit": cfg.get("take_profit", "bb_midline"),
        "status": "armed",                   # armed | triggered | executed | cancelled
        "note": "UI-armed only. Drift execution not wired yet.",
    }
    _armed_trades.insert(0, entry)
    return entry


def compute_bb_status(
    candles: list[dict],
    period: int = 20,
    std_mult: float = 2.0,
) -> dict | None:
    """Compute BB status for the latest candle. Always returns the %B value if
    enough history exists, regardless of whether it crosses a threshold."""
    if len(candles) < period + 1:
        return None
    closes = [c["close"] for c in candles]
    recent = closes[-period:]
    mean = sum(recent) / period
    var = sum((c - mean) ** 2 for c in recent) / period
    std = var ** 0.5
    upper = mean + std_mult * std
    lower = mean - std_mult * std
    close = closes[-1]
    if upper == lower:
        return None
    pct_b = (close - lower) / (upper - lower)
    return {
        "percent_b": round(pct_b, 4),
        "price": round(close, 6),
        "bb_lower": round(lower, 6),
        "bb_mid": round(mean, 6),
        "bb_upper": round(upper, 6),
    }


def scan_opportunities(
    symbols: list[str],
    timeframes: list[str],
    long_threshold: float = 0.15,
    short_threshold: float = 0.85,
) -> tuple[list[dict], list[dict]]:
    """Scan symbols × timeframes. Returns (firing, watching).

    firing: %B crosses long/short threshold → an actual entry setup
    watching: %B inside the neutral zone → still scanning, nothing fired
    """
    firing, watching = [], []
    now = int(time.time())
    for sym in symbols:
        full_sym = f"{sym}/USD"
        for tf in timeframes:
            if tf not in TIMEFRAMES_CC:
                continue
            try:
                candles = fetch_candles(full_sym, tf)
                status = compute_bb_status(candles)
                if not status:
                    continue
                status["symbol"] = sym
                status["timeframe"] = tf
                status["detected_at"] = now
                pb = status["percent_b"]
                if pb <= long_threshold:
                    status["side"] = "long"
                    firing.append(status)
                elif pb >= short_threshold:
                    status["side"] = "short"
                    firing.append(status)
                else:
                    watching.append(status)
            except Exception as e:
                print(f"  [opp] {sym} {tf} failed: {e}", file=sys.stderr)
    return firing, watching


def get_wallet(pubkey: str) -> dict:
    # SOL balance (lamports -> SOL)
    bal = rpc_call("getBalance", [pubkey])
    sol = bal.get("value", 0) / 1e9

    # USDC balance (sum across all owner accounts for that mint)
    usdc = 0.0
    try:
        accounts = rpc_call(
            "getTokenAccountsByOwner",
            [pubkey, {"mint": USDC_MINT}, {"encoding": "jsonParsed"}],
        )
        for acc in accounts.get("value", []):
            info = acc["account"]["data"]["parsed"]["info"]
            amt = info.get("tokenAmount", {}).get("uiAmount")
            if amt:
                usdc += float(amt)
    except Exception as e:
        print(f"  [wallet] USDC lookup failed: {e}", file=sys.stderr)

    sol_price = 0.0
    try:
        prices = fetch_prices()
        sol_price = float(prices.get("SOL/USD", {}).get("price", 0))
    except Exception:
        pass

    return {
        "pubkey": pubkey,
        "sol_balance": sol,
        "usdc_balance": usdc,
        "sol_price_usd": sol_price,
        "total_usd": sol * sol_price + usdc,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    @staticmethod
    def _strip_vercel_prefix(path: str) -> str:
        for prefix in ("/api/index.py", "/api/index", "/scripts/serve_dashboard"):
            if path == prefix:
                return "/"
            if path.startswith(prefix + "/"):
                return path[len(prefix):]
        return path

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = self._strip_vercel_prefix(u.path)
        qs = parse_qs(u.query)

        if path in ("/", "/index.html"):
            if not DASHBOARD.exists():
                self._send(500, b"dashboard/index.html missing", "text/plain")
                return
            self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
            return

        if path in ("/about", "/about.html", "/about/"):
            if not ABOUT.exists():
                self._send(500, b"dashboard/about.html missing", "text/plain")
                return
            self._send(200, ABOUT.read_bytes(), "text/html; charset=utf-8")
            return

        if path == "/api/prices":
            try:
                body = cached("prices", 10.0, lambda: json.dumps(fetch_prices()).encode())
                self._send(200, body, "application/json")
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if path.startswith("/api/candles/"):
            sym_part = path.rsplit("/", 1)[-1].upper()
            symbol = f"{sym_part}/USD"
            tf = qs.get("tf", ["1h"])[0].lower()
            key = f"candles:{symbol}:{tf}"
            ttl = 20.0 if tf in ("5m", "15m") else 60.0 if tf in ("1h", "4h") else 300.0
            try:
                body = cached(key, ttl, lambda: json.dumps(fetch_candles(symbol, tf)).encode())
                self._send(200, body, "application/json")
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if path == "/api/opportunities":
            tf_str = qs.get("timeframes", ["5m,15m,1h"])[0]
            sym_str = qs.get("symbols", ["SOL,BTC"])[0]
            tfs = [x.strip() for x in tf_str.split(",") if x.strip()]
            syms = [x.strip().upper() for x in sym_str.split(",") if x.strip()]
            # Only allow traded symbols
            syms = [s for s in syms if s in ("SOL", "BTC")]
            if not syms:
                syms = ["SOL", "BTC"]
            key = f"opp:{','.join(syms)}:{','.join(tfs)}"

            def do_scan():
                firing, watching = scan_opportunities(syms, tfs)
                return json.dumps({
                    "generated_at": int(time.time()),
                    "opportunities": firing,
                    "watching": watching,
                }).encode()

            try:
                body = cached(key, ttl=20.0, fetch=do_scan)
                self._send(200, body, "application/json")
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if path.startswith("/api/wallet/"):
            pubkey = path.rsplit("/", 1)[-1]
            if not (32 <= len(pubkey) <= 44):
                self._json(400, {"error": "pubkey looks wrong"})
                return
            key = f"wallet:{pubkey}"
            try:
                body = cached(key, 8.0, lambda: json.dumps(get_wallet(pubkey)).encode())
                self._send(200, body, "application/json")
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if path.startswith("/api/icon/"):
            sym = path.rsplit("/", 1)[-1].upper()
            try:
                data, ctype = fetch_icon(sym)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._send(500, str(e).encode(), "text/plain")
            return

        if path == "/api/trades":
            self._json(200, {"armed": _armed_trades})
            return

        if path == "/api/health":
            self._send(200, b'{"ok":true}', "application/json")
            return

        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = self._strip_vercel_prefix(u.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            self._json(400, {"error": "invalid JSON"})
            return

        if path == "/api/trades/arm":
            try:
                entry = arm_trade(payload)
                self._json(200, entry)
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if path == "/api/trades/cancel":
            trade_id = payload.get("id")
            global _armed_trades
            before = len(_armed_trades)
            _armed_trades = [t for t in _armed_trades if t["id"] != trade_id]
            self._json(200, {"removed": before - len(_armed_trades)})
            return

        self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):
        try:
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")
        except Exception:
            pass


def main() -> int:
    print(f"\n  Nomad dashboard  →  http://localhost:{PORT}")
    print(f"  Prices           →  http://localhost:{PORT}/api/prices")
    print(f"  Candles          →  http://localhost:{PORT}/api/candles/SOL?tf=1h")
    print(f"  Wallet           →  http://localhost:{PORT}/api/wallet/<pubkey>")
    print(f"  Timeframes       →  5m / 15m / 1h / 4h / 1d")
    print("  Ctrl-C to stop.\n")

    class _Server(ThreadingHTTPServer):
        allow_reuse_address = True

    try:
        _Server(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
