# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

- **Remote:** https://github.com/fazxes/Trading.git (private)
- **Branch:** main

## Project Overview

Pocket Option trading bot implementing the 7-second entry confirmation system for EUR/USD OTC binary options on 5-minute candles. The system samples 6 prices during a candle's formation, runs a 5-point confirmation checklist (momentum, deceleration ratio, position, consistency, range), and executes BUY/SELL trades at 8 seconds remaining with a 7-second expiry.

## Commands

```bash
# Activate the virtual environment (Python 3.9)
cd ~/Desktop/Trading && source venv/bin/activate

# Run the live trading bot (launches Chromium via Playwright, logs into Pocket Option)
python3 -u pocket_live.py

# Install dependencies (first time only)
pip install yfinance playwright
playwright install chromium
```

## Architecture

### Main Bot

- **`pocket_live.py`** — Full live bot. Uses Playwright to launch a headed Chromium browser, logs into Pocket Option, syncs to the platform's 5-minute candle countdown, collects 6 price samples at precise moments, runs the 5-confirmation analysis, and clicks the Buy/Sell button at 8 seconds remaining. Runs in a continuous loop (one trade per candle).

### Signal Pipeline (7-Second Entry Confirmation)

Formula logic is ported 1:1 from `EURUSD_7sec_Checklist.html`:

1. **Price Sampling** — 6 prices captured at specific seconds remaining before candle close:
   - B1 (150s), B2 (105s), B3 (60s), D1 (45s), D2 (30s), D3 (12s — trigger)

2. **Primary Signal** (`compute_signal`) — Skip filters (micro range, flat candle, direction flip), decel trap reversal detection, strong momentum check, fallback to D3 vs average

3. **5 Confirmations** (`check_confirmations`):
   - Momentum Continuation — D1→D2→D3 direction
   - Deceleration Ratio — |D3-D2| / |D2-D1|, thresholds at 0.8 (good) and 0.4 (bad)
   - Position Danger Zone — D3 position within candle range, extremes at 8%/92%
   - Trend Consistency — sign(B2-B1) + sign(B3-B2) + sign(D1-B3) + sign(D2-D1) + sign(D3-D2)
   - Range Quality — hi-lo in pips, thresholds at 0.0008/0.0003/0.0001

4. **Verdict** — All green = ENTER, any red = NO ENTRY, any yellow = CAUTION (skip by default)

### HTML Checklist

- **`EURUSD_7sec_Checklist.html`** — Browser-based manual confirmation tool. Same formula as the bot. Enter 6 prices, click Analyze, get signal + 5 confirmations + final verdict. Includes flip-pattern warnings and payout math.

### Browser Automation (pocket_live.py)

Uses `playwright.sync_api` to:
- Login with email/password to pocketoption.com
- Dismiss popups/modals
- Set trade amount and expiry via the platform's HH:MM:SS modal
- Click Buy/Sell buttons with timing precision (measures click latency in ms)

### Key Dependencies

- `yfinance` — Real-time EUR/USD price data
- `playwright` — Browser automation for live trading

## Configuration

Settings are at the top of `pocket_live.py`:

- `EMAIL` / `PASSWORD` — Pocket Option login credentials
- `DEMO_MODE` — True for demo account, False for real money
- `ASSET` — Trading pair (default: "EUR/USD OTC")
- `TRADE_AMOUNT` — Dollars per trade (default: 1)
- `TRADE_EXPIRY` — 7 seconds (do not change)
- `TRADE_AT_REMAINING` — Place trade at 8 seconds remaining (do not change)
- `TRADE_ON_CAUTION` — False = skip yellow warnings, True = trade anyway
- `SAMPLES` — Price collection schedule (seconds remaining on candle countdown)
