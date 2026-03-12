# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

- **Remote:** https://github.com/fazxes/Trading.git (private)
- **Branch:** main

## Project Overview

Pocket Option trading bot implementing the Deep Signal Engine v6 for EUR/USD OTC binary options on 5-minute candles. The system collects 288 prices (1/sec from 5:00 to 0:12), runs an 8-component scoring system (0-100% confidence), and executes BUY/SELL trades at 0:08 remaining with a 7-second expiry (expires at 0:01).

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

- **`pocket_live.py`** — Full live bot. Uses Playwright to launch a headed Chromium browser, logs into Pocket Option, syncs to the platform's 5-minute candle countdown (5:00 → 0:00), collects 288 prices (1/sec), runs the Deep Signal Engine v6, and clicks Buy/Sell at 0:08 remaining. Runs in a continuous loop (one trade per candle).

### Signal Pipeline (Deep Signal Engine v6)

Formula logic is ported 1:1 from `EURUSD_DeepSignal_v6_300sec.html`:

1. **Price Collection** — 288 prices captured at 1/sec from 5:00 to 0:12 remaining

2. **Detection** — Fake spike detection (>2.5x rolling std that reverses), reversal detection (5+ sec trend then 3+ sec flip), gap detection (>1.5 pip jumps)

3. **8-Component Scoring** (`run_deep_signal`):
   - ① Net Direction (spike-filtered) — max 20 points
   - ② Last 30s Momentum — max 20 points
   - ③ Consistency (% seconds aligned) — max 15 points
   - ④ Acceleration — max 10 points
   - ⑤ Range Size — max 10 points
   - ⑥ Fake Spike Penalty — max -15 points
   - ⑦ Reversal Penalty — max -15 points
   - ⑧ Last 10s Alignment — max 10 points

4. **Verdict** — Score ≥50% = ENTER, 35-49% = BORDERLINE (skip by default), <35% = SKIP, recent reversal = BLOCK

### HTML Reference

- **`EURUSD_DeepSignal_v6_300sec.html`** — Browser-based signal engine. Paste 300 prices, get full scoring breakdown with chart, spike/reversal markers, and second-by-second analysis.
- **`EURUSD_7sec_Checklist.html`** — Legacy 6-point checklist (no longer used by the bot).

### Browser Automation (pocket_live.py)

Uses `playwright.sync_api` to:
- Login with email/password to pocketoption.com
- Dismiss popups/modals
- Set trade amount and expiry via the platform's HH:MM:SS modal
- Click Buy/Sell buttons with timing precision (measures click latency in ms)

### Key Dependencies

- `playwright` — Browser automation for live trading (price feed via WebSocket, no yfinance needed)

## Configuration

Settings are at the top of `pocket_live.py`:

- `EMAIL` / `PASSWORD` — Pocket Option login credentials
- `DEMO_MODE` — True for demo account, False for real money
- `ASSET` — Trading pair (default: "EUR/USD OTC")
- `TRADE_AMOUNT` — Dollars per trade (default: 1)
- `TRADE_EXPIRY` — 7 seconds (do not change)
- `TRADE_AT_REMAINING` — Place trade at 8 seconds remaining (do not change)
- `TRADE_ON_CAUTION` — False = skip borderline scores (35-49%), True = trade anyway
- `COLLECT_UNTIL` — Stop collecting at 12 seconds remaining (trigger point)
- `MIN_PRICES` — Minimum prices needed for analysis (default: 120)
