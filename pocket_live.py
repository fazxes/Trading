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
import statistics
import sys
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

# Price sample schedule: label -> seconds remaining on candle countdown
SAMPLES = {
    'B1': 105,  # 1:45 remaining
    'B2': 58,   # 0:58 remaining
    'B3': 43,   # 0:43 remaining
    'D1': 30,   # 0:30 remaining
    'D2': 26,   # 0:26 remaining
    'D3': 22,   # 0:22 remaining
}


# ═══════════════════════════════════════════════════════════════
# DIVINE FORMULA — Sheet3 + Advanced + Session
# ═══════════════════════════════════════════════════════════════

def calc_volatility(B1, B3, D1, D3):
    ab, ad = abs(B1 - B3), abs(D1 - D3)
    if ab >= 0.001 and ad >= 0.001: return "HIGH"
    if 0.0004 <= ab < 0.001 and 0.0004 <= ad < 0.001: return "MEDIUM"
    return "LOW"

def s3_direction(B4, B1, B2, B3, D1, D2, D3, vol):
    if vol == "HIGH" and B4 > B3 > B2 > B1 and D3 > D2 > D1: return "BUY"
    if vol == "LOW" and B4 < B3 < B2 < B1 and D3 < D2 < D1: return "SELL"
    if vol == "STABLE" and abs(B4-B3) < 0.0001 and abs(D3-D2) < 0.0001: return "BUY"
    if vol == "STABLE" and B4 > B3 and D3 > D2: return "BUY"
    return "SELL"

def s3_strength(B1, B2, B3, D1, D2, D3):
    if D1 > D2 > D3 and B1 > B2 > B3 and abs(D1-D3) > 0.00015 and abs(B1-B3) > 0.00015: return "SELL STRONG"
    if D1 < D2 < D3 and B1 < B2 < B3 and abs(D1-D3) > 0.00015 and abs(B1-B3) > 0.00015: return "BUY STRONG"
    if D1 > D2 and B1 > B2: return "SELL STRONG"
    if D1 < D2 and B1 < B2: return "BUY STRONG"
    return "SELL STRONG"

def s3_confirm(B4, B1, B2, B3, D1, D2, D3):
    return "BUY" if B4 > B3 > B2 > B1 and D3 > D2 > D1 else "SELL"

def s3_safety(B4, B1, B2, B3):
    if abs(B4-B3) > 0.0005 and abs(B3-B2) > 0.0005 and abs(B2-B1) > 0.0005:
        return "WAIT"
    return "OK"

def session_direction(B4, B1, B2, B3, D1, D2, D3, weekend):
    hour = datetime.datetime.now().hour
    up = B4 > B3 > B2 and D3 > D2 > D1
    if weekend:
        if 8 <= hour < 15: return "BUY" if up and abs(B4-B1) > 0.0002 else "SELL"
        if 15 <= hour < 18: return "BUY" if up and abs(B4-B2) > 0.00025 else "SELL"
        if 18 <= hour < 24: return "BUY" if up and abs(B4-B2) > 0.0002 else "SELL"
        return "SELL" if B4 < B3 < B2 and D3 < D2 < D1 else "BUY"
    else:
        if 8 <= hour < 15: return "BUY" if up and abs(B4-B1) > 0.0002 else "SELL"
        if 15 <= hour < 18: return "BUY" if up else "SELL"
        if 18 <= hour < 23: return "BUY" if up and abs(B4-B1) > 0.00025 else "SELL"
        return "BUY" if up and abs(B4-B3) < 0.00035 else "SELL"

def advanced_signal(B1, B2, B3, B4, D1, D2, D3):
    avg_b = statistics.mean([B1, B2, B3])
    std_b = statistics.pstdev([B1, B2, B3])
    avg_d = statistics.mean([D1, D2, D3])
    E1 = (D3-D2) + (D2-D1)
    E2 = statistics.mean([abs(D3-D2), abs(D2-D1)])
    E3 = (max(0, D3-D2) + max(0, D2-D1)) / 2
    E4 = ((abs(D3-D2) if D3<D2 else 0) + (abs(D2-D1) if D2<D1 else 0)) / 2
    E5 = 100 - (100 / (1 + E3/max(0.0001, E4)))
    E6 = abs(D3-D2) / max(0.0001, E2)
    E7 = abs(D3-D2) / max(0.0001, abs(D2-D1))
    E8 = abs((D3-B4)-E1) / max(0.0001, statistics.pstdev([D3,D2,D1]))
    E9 = statistics.mean([abs(B1-B2), abs(B2-B3)]) * 1.5
    E10 = (D3-avg_b) / max(0.0001, std_b)
    E11 = (D3-D2) / max(0.0001, statistics.mean([abs(B1-B2), abs(B2-B3), abs(D2-D1)]))
    E12 = min(1, abs(E10)*E6/max(0.0001, E8))
    if (E1>=E2*E9 and D3>B4 and D3>max(B1,B2,B3) and E5<65 and avg_d>avg_b
            and D3>(avg_b+0.5*std_b) and E6>0.2 and E8<2 and E10>0.03 and E11>0.4 and E12>0.8):
        return "HARD BUY"
    if (E1<=E2*E9*-1 and D3<B4 and D3<min(B1,B2,B3) and E5>35 and avg_d<avg_b
            and D3<(avg_b-0.5*std_b) and E6>0.2 and E8<1.5 and E10<-0.15 and E11<-0.5 and E12>0.8):
        return "HARD SELL"
    if (E1>=E2*E9*0.5 and D3>B4 and avg_d>avg_b and D3>(avg_b-0.5*std_b)
            and 0.15<E7<6 and E8<1.8 and E10>0.02 and E11>0.3 and E12>0.7):
        return "SOFT BUY"
    if (E1<=E2*E9*-0.5 and D3<B4 and avg_d<avg_b and D3<(avg_b+0.5*std_b)
            and 0.15<E7<6 and E8<1.3 and E10<-0.1 and E11<-0.4 and E12>0.7):
        return "SOFT SELL"
    if D3>=B4-0.00003 and E8<1.2 and E10>=-0.005 and E11>0.1 and E12>0.6:
        return "WEAK BUY"
    return "WEAK SELL"

def run_analysis(prices: Dict[str, float]) -> dict:
    B1, B2, B3 = prices['B1'], prices['B2'], prices['B3']
    D1, D2, D3 = prices['D1'], prices['D2'], prices['D3']
    B4 = statistics.mean([B1, B2, B3, D1, D2, D3])
    B4w = (B1*1 + B2*1.5 + B3*2 + D1*1 + D2*1.2 + D3*1.2) / 7.9
    vol = calc_volatility(B1, B3, D1, D3)
    weekend = datetime.datetime.now().weekday() >= 5

    votes = {
        'Direction': s3_direction(B4, B1, B2, B3, D1, D2, D3, vol),
        'Confirm':   s3_confirm(B4, B1, B2, B3, D1, D2, D3),
        'Strength':  "BUY" if "BUY" in s3_strength(B1, B2, B3, D1, D2, D3) else "SELL",
        'Session':   session_direction(B4, B1, B2, B3, D1, D2, D3, weekend),
        'Advanced':  "BUY" if "BUY" in advanced_signal(B1, B2, B3, B4w, D1, D2, D3) else "SELL",
    }
    buy_count = sum(1 for v in votes.values() if v == "BUY")
    consensus = "BUY" if buy_count > len(votes) / 2 else "SELL"
    agree = buy_count if consensus == "BUY" else len(votes) - buy_count
    safety = s3_safety(B4, B1, B2, B3)

    return {
        'consensus': consensus, 'votes': votes, 'agree': agree,
        'total': len(votes), 'safety': safety, 'volatility': vol,
        'advanced': advanced_signal(B1, B2, B3, B4w, D1, D2, D3),
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
      1. Wait and sample prices at B1(1:45), B2(58s), B3(43s), D1(30s), D2(26s), D3(22s)
      2. Run analysis at ~14s remaining
      3. Place trade at 8s remaining
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

    consensus = result['consensus']
    print(f"\n[ANALYSIS] {t_analysis:.0f}ms")
    print(f"  Volatility: {result['volatility']}")
    print(f"  Advanced:   {result['advanced']}")
    for name, vote in result['votes'].items():
        m = "+" if vote == consensus else "-"
        print(f"  [{m}] {name}: {vote}")
    print(f"  CONSENSUS: {consensus} ({result['agree']}/{result['total']})")
    print(f"  Safety:    {result['safety']}")

    if result['safety'] == "WAIT":
        print("[SKIP] High volatility — no trade this candle")
        return {'result': result, 'candle_end': candle_end}

    # ── Wait for trade entry point: 8s remaining ───────
    rem = seconds_remaining(candle_end)
    if rem > TRADE_AT_REMAINING:
        print(f"\n[WAIT] Trade fires at {TRADE_AT_REMAINING}s remaining (in {rem - TRADE_AT_REMAINING:.0f}s)...")
        wait_until_remaining(candle_end, TRADE_AT_REMAINING)

    # ── FIRE TRADE ──────────────────────────────────────
    t_start = time.time()
    rem_at_fire = seconds_remaining(candle_end)

    if consensus == "BUY":
        click_ms = click_buy(page)
    else:
        click_ms = click_sell(page)

    t_total = (time.time() - t_start) * 1000

    print(f"\n  >>> {consensus} TRADE PLACED <<<")
    print(f"  Fired at:    {rem_at_fire:.1f}s remaining")
    print(f"  Click time:  {click_ms:.0f}ms")
    print(f"  Expiry:      {TRADE_EXPIRY}s")
    print(f"  Expires at:  ~{rem_at_fire - TRADE_EXPIRY:.1f}s remaining")

    return {'result': result, 'candle_end': candle_end}


def main():
    now = datetime.datetime.now()
    print("=" * 60)
    print("  POCKET BOT - Divine Formula (7 Second)")
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
