# Pocket Option Trading Bot — 7-Second Entry System

An automated trading bot for Pocket Option that trades EUR/USD OTC on 5-minute candles. It watches the candle form, collects 6 price readings at specific moments, runs a 5-point confirmation checklist, and places the trade at 8 seconds before the candle closes — with a 7-second expiry.

---

## What You Need Before Starting

Before you do anything, make sure you have these:

1. **A Mac computer** (this bot was built and tested on macOS)
2. **A Pocket Option account** — you need your login email and password
3. **Claude Code installed** — this is the tool you'll use to set everything up
4. **Python 3.9 or newer** — most Macs come with this. If you're not sure, don't worry — Claude Code can check for you.

---

## How to Set Everything Up (Copy-Paste This Into Claude Code)

Open Claude Code and paste the following message. Claude will do everything for you:

```
I need you to set up the Pocket Option trading bot from this GitHub repo:
https://github.com/fazxes/Trading.git

Here's what I need you to do step by step:

1. Clone the repo to my Desktop:
   git clone https://github.com/fazxes/Trading.git ~/Desktop/Trading

2. Go into that folder:
   cd ~/Desktop/Trading

3. Create a Python virtual environment:
   python3 -m venv venv

4. Activate the virtual environment:
   source venv/bin/activate

5. Install the required packages:
   pip install yfinance playwright

6. Install the browser that the bot uses:
   playwright install chromium

7. Open the file pocket_live.py and update the CONFIGURATION section at the top:
   - Change EMAIL to my Pocket Option email: [PUT YOUR EMAIL HERE]
   - Change PASSWORD to my Pocket Option password: [PUT YOUR PASSWORD HERE]
   - Set DEMO_MODE = True (this uses fake money so I can test safely)
   - Set TRADE_AMOUNT = 1 (1 dollar per trade)
   - Leave everything else as default

8. Confirm everything is ready and tell me the exact command to run the bot.
```

**IMPORTANT: Replace `[PUT YOUR EMAIL HERE]` and `[PUT YOUR PASSWORD HERE]` with your actual Pocket Option login details before pasting.**

---

## How to Run the Bot

Once Claude has set everything up, this is the command to run the bot:

```bash
cd ~/Desktop/Trading && source venv/bin/activate && python3 -u pocket_live.py
```

What this does:
- `cd ~/Desktop/Trading` — goes to the bot's folder
- `source venv/bin/activate` — turns on the Python environment
- `python3 -u pocket_live.py` — starts the bot

A browser window will open automatically. The bot will:
1. Log into your Pocket Option account
2. Navigate to the trading page
3. Set the trade amount and expiry time
4. Start watching candles and trading automatically

---

## What You'll See When It's Running

The bot prints everything it's doing. Here's what a normal cycle looks like:

```
============================================================
  POCKET BOT - 7sec Entry Confirmation
  Account: DEMO
  Asset:   EUR/USD OTC
  Amount:  $1
  Expiry:  7s
  Candle:  5min
  Trade at: 8s remaining
============================================================
[LOGIN] Opening Pocket Option...
[LOGIN] Success! Loading trading page...
[READY] Bot is running. Ctrl+C to stop.

============================================================
  CANDLE CYCLE
  Candle ends: 14:35:00  (280s remaining)
============================================================
[SAMPLE] B1 = 1.08520  (at 150s remaining)
[SAMPLE] B2 = 1.08525  (at 105s remaining)
[SAMPLE] B3 = 1.08530  (at 60s remaining)
[SAMPLE] D1 = 1.08535  (at 45s remaining)
[SAMPLE] D2 = 1.08538  (at 30s remaining)
[SAMPLE] D3 = 1.08542  (at 12s remaining)

[ANALYSIS] 0ms
  Signal: BUY
  [✓] Momentum: STRONG UP
  [✓] Decel Ratio: ACCEL 85%
  [✓] Position: UPPER 72.3%
  [✓] Consistency: 5/5 ALIGNED
  [✓] Range: ADEQUATE 4.2p
  VERDICT: BUY

  >>> BUY TRADE PLACED <<<
  Fired at:    8.0s remaining
  Click time:  55ms
  Expiry:      7s
  Expires at:  ~1.0s remaining
```

**What the symbols mean:**
- `[✓]` = That check passed (green light)
- `[!]` = Warning — the check is uncertain (yellow light)
- `[✗]` = That check failed (red light — bot will NOT trade)

---

## What the Bot Decides

The bot collects 6 price readings during each 5-minute candle, then runs 5 safety checks:

| Check | What It Looks At | Green = Safe | Red = Don't Trade |
|-------|------------------|--------------|-------------------|
| Momentum | Is the price still moving in one direction? | D3 > D2 > D1 (or all falling) | Price reversed at D3 |
| Decel Ratio | Is the movement slowing down? | Still accelerating (80%+) | Decelerating hard (<40%) |
| Position | Is D3 at an extreme? | Between 8%-92% of range | Above 92% or below 8% |
| Consistency | Are all 6 prices trending together? | 4 or 5 out of 5 aligned | Less than 2 aligned |
| Range | Is the candle big enough to trade? | More than 3 pips range | Less than 1 pip |

**The bot will only trade when:**
- The primary signal says BUY or SELL (not SKIP)
- NONE of the 5 checks show a red flag
- By default, it also skips if any check shows a yellow warning (you can change this)

---

## Configuration — What You Can Change

All settings are at the top of `pocket_live.py`. Ask Claude Code to change them for you:

| Setting | What It Does | Default | Options |
|---------|-------------|---------|---------|
| `EMAIL` | Your Pocket Option login email | — | Your email |
| `PASSWORD` | Your Pocket Option password | — | Your password |
| `DEMO_MODE` | Use demo (fake) or real money | `True` | `True` = demo, `False` = real |
| `ASSET` | What to trade | `EUR/USD OTC` | Any asset on the platform |
| `TRADE_AMOUNT` | How much per trade (dollars) | `1` | Any amount |
| `TRADE_EXPIRY` | How long the trade lasts | `7` seconds | Don't change this |
| `TRADE_AT_REMAINING` | When to place the trade | `8` seconds before candle end | Don't change this |
| `TRADE_ON_CAUTION` | Trade even with yellow warnings? | `False` | `True` = more trades but riskier |

**To change a setting, tell Claude Code something like:**
```
Open pocket_live.py and change DEMO_MODE to False
```

---

## How to Stop the Bot

Press `Ctrl + C` in the terminal. The bot will stop and the browser will close.

If the terminal is frozen or unresponsive, close the terminal window entirely. The browser may stay open — just close it manually.

---

## Do's and Don'ts

### DO:

- **DO start with DEMO_MODE = True** — Always test with fake money first. Make sure the bot is logging in, placing trades, and the timing looks right before using real money.
- **DO keep the browser window visible** — The bot clicks the Buy/Sell buttons on the actual website. If you minimize or close the browser, it can't trade.
- **DO let each candle complete** — The bot waits for specific moments during the 5-minute candle. Don't expect instant trades. It will sit and wait — that's normal.
- **DO check that the expiry shows 7 seconds on the platform** — After the bot starts, look at the trading page and verify the expiry time says "00:00:07". If it doesn't, set it manually.
- **DO check that the amount shows $1 (or your chosen amount)** — Same thing. Verify it on the platform after the bot starts.
- **DO keep your computer awake** — If your Mac goes to sleep, the bot stops. Go to System Settings > Displays > Turn off "Turn display off" while the bot runs. Or use a "keep awake" app.
- **DO watch the first few candles** — Make sure everything is working before walking away.

### DON'T:

- **DON'T use real money until you've tested with demo** — Seriously. Test at least 10-20 candles on demo first.
- **DON'T close the browser window** — The bot needs it open to click Buy/Sell.
- **DON'T click anything on the trading page while the bot is running** — You might accidentally change the asset, amount, or expiry. Let the bot do its thing.
- **DON'T run multiple copies of the bot at the same time** — One instance only.
- **DON'T change the TRADE_EXPIRY or TRADE_AT_REMAINING** — These are tuned for the 7-second formula. Changing them breaks the strategy.
- **DON'T panic if the bot skips a candle** — The bot is DESIGNED to skip unsafe candles. A skipped trade is a saved dollar. The formula filters out bad setups on purpose.
- **DON'T expect to win every trade** — This is binary options. The formula aims for ~60% win rate. You will lose some trades. That's normal and expected. At 92% payout, you only need 52.1% to break even.

---

## Common Issues and Fixes

### "The bot isn't placing trades — it keeps saying SKIP"
This is normal. The formula has strict filters. If the market is flat (small range) or the price is behaving erratically, it will skip. This protects you from bad trades. Wait for more active market hours (typically 06:00-12:00 UTC).

### "The browser opened but the bot says it can't log in"
Your email or password might be wrong. Tell Claude Code:
```
Open pocket_live.py and show me the EMAIL and PASSWORD settings
```
Fix them if they're wrong. Also make sure you can log into pocketoption.com manually first.

### "The expiry is showing 3 seconds instead of 7"
The bot tries to set it automatically, but sometimes the platform doesn't respond. Manually click the expiry time on the trading page and set it to 00:00:07 (7 seconds).

### "The amount is wrong"
Same thing — manually set the amount on the platform. The bot will continue working with whatever amount is showing.

### "I see a warning about urllib3 or OpenSSL"
Ignore it. It's cosmetic and doesn't affect anything. The bot suppresses it automatically.

### "The bot crashed or froze"
Press `Ctrl + C` to stop it, then run it again:
```bash
cd ~/Desktop/Trading && source venv/bin/activate && python3 -u pocket_live.py
```

### "I want to switch to real money"
Tell Claude Code:
```
Open pocket_live.py and change DEMO_MODE from True to False
```
Then restart the bot. **Only do this after thorough demo testing.**

---

## How the Formula Works (Simple Version)

Every 5 minutes, a new candle starts on the chart. The bot watches it form:

```
Candle starts (5:00 remaining)
   |
   |--- B1 price captured at 2:30 remaining
   |--- B2 price captured at 1:45 remaining
   |--- B3 price captured at 1:00 remaining
   |--- D1 price captured at 0:45 remaining
   |--- D2 price captured at 0:30 remaining
   |--- D3 price captured at 0:12 remaining  <-- TRIGGER
   |
   |--- Analysis runs instantly (< 1 millisecond)
   |--- If all 5 checks pass: TRADE at 0:08 remaining
   |--- Trade expires at ~0:01 remaining
   |
Candle closes (0:00)
   |
Next candle starts...
```

The bot is predicting what the price will do in the LAST 7 seconds of the candle, based on how it behaved during the candle's formation. If the price was steadily rising and all safety checks pass, it buys. If steadily falling, it sells. If anything looks off, it skips.

---

## File Structure

```
~/Desktop/Trading/
  pocket_live.py              <-- The bot (this is what you run)
  EURUSD_7sec_Checklist.html  <-- The formula reference (open in browser to test manually)
  CLAUDE.md                   <-- Instructions for Claude Code
  README.md                   <-- This file
  venv/                       <-- Python environment (created during setup)
```

---

## Quick Reference — Commands to Tell Claude Code

| What you want to do | What to tell Claude Code |
|---------------------|--------------------------|
| Set up everything from scratch | Copy the setup block from the "How to Set Everything Up" section above |
| Change to real money | "Change DEMO_MODE to False in pocket_live.py" |
| Change back to demo | "Change DEMO_MODE to True in pocket_live.py" |
| Change the trade amount | "Change TRADE_AMOUNT to 5 in pocket_live.py" |
| Change the asset | "Change ASSET to 'GBP/USD OTC' in pocket_live.py" |
| Trade on yellow warnings too | "Change TRADE_ON_CAUTION to True in pocket_live.py" |
| See what settings are currently set | "Show me the configuration section of pocket_live.py" |
| Update to latest version | "Run: cd ~/Desktop/Trading && git pull" |
| Check if bot is set up correctly | "Run: cd ~/Desktop/Trading && source venv/bin/activate && python3 -c 'import yfinance; import playwright; print(\"All good\")'" |

---

## Support

If something isn't working, paste the error message into Claude Code and ask it to fix it. Claude Code has full context of this project and can diagnose and resolve most issues.
