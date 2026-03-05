#!/usr/bin/env python3
"""
Pocket Option Live Trading Bot - Divine Formula (7 Second)
Syncs to the platform's 5-minute candle countdown.
Collects 6 price samples during the candle, then fires trade at 8s remaining.

Usage:
    cd ~/Desktop/Trading && source venv/bin/activate
    python3 -u pocket_live.py
"""

import time
import datetime
import warnings
from typing import Dict, Optional

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

from playwright.sync_api import sync_playwright, Page

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — change these as needed
# ═══════════════════════════════════════════════════════════════
EMAIL = "hello@no9.io"
PASSWORD = "Faze2501-"
DEMO_MODE = True          # True = demo, False = real account
ASSET = "EUR/USD OTC"     # Change to any asset the platform supports
TRADE_AMOUNT = 1          # Dollars per trade
TRADE_EXPIRY = 7          # Seconds (the 7-second divine formula)
CANDLE_SECONDS = 300      # 5-minute candle = 300 seconds
TRADE_AT_REMAINING = 8    # Place trade when this many seconds left

TRADE_ON_CAUTION = False   # True = trade even with yellow warnings

# Price sample schedule: label -> seconds remaining on candle countdown
SAMPLES = {
    'B1': 150,  # 2:30 remaining
    'B2': 105,  # 1:45 remaining
    'B3': 60,   # 1:00 remaining
    'D1': 45,   # 0:45 remaining
    'D2': 30,   # 0:30 remaining
    'D3': 12,   # 0:12 remaining (TRIGGER — analysis runs here)
}


# ═══════════════════════════════════════════════════════════════
# 7-SECOND ENTRY CONFIRMATION SYSTEM
# From: EURUSD_7sec_Checklist.html
# ═══════════════════════════════════════════════════════════════

def _sign(x):
    return (x > 0) - (x < 0)


def compute_signal(B1, B2, B3, D1, D2, D3):
    """Primary signal with skip filters, decel trap reversal, and momentum."""
    all_p = [B1, B2, B3, D1, D2, D3]
    avg = sum(all_p) / 6
    hi, lo = max(all_p), min(all_p)
    rng = hi - lo + 0.00001

    # Skip filters
    if (hi - lo) < 0.0001:
        return "SKIP"
    if abs(D3-avg) < 0.08*rng and abs(D3-D2) < 0.12*rng and abs(D2-D1) < 0.12*rng:
        return "SKIP"
    if _sign(D3-D2) != _sign(D2-D1) and abs(D3-D2) > 0.75*rng:
        return "SKIP"

    # Decel trap reversal
    pos_d3 = (D3 - lo) / rng
    if D3 > avg and (D3-D2) < 0.1*rng and (D2-D1) > 0.3*rng and pos_d3 > 0.75:
        return "SELL"
    if D3 < avg and (D2-D3) < 0.1*rng and (D1-D2) > 0.3*rng and (hi-D3)/rng > 0.75:
        return "BUY"

    # Strong momentum
    early_avg = (B1 + B2 + B3) / 3
    weighted = 0.5*D3 + 0.3*D2 + 0.2*D1
    if weighted > early_avg and D3 > avg and (D3-D2) > 0.14*rng and pos_d3 > 0.58:
        return "BUY"
    if weighted < early_avg and D3 < avg and (D2-D3) > 0.14*rng and (hi-D3)/rng > 0.58:
        return "SELL"

    # Fallback
    return "BUY" if D3 > avg else "SELL"


def check_confirmations(B1, B2, B3, D1, D2, D3):
    """5 confirmation checks. Returns list of (name, status, message).
    status: 'good', 'warn', or 'bad'."""
    all_p = [B1, B2, B3, D1, D2, D3]
    hi, lo = max(all_p), min(all_p)
    rng = hi - lo + 0.00001
    results = []

    # 1. Momentum Continuation
    if   D3 > D2 and D2 > D1: results.append(("Momentum",  "good", "STRONG UP"))
    elif D3 < D2 and D2 < D1: results.append(("Momentum",  "good", "STRONG DOWN"))
    elif D3 > D2 and D2 < D1: results.append(("Momentum",  "warn", "SHIFT — DIP THEN UP"))
    elif D3 < D2 and D2 > D1: results.append(("Momentum",  "bad",  "DECEL TRAP"))
    else:                      results.append(("Momentum",  "warn", "MIXED"))

    # 2. Deceleration Ratio
    d21 = abs(D2 - D1)
    d32 = abs(D3 - D2)
    if d21 < 0.000001:
        results.append(("Decel Ratio", "warn", "FLAT D1→D2"))
    else:
        ratio = d32 / d21
        if   ratio >= 0.8: results.append(("Decel Ratio", "good", f"ACCEL {ratio*100:.0f}%"))
        elif ratio >= 0.4: results.append(("Decel Ratio", "warn", f"SLOWING {ratio*100:.0f}%"))
        else:              results.append(("Decel Ratio", "bad",  f"DECEL {ratio*100:.0f}%"))

    # 3. Position Danger Zone
    pos = (D3 - lo) / rng
    if   pos > 0.92: results.append(("Position", "bad",  f"EXTREME HIGH {pos*100:.1f}%"))
    elif pos < 0.08: results.append(("Position", "bad",  f"EXTREME LOW {pos*100:.1f}%"))
    elif pos >= 0.55: results.append(("Position", "good", f"UPPER {pos*100:.1f}%"))
    elif pos <= 0.45: results.append(("Position", "good", f"LOWER {pos*100:.1f}%"))
    else:             results.append(("Position", "warn", f"MID {pos*100:.1f}%"))

    # 4. Trend Consistency (5 steps: B1→B2→B3→D1→D2→D3)
    steps = (_sign(B2-B1) + _sign(B3-B2) + _sign(D1-B3)
             + _sign(D2-D1) + _sign(D3-D2))
    abs_steps = abs(steps)
    if   abs_steps >= 4: results.append(("Consistency", "good", f"{abs_steps}/5 ALIGNED"))
    elif abs_steps >= 2: results.append(("Consistency", "warn", f"{abs_steps}/5 WEAK"))
    else:                results.append(("Consistency", "bad",  f"{abs_steps}/5 CHOPPY"))

    # 5. Range Quality
    pure_rng = hi - lo
    pips = pure_rng * 100000
    if   pure_rng >= 0.0008: results.append(("Range", "good", f"STRONG {pips:.1f}p"))
    elif pure_rng >= 0.0003: results.append(("Range", "good", f"ADEQUATE {pips:.1f}p"))
    elif pure_rng >= 0.0001: results.append(("Range", "warn", f"THIN {pips:.1f}p"))
    else:                    results.append(("Range", "bad",  f"MICRO {pips:.1f}p"))

    return results


def run_analysis(prices: Dict[str, float]) -> dict:
    B1, B2, B3 = prices['B1'], prices['B2'], prices['B3']
    D1, D2, D3 = prices['D1'], prices['D2'], prices['D3']

    signal = compute_signal(B1, B2, B3, D1, D2, D3)
    confirms = check_confirmations(B1, B2, B3, D1, D2, D3)

    has_red  = any(c[1] == "bad"  for c in confirms)
    has_warn = any(c[1] == "warn" for c in confirms)

    if signal == "SKIP":
        verdict = "SKIP"
    elif has_red:
        verdict = "NO_ENTRY"
    elif has_warn:
        verdict = "CAUTION"
    else:
        verdict = signal   # BUY or SELL — all clear

    return {
        'signal': signal,
        'confirms': confirms,
        'verdict': verdict,
        'has_red': has_red,
        'has_warn': has_warn,
    }


# ═══════════════════════════════════════════════════════════════
# BROWSER CONTROL
# ═══════════════════════════════════════════════════════════════

def login(page: Page):
    url = ("https://pocketoption.com/en/cabinet/demo-quick-high-low/"
           if DEMO_MODE else
           "https://pocketoption.com/en/cabinet/quick-high-low/")
    print("[LOGIN] Opening Pocket Option...")
    page.goto("https://pocketoption.com/en/login", wait_until="domcontentloaded")
    time.sleep(3)

    if "cabinet" in page.url:
        print("[LOGIN] Already logged in")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(5)
        dismiss_popups(page)
        return

    print("[LOGIN] Signing in...")
    page.fill('input[name="email"], input[type="email"]', EMAIL)
    page.fill('input[name="password"], input[type="password"]', PASSWORD)
    page.click('button:has-text("Sign In")')
    page.wait_for_url("**/cabinet/**", timeout=30000)
    print("[LOGIN] Success! Loading trading page...")
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(5)
    dismiss_popups(page)
    print("[LOGIN] Ready")


def dismiss_popups(page: Page):
    time.sleep(2)
    for sel in ['text="Continue to accumulate bonus"', 'text="Close"',
                '[class*="modal"] [class*="close"]', '[class*="popup"] [class*="close"]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1000):
                el.click()
                time.sleep(0.5)
        except Exception:
            pass


def set_expiry(page: Page, seconds: int):
    """Set the trade expiry time via the platform's HH:MM:SS modal."""
    try:
        modal_sel = '.expiration-inputs-list-modal'

        # Open the expiry modal if not already visible
        if not page.locator(modal_sel).is_visible():
            page.locator('[class*="block-expiration"]').first.click()
            time.sleep(0.5)

        # The modal has 3 rows: hours, minutes, seconds — each with an input
        inputs = page.locator(f'{modal_sel} .input-field-wrapper input')
        if inputs.count() != 3:
            print(f"[SETUP] Expected 3 expiry inputs, found {inputs.count()} — set to {seconds}s manually")
            return

        hrs = seconds // 3600
        mins = (seconds % 3600) // 60
        secs = seconds % 60

        for i, val in enumerate([f"{hrs:02d}", f"{mins:02d}", f"{secs:02d}"]):
            inp = inputs.nth(i)
            inp.click(click_count=3)   # select all text
            page.keyboard.type(val)    # real keystrokes
            time.sleep(0.1)

        # Close modal
        page.keyboard.press('Escape')
        time.sleep(0.3)
        print(f"[SETUP] Expiry set to {seconds}s")
    except Exception as e:
        print(f"[SETUP] Could not auto-set expiry ({e}) — set to {seconds}s manually")


def set_amount(page: Page, amount: int):
    try:
        page.evaluate(f"""() => {{
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {{
                if (inp.value && !isNaN(inp.value) && parseInt(inp.value) <= 50000) {{
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    nativeSetter.call(inp, '{amount}');
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return;
                }}
            }}
        }}""")
        print(f"[SETUP] Amount set to ${amount}")
    except Exception:
        print(f"[SETUP] Could not auto-set amount - please set to ${amount} manually")


def click_buy(page: Page):
    start = time.time()
    page.locator('text="Buy"').first.click()
    return (time.time() - start) * 1000

def click_sell(page: Page):
    start = time.time()
    page.locator('text="Sell"').first.click()
    return (time.time() - start) * 1000


def get_price_yf() -> Optional[float]:
    """Get latest EUR/USD price from yfinance."""
    try:
        import yfinance as yf
        d = yf.Ticker("EURUSD=X").history(period="1d", interval="1m")
        if not d.empty:
            return float(d['Close'].iloc[-1])
    except Exception:
        pass
    return None


def get_prices_yf_batch() -> list:
    """Get last 10 one-minute closes from yfinance."""
    try:
        import yfinance as yf
        d = yf.Ticker("EURUSD=X").history(period="1d", interval="1m")
        if not d.empty and len(d) >= 10:
            return [float(x) for x in d['Close'].iloc[-10:].tolist()]
    except Exception:
        pass
    return []


# ═══════════════════════════════════════════════════════════════
# CANDLE SYNC — align to platform's 5-minute candle
# ═══════════════════════════════════════════════════════════════

def next_candle_end() -> datetime.datetime:
    """Calculate when the current 5-min candle ends (aligned to :00, :05, :10...)."""
    now = datetime.datetime.now()
    minute = now.minute
    next_5 = ((minute // 5) + 1) * 5
    candle_end = now.replace(second=0, microsecond=0)
    if next_5 >= 60:
        candle_end = candle_end.replace(minute=0) + datetime.timedelta(hours=1)
    else:
        candle_end = candle_end.replace(minute=next_5)
    return candle_end


def seconds_remaining(candle_end: datetime.datetime) -> float:
    return (candle_end - datetime.datetime.now()).total_seconds()


def wait_until_remaining(candle_end: datetime.datetime, target_secs: float):
    """Sleep until the candle countdown reaches target_secs remaining."""
    while True:
        rem = seconds_remaining(candle_end)
        if rem <= target_secs:
            return rem
        # Sleep most of the wait, then poll tightly
        wait = rem - target_secs
        if wait > 1:
            time.sleep(wait - 0.5)
        else:
            time.sleep(0.01)


# ═══════════════════════════════════════════════════════════════
# MAIN CANDLE LOOP
# ═══════════════════════════════════════════════════════════════

def run_candle_cycle(page: Page):
    """
    One full candle cycle:
      1. Sample prices at B1(2:30), B2(1:45), B3(1:00), D1(45s), D2(30s), D3(12s)
      2. Run 5-confirmation analysis at D3 (12s remaining)
      3. Place trade at 8s remaining if all checks pass
    """
    candle_end = next_candle_end()
    rem = seconds_remaining(candle_end)

    print(f"\n{'='*60}")
    print(f"  CANDLE CYCLE")
    print(f"  Candle ends: {candle_end.strftime('%H:%M:%S')}  ({rem:.0f}s remaining)")
    print(f"{'='*60}")

    # If we're already past the B1 sample point (105s remaining),
    # skip to next candle
    if rem < SAMPLES['D3']:
        print(f"[SKIP] Only {rem:.0f}s left — too late for this candle. Waiting for next...")
        return {'result': None, 'candle_end': candle_end}

    prices = {}
    sorted_samples = sorted(SAMPLES.items(), key=lambda x: x[1], reverse=True)

    # Pre-fetch batch prices from yfinance once (for fallback)
    print("[PREFETCH] Loading yfinance prices...")
    t0 = time.time()
    yf_prices = get_prices_yf_batch()
    print(f"[PREFETCH] Got {len(yf_prices)} bars in {(time.time()-t0)*1000:.0f}ms")

    # Collect each sample at the right time
    for label, target_rem in sorted_samples:
        current_rem = seconds_remaining(candle_end)

        if current_rem > target_rem:
            # Wait for the right moment
            print(f"[WAIT] {label} at {target_rem}s remaining (in {current_rem - target_rem:.0f}s)...")
            wait_until_remaining(candle_end, target_rem)

        # Sample price
        if current_rem >= target_rem - 2:
            # We're at the right time — get live price
            price = get_price_yf()
            if price:
                prices[label] = price
                print(f"[SAMPLE] {label} = {price:.5f}  (at {seconds_remaining(candle_end):.0f}s remaining)")
            elif yf_prices:
                # Use pre-fetched data
                idx = {'B1': -6, 'B2': -5, 'B3': -4, 'D1': -3, 'D2': -2, 'D3': -1}
                prices[label] = yf_prices[idx[label]]
                print(f"[SAMPLE] {label} = {prices[label]:.5f}  (prefetched)")
        else:
            # Missed this sample, use prefetch
            if yf_prices:
                idx = {'B1': -6, 'B2': -5, 'B3': -4, 'D1': -3, 'D2': -2, 'D3': -1}
                prices[label] = yf_prices[idx[label]]
                print(f"[SAMPLE] {label} = {prices[label]:.5f}  (prefetched, sample window passed)")

    if len(prices) < 6:
        print(f"[ERROR] Only got {len(prices)}/6 prices — skipping trade")
        return {'result': None, 'candle_end': candle_end}

    # ── Run analysis ────────────────────────────────────
    t0 = time.time()
    result = run_analysis(prices)
    t_analysis = (time.time() - t0) * 1000

    signal  = result['signal']
    verdict = result['verdict']

    print(f"\n[ANALYSIS] {t_analysis:.0f}ms")
    print(f"  Signal: {signal}")
    for name, status, msg in result['confirms']:
        icon = "✓" if status == "good" else ("!" if status == "warn" else "✗")
        print(f"  [{icon}] {name}: {msg}")
    print(f"  VERDICT: {verdict}")

    # ── Should we trade? ─────────────────────────────
    if verdict == "SKIP":
        print("[SKIP] Formula filtered — unsafe candle")
        return {'result': result, 'candle_end': candle_end}
    if verdict == "NO_ENTRY":
        print("[SKIP] Red flag in confirmations — no trade")
        return {'result': result, 'candle_end': candle_end}
    if verdict == "CAUTION" and not TRADE_ON_CAUTION:
        print("[SKIP] Weak confirmations — skipping (set TRADE_ON_CAUTION=True to override)")
        return {'result': result, 'candle_end': candle_end}

    direction = signal if verdict in ("BUY", "SELL") else signal

    # ── Wait for trade entry point: 8s remaining ───────
    rem = seconds_remaining(candle_end)
    if rem > TRADE_AT_REMAINING:
        print(f"\n[WAIT] Trade fires at {TRADE_AT_REMAINING}s remaining (in {rem - TRADE_AT_REMAINING:.0f}s)...")
        wait_until_remaining(candle_end, TRADE_AT_REMAINING)

    # ── FIRE TRADE ──────────────────────────────────────
    rem_at_fire = seconds_remaining(candle_end)

    if direction == "BUY":
        click_ms = click_buy(page)
    else:
        click_ms = click_sell(page)

    print(f"\n  >>> {direction} TRADE PLACED <<<")
    print(f"  Fired at:    {rem_at_fire:.1f}s remaining")
    print(f"  Click time:  {click_ms:.0f}ms")
    print(f"  Expiry:      {TRADE_EXPIRY}s")
    print(f"  Expires at:  ~{rem_at_fire - TRADE_EXPIRY:.1f}s remaining")

    return {'result': result, 'candle_end': candle_end}


def main():
    now = datetime.datetime.now()
    print("=" * 60)
    print("  POCKET BOT - 7sec Entry Confirmation")
    print(f"  Account: {'DEMO' if DEMO_MODE else 'REAL'}")
    print(f"  Asset:   {ASSET}")
    print(f"  Amount:  ${TRADE_AMOUNT}")
    print(f"  Expiry:  {TRADE_EXPIRY}s")
    print(f"  Candle:  {CANDLE_SECONDS//60}min")
    print(f"  Trade at: {TRADE_AT_REMAINING}s remaining")
    print(f"  Time:    {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Day:     {'Weekend' if now.weekday() >= 5 else 'Weekday'}")
    print("=" * 60)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=0)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        login(page)
        set_amount(page, TRADE_AMOUNT)
        set_expiry(page, TRADE_EXPIRY)

        print("\n[READY] Bot is running. Ctrl+C to stop.")
        print(f"[READY] Will trade every 5-min candle at {TRADE_AT_REMAINING}s remaining.\n")

        try:
            while True:
                cycle = run_candle_cycle(page)
                # Wait past candle end before starting next cycle
                rem = seconds_remaining(cycle['candle_end'])
                if rem > 0:
                    print(f"\n[WAIT] Candle closes in {rem:.0f}s — waiting for next cycle...")
                    time.sleep(rem + 2)
                else:
                    time.sleep(2)
        except KeyboardInterrupt:
            print("\n[STOP] Stopped by user")

        browser.close()


if __name__ == "__main__":
    main()
