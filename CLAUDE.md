# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pocket Option trading bot implementing the "Divine Formula" (7-second entry) strategy for EUR/USD OTC binary options on 5-minute candles. The system samples 6 prices during a candle's formation, runs multi-layer signal analysis, and executes BUY/SELL trades at ~8 seconds remaining.

## Commands

```bash
# Activate the virtual environment (Python 3.9)
cd ~/Desktop/Trading && source venv/bin/activate

# Run the offline/backtest bot (uses yfinance for price data, no browser)
python3 pocket_bot.py

# Run the live trading bot (launches Chromium via Playwright, logs into Pocket Option)
python3 -u pocket_live.py

# Install Playwright browsers (required once before pocket_live.py)
playwright install chromium
```

## Architecture

### Two bot variants

- **`pocket_bot.py`** — Standalone analysis bot. Fetches prices via `yfinance`, collects 6 samples (live timing or instant mode), runs the full analysis pipeline, and prints a consensus. Does NOT execute trades on the platform. Configurable via `RUN_MODE` ("live" waits for real candle timing, "instant" samples rapidly for testing) and `DEMO_MODE`.

- **`pocket_live.py`** — Full live bot. Uses Playwright to launch a headed Chromium browser, logs into Pocket Option, syncs to the platform's 5-minute candle countdown, collects 6 price samples at precise moments, runs analysis, and clicks the Buy/Sell button at 8 seconds remaining. Runs in a continuous loop (one trade per candle).

### Signal Pipeline (Divine Formula)

Both files implement the same core analysis from `Divine Formula sheet 7sec.xlsx`:

1. **Price Sampling** — 6 prices captured at specific seconds remaining before candle close:
   - B1 (105s), B2 (58s), B3 (43s), D1 (30s), D2 (26s), D3 (22s)
   - B4 = average of all 6 (simple) or weighted average

2. **Sheet3 Core** — Volatility classification (HIGH/MEDIUM/LOW), direction, strength, confirmation, safety check, trade timing with entry/expiry seconds

3. **Session Routing** — Different entry/expiry logic based on time-of-day and weekday vs weekend

4. **Advanced Signal** — 12-variable analysis (E1–E12) using momentum derivatives, RSI-like indicators, z-scores, and composite confidence. Produces HARD BUY/SELL, SOFT BUY/SELL, or WEAK BUY/SELL

5. **Reference Point** (pocket_bot.py only) — Candle OHLC momentum, predicted close, reference point buy/sell

6. **Consensus Vote** — 5–6 independent indicators vote BUY or SELL; majority wins

### HTML Checklist

- **`EURUSD_7sec_Checklist.html`** — Manual browser-based trade confirmation tool. Enter 6 prices, click Analyze, get signal + 5 confirmation checks (momentum, deceleration ratio, position, consistency, range) + final verdict. Includes flip-pattern warnings and payout math.

### Browser Automation (pocket_live.py)

Uses `playwright.sync_api` to:
- Login with email/password to pocketoption.com
- Dismiss popups/modals
- Set trade amount and expiry via DOM manipulation
- Click Buy/Sell buttons with timing precision (measures click latency in ms)

### Key Dependencies

- `yfinance` — Real-time EUR/USD price data
- `playwright` — Browser automation for live trading
- `pandas`, `numpy` — Installed but primarily used transitively by yfinance
- `openpyxl` — For reading the Divine Formula Excel spreadsheet

## Configuration

Both scripts have configuration constants at the top of the file. Key settings:

- `DEMO_MODE` — True for demo account, False for real money
- `ASSET` — Trading pair (pocket_bot uses "EURUSD=X" for yfinance, pocket_live uses "EUR/USD OTC")
- `TRADE_EXPIRY` — 7 seconds (the core divine formula timing)
- `TRADE_AT_REMAINING` — Place trade at 8 seconds remaining on candle
- Credentials in `pocket_live.py` (`EMAIL`, `PASSWORD`)

## Data Files

- `Divine Formula sheet 7sec.xlsx` — Source spreadsheet containing the original formula logic across multiple sheets (Sheet3, Sheet 3 Advanced, Reference Point)
- `lancedb/` — Empty LanceDB directory (vector DB, not yet in use)
