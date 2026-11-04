<p align="center">
  <img src="./logo.svg" alt="Nomad Bot" width="320">
</p>

<p align="center">
  <strong>Trade while you travel.</strong><br>
  A disciplined Solana trading bot for people who have other things to do than stare at charts.
</p>

<p align="center">
  <em>Bollinger-band mean reversion · multi-timeframe · sentiment-gated · non-custodial</em>
</p>

---

## What this is

Nomad Bot is a Solana-native trading bot. You run it on your own machine, connect your own wallet, pick a trading mode, and it watches the market 24/7 across multiple timeframes. When a setup fires, it opens a position on **Drift Protocol** (perps) or **Jupiter** (spot), sets a stop-loss immediately, and waits for one of two take-profit levels.

Every trade is logged with its reason. You can audit what the bot is doing at any moment, or step away for a week.

There is no custody. Your wallet signs transactions directly against Drift and Jupiter; Nomad never holds your funds.

## Status

**v0.7 — dashboard, data layer, signal engine, backtester, wallet connect.**

| Phase | Status |
|---|---|
| Data layer (candles, prices, wallet balance) | ✅ Shipped |
| Bollinger signal detector + volume + wick rejection | ✅ Shipped |
| Walk-forward backtester with partial exits | ✅ Shipped |
| Glass dashboard (live prices, candle chart with BB, order ticket) | ✅ Shipped |
| Phantom wallet connect + balance display | ✅ Shipped |
| **Drift SDK execution (open positions, place stops)** | ⏳ Next |
| Regime detector (chooses active strategy) | ⏳ |
| Sentiment module (X API + Claude classifier) | ⏳ |
| Deployed hosted dashboard | ⏳ |

**Right now, armed trades save to the backend but do NOT execute on Drift.** The next patch wires actual order submission.

## Quick start

Requires Python 3.10+.

```bash
# 1. Clone
git clone https://github.com/msurfx/nomadbot.git
cd nomadbot

# 2. Install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure (optional for data layer, needed for Birdeye candles)
cp .env.example .env
# edit .env and paste your Birdeye + Helius keys

# 4. Prove the data pipe (no keys needed)
python scripts/live_price.py

# 5. Open the glass dashboard
python scripts/serve_dashboard.py
# then open http://localhost:8787
```

## Dashboard

A single-page, glass-UI dashboard served locally:

- Live **SOL / JUP / BTC / ETH / ZEC** ticker (CoinGecko)
- **TradingView Lightweight Charts** with 5m / 15m / 1h / 4h / 1d timeframes
- **Bollinger Bands** overlaid on candles with volume histogram
- **Open Trade** order ticket — market, direction, leverage (1×–50× with a built-in guardrail), collateral, trigger strategy, stop-loss
- **Signal feed** showing entries, rejections, exits with their reasons
- **Open positions** table with real-time P&L
- **Phantom wallet** connect reading your real SOL + USDC balance
- **Mode toggle** — Cruise (safe default) / Pro (candle-bounce scalper for experienced traders)
- **Kill switch** — two-tap confirmation, always visible

See `/about` on the running dashboard for a full feature walkthrough.

## The engine

Rather than one master strategy, Nomad runs four specialists in parallel. A regime detector classifies volatility and trend every 5 minutes and decides which are armed:

| Strategy | Timeframe | Fires when |
|---|---|---|
| **Scalper BB** | 1m / 5m | Low volatility, majors only |
| **Swing BB** | 15m / 1h | Bollinger squeeze breakouts |
| **Trend rider** | 1h / 4h | Pullbacks in established trends |
| **Macro position** | 1d / spot | Multi-day sentiment-biased |
| **Candle bounce** *(Pro)* | 1m / 5m | Wick rejection + volume spike |

A **sentiment gate** pulls X posts every 15 min, classifies via Claude, and can veto or shrink entries that disagree with the current bias. Toggled off by default until the module is wired.

## Tech stack

- **Backend**: Python 3.10+ · pandas · requests · python-dotenv
- **Dashboard**: vanilla HTML/CSS/JS, no build step, served by a stdlib `http.server`
- **Charts**: [TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/) v4
- **Prices**: CoinGecko (free, no auth) with Jupiter Price v3 as a Solana-native secondary
- **Candles**: CryptoCompare with CoinGecko fallback
- **Wallet**: Solana Wallet Standard via Phantom provider
- **Chain reads**: Helius RPC (recommended) or public mainnet-beta
- **Execution** *(next)*: Drift Protocol (perps) + Jupiter Swap (spot)
- **Fonts**: Plus Jakarta Sans + JetBrains Mono

## Safety

**Automated trading on perpetual futures can lose your entire deposit.** Everything below is not optional reading.

- Fund a **dedicated hot wallet**, never your main.
- Backtest numbers assume liquidity and fills that may not exist in live markets. Historical performance does not predict future results.
- The bot has hard risk caps (per-trade %, max exposure, daily loss, min SOL reserve) — leave them on, especially while testing.
- Start on devnet, or with capital you can afford to lose entirely.
- Nothing in this repo is financial advice.

## Repo layout

```
nomadbot/
├── nomad/
│   ├── data/          # Birdeye (candles), Pyth/Jupiter (prices)
│   ├── signals/       # Bollinger + volume + wick-rejection detector
│   └── backtest/      # Walk-forward backtester
├── scripts/
│   ├── live_price.py
│   ├── fetch_sol_history.py
│   ├── run_backtest.py
│   ├── live_signal.py
│   └── serve_dashboard.py
├── dashboard/
│   ├── index.html     # Glass UI dashboard
│   └── about.html     # Marketing/about page
├── tests/
├── config.yaml
├── requirements.txt
├── .env.example       # copy to .env and fill in
└── logo.svg
```

## License

TBD. Intended as an open reference for Solana trading infrastructure, not a product.

## Disclaimer

This software is provided as-is, for educational and research purposes. The authors and contributors take no responsibility for financial losses incurred through its use. Use at your own risk.

Built in London. Compound responsibly.
