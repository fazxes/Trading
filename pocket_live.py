#!/usr/bin/env python3
"""
Pocket Option Live Trading Bot — Deep Signal Engine v6
Syncs to the platform's 5-minute candle countdown (5:00 → 0:00).
Collects 288 prices (1/sec from 5:00 to 0:12), runs 8-component scoring,
fires trade at 0:08 remaining with 7-second expiry (expires at 0:01).

Usage:
    cd ~/Desktop/Trading && source venv/bin/activate
    python3 -u pocket_live.py
"""

import time
import datetime
import json
import threading
import warnings
from typing import List, Optional

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

from playwright.sync_api import sync_playwright, Page


# ═══════════════════════════════════════════════════════════════
# LIVE PRICE VIA WEBSOCKET
# Pocket Option streams ticks as: [["EURUSD_otc", timestamp, price]]
# ═══════════════════════════════════════════════════════════════

_latest_price = {'value': None, 'ts': 0.0}
_last_update_local = {'t': 0.0}
_price_lock = threading.Lock()


def _on_ws_message(payload):
    """Parse WebSocket frame for EURUSD_otc price ticks."""
    try:
        raw = payload if isinstance(payload, str) else payload.decode('utf-8', errors='ignore')
        # Match the tick format: [["EURUSD_otc", timestamp, price]]
        if 'EURUSD_otc' not in raw:
            return
        data = json.loads(raw)
        if isinstance(data, list) and len(data) > 0:
            for tick in data:
                if isinstance(tick, list) and len(tick) >= 3 and tick[0] == 'EURUSD_otc':
                    price = float(tick[2])
                    ts = float(tick[1])
                    with _price_lock:
                        if ts >= _latest_price['ts']:
                            _latest_price['value'] = price
                            _latest_price['ts'] = ts
                            _last_update_local['t'] = time.time()
    except (json.JSONDecodeError, ValueError, TypeError, IndexError):
        pass


def setup_price_feed(page: Page):
    """Attach WebSocket listener to capture live price ticks from Pocket Option."""
    def on_ws(ws):
        ws.on("framereceived", lambda payload: _on_ws_message(payload))
    page.on("websocket", on_ws)
    print("[PRICE] WebSocket price feed listener attached")

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — change these as needed
# ═══════════════════════════════════════════════════════════════
EMAIL = "hello@no9.io"
PASSWORD = "Faze2501-"
DEMO_MODE = True          # True = demo, False = real account
ASSET = "EUR/USD OTC"     # Change to any asset the platform supports
TRADE_AMOUNT = 1          # Dollars per trade
TRADE_EXPIRY = 7          # Seconds — trade expires at 0:01 remaining
CANDLE_SECONDS = 300      # 5-minute candle = 300 seconds
TRADE_AT_REMAINING = 8    # Place trade at 0:08 remaining

TRADE_ON_CAUTION = False  # True = trade on borderline scores (35-49%)
MIN_PAYOUT = 80           # Minimum payout % — bot goes on standby below this

# Price collection: 1 price per second throughout the candle
COLLECT_UNTIL = 12        # Stop collecting at 0:12 remaining (trigger point)
MIN_PRICES = 120          # Minimum prices needed for reliable analysis


# ═══════════════════════════════════════════════════════════════
# DEEP SIGNAL ENGINE v6
# Ported 1:1 from: EURUSD_DeepSignal_v6_300sec.html
# 288 prices → 8-component scoring → BUY / SELL / SKIP / BLOCK
# ═══════════════════════════════════════════════════════════════

PIP = 0.0001


def _detect_spikes(pip_changes: List[float], n: int):
    """Detect fake spikes: single-second move >2.5x rolling std that reverses within 2 seconds."""
    spikes = [False] * n
    spike_dir = [0] * n
    for i in range(5, n - 2):
        window = pip_changes[max(0, i - 10):i]
        mean = sum(window) / len(window)
        std = (sum((x - mean) ** 2 for x in window) / len(window)) ** 0.5 or 0.01
        move = pip_changes[i]
        if abs(move) > max(2.5 * std, 1.5):
            reverse_check = pip_changes[i + 1] + (pip_changes[i + 2] if i + 2 < n else 0)
            if ((reverse_check > 0) != (move > 0)) and abs(reverse_check) > abs(move) * 0.4:
                spikes[i] = True
                spike_dir[i] = 1 if move > 0 else -1
    return spikes, spike_dir


def _detect_reversals(pip_changes: List[float], spikes: List[bool], n: int):
    """Detect reversals: 5+ seconds in one direction then 3+ seconds switching."""
    reversals = [False] * n
    for i in range(8, n - 3):
        if spikes[i]:
            continue
        prev_sum = sum(pip_changes[i - 5:i])
        next_sum = sum(pip_changes[i:i + 3])
        if abs(prev_sum) > 2 and abs(next_sum) > 1.5 and ((prev_sum > 0) != (next_sum > 0)):
            reversals[i] = True
    return reversals


def run_deep_signal(prices: List[float]) -> dict:
    """
    Deep Signal Engine v6 — 8-component scoring system.
    Takes array of prices (1 per second, from candle open to 0:12 remaining).
    Returns dict with signal, score, verdict, direction, breakdown.
    """
    n = len(prices)

    # ── Second-by-second pip changes ──────────────────────
    pip_changes = [0.0]
    for i in range(1, n):
        pip_changes.append((prices[i] - prices[i - 1]) / PIP)

    # ── Spike & reversal detection ────────────────────────
    spikes, spike_dir = _detect_spikes(pip_changes, n)
    reversals = _detect_reversals(pip_changes, spikes, n)

    # ── Key metrics ───────────────────────────────────────
    open_price = prices[0]
    close_price = prices[-1]
    high = max(prices)
    low = min(prices)
    range_pips = (high - low) / PIP
    net_pips = (close_price - open_price) / PIP

    # Spike-filtered net direction
    filt_net_up = 0.0
    filt_net_dn = 0.0
    for i in range(1, n):
        if spikes[i]:
            continue
        if pip_changes[i] > 0:
            filt_net_up += pip_changes[i]
        else:
            filt_net_dn += abs(pip_changes[i])

    if filt_net_up > filt_net_dn:
        filtered_direction = 'BUY'
    elif filt_net_dn > filt_net_up:
        filtered_direction = 'SELL'
    else:
        filtered_direction = 'FLAT'
    dir_strength = abs(filt_net_up - filt_net_dn) / (filt_net_up + filt_net_dn + 0.001)

    # Last 30 seconds momentum
    last30 = prices[max(0, n - 30):]
    last30_net = (last30[-1] - last30[0]) / PIP

    # Last 10 seconds momentum
    last10 = prices[max(0, n - 10):]
    last10_net = (last10[-1] - last10[0]) / PIP

    # Last 5 seconds average pip per second
    last5_changes = pip_changes[max(0, n - 5):]
    last5_avg = sum(abs(c) for c in last5_changes) / len(last5_changes)

    # Momentum consistency: % of seconds in signal direction (excluding spikes)
    consistent_seconds = 0
    total_non_spike = 0
    for i in range(1, n):
        if spikes[i]:
            continue
        total_non_spike += 1
        if filtered_direction == 'BUY' and pip_changes[i] > 0:
            consistent_seconds += 1
        if filtered_direction == 'SELL' and pip_changes[i] < 0:
            consistent_seconds += 1
    consistency = consistent_seconds / total_non_spike if total_non_spike > 0 else 0

    # Acceleration: last 30 seconds faster than first 30 seconds?
    first30 = prices[:30]
    first30_net = abs((first30[29] - first30[0]) / PIP) if len(first30) >= 30 else 0
    last30_abs = abs(last30_net)
    accelerating = last30_abs > first30_net

    # Recent reversal check: reversal in last 20 seconds?
    last_rev_idx = max((i for i in range(n) if reversals[i]), default=-1)
    recent_reversal = last_rev_idx >= n - 20 and last_rev_idx != -1

    # Recent spike check: fake spike in last 15 seconds?
    last_spike_idx = max((i for i in range(n) if spikes[i]), default=-1)
    recent_spike = last_spike_idx >= n - 15 and last_spike_idx != -1

    total_spikes = sum(spikes)
    total_reversals = sum(reversals)

    # ══════════════════════════════════════════════════════
    # SCORING SYSTEM (out of 100)
    # ══════════════════════════════════════════════════════
    score = 0
    breakdown = []

    # ① NET DIRECTION (max 20)
    if range_pips >= 2:
        s1 = round(min(dir_strength * 30, 20))
        s1_note = f"{filtered_direction} · {dir_strength * 100:.0f}% strength"
        s1_verdict = 'STRONG' if s1 >= 15 else 'MODERATE' if s1 >= 8 else 'WEAK'
    else:
        s1 = 0
        s1_note = 'Range too small (<2 pip)'
        s1_verdict = 'SKIP'
    score += s1
    breakdown.append(('① NET DIRECTION', s1_note, f'{s1}/20', s1_verdict))

    # ② LAST 30 SEC MOMENTUM (max 20)
    l30_aligned = ((filtered_direction == 'BUY' and last30_net > 0) or
                   (filtered_direction == 'SELL' and last30_net < 0))
    if l30_aligned:
        s2 = min(round(abs(last30_net) * 3), 20)
        s2_note = f"{'+' if last30_net > 0 else ''}{last30_net:.2f}p last 30s"
        s2_verdict = 'STRONG PUSH' if s2 >= 14 else 'ALIGNED'
    else:
        s2 = max(0, 5 - round(abs(last30_net)))
        s2_note = f"AGAINST signal · {last30_net:.2f}p"
        s2_verdict = 'WEAK'
    score += s2
    breakdown.append(('② LAST 30s MOMENTUM', s2_note, f'{s2}/20', s2_verdict))

    # ③ CONSISTENCY (max 15)
    s3 = round(consistency * 15)
    s3_note = f"{consistency * 100:.0f}% seconds aligned"
    s3_verdict = 'CONSISTENT' if consistency >= 0.65 else 'MIXED' if consistency >= 0.5 else 'NOISY'
    score += s3
    breakdown.append(('③ CONSISTENCY', s3_note, f'{s3}/15', s3_verdict))

    # ④ ACCELERATION (max 10)
    if accelerating:
        s4 = 10
        s4_note = f"Last 30s ({last30_abs:.1f}p) > First 30s ({first30_net:.1f}p)"
        s4_verdict = 'ACCELERATING'
    else:
        s4 = 3
        s4_note = f"Slowing · Last 30s ({last30_abs:.1f}p)"
        s4_verdict = 'DECELERATING'
    score += s4
    breakdown.append(('④ ACCELERATION', s4_note, f'{s4}/10', s4_verdict))

    # ⑤ RANGE SIZE (max 10)
    if range_pips >= 5:
        s5, s5_verdict = 10, 'EXCELLENT'
    elif range_pips >= 3:
        s5, s5_verdict = 7, 'GOOD'
    elif range_pips >= 2:
        s5, s5_verdict = 4, 'BORDERLINE'
    else:
        s5, s5_verdict = 0, 'TOO SMALL'
    s5_note = f"{range_pips:.2f} pips range"
    score += s5
    breakdown.append(('⑤ RANGE SIZE', s5_note, f'{s5}/10', s5_verdict))

    # ⑥ FAKE SPIKE PENALTY (max -15)
    if recent_spike:
        s6 = -15
        s6_note = f"Spike in last 15s ({n - last_spike_idx}s ago)"
        s6_verdict = 'DANGER'
    elif total_spikes > 3:
        s6 = -5
        s6_note = f"{total_spikes} spikes (noisy candle)"
        s6_verdict = 'CAUTION'
    else:
        s6 = 0
        s6_note = f"{total_spikes} spike(s) · none recent"
        s6_verdict = 'CLEAN'
    score += s6
    breakdown.append(('⑥ SPIKE PENALTY', s6_note, f'{s6}/0', s6_verdict))

    # ⑦ RECENT REVERSAL PENALTY (max -15)
    if recent_reversal:
        s7 = -15
        s7_note = 'Reversal in last 20s · flip risk HIGH'
        s7_verdict = 'HARD BLOCK'
    elif total_reversals > 2:
        s7 = -5
        s7_note = f"{total_reversals} reversals · choppy"
        s7_verdict = 'CAUTION'
    else:
        s7 = 0
        s7_note = f"{total_reversals} reversal(s) · none recent"
        s7_verdict = 'SAFE'
    score += s7
    breakdown.append(('⑦ REVERSAL PENALTY', s7_note, f'{s7}/0', s7_verdict))

    # ⑧ LAST 10 SEC ALIGNMENT (max 10)
    l10_aligned = ((filtered_direction == 'BUY' and last10_net > 0) or
                   (filtered_direction == 'SELL' and last10_net < 0))
    if l10_aligned:
        s8 = min(round(abs(last10_net) * 4), 10)
        s8_note = f"Last 10s: {'+' if last10_net > 0 else ''}{last10_net:.2f}p"
        s8_verdict = 'ALIGNED'
    else:
        s8 = 0
        s8_note = 'Last 10s going against signal'
        s8_verdict = 'MISALIGNED'
    score += s8
    breakdown.append(('⑧ LAST 10s ALIGNMENT', s8_note, f'{s8}/10', s8_verdict))

    # Clamp 0-100
    score = max(0, min(100, score))

    # ══════════════════════════════════════════════════════
    # FINAL VERDICT
    # ══════════════════════════════════════════════════════
    final_signal = filtered_direction

    if recent_reversal and range_pips >= 2:
        verdict = 'BLOCK'
        final_signal = 'BLOCK'
    elif score >= 50 and final_signal in ('BUY', 'SELL'):
        verdict = f'ENTER {final_signal}'
    elif score >= 35:
        verdict = 'BORDERLINE'
        final_signal = 'SKIP'
    else:
        verdict = 'SKIP'
        final_signal = 'SKIP'

    if range_pips < 2:
        verdict = 'SKIP · RANGE TOO SMALL'
        final_signal = 'SKIP'

    return {
        'signal': final_signal,            # BUY, SELL, SKIP, or BLOCK
        'verdict': verdict,                # Human-readable verdict
        'score': score,                    # 0-100 confidence
        'direction': filtered_direction,   # Raw detected direction (BUY/SELL/FLAT)
        'breakdown': breakdown,            # 8 scoring components
        'range_pips': range_pips,
        'net_pips': net_pips,
        'total_spikes': total_spikes,
        'total_reversals': total_reversals,
        'last30_net': last30_net,
        'last10_net': last10_net,
        'consistency': consistency,
        'accelerating': accelerating,
        'recent_spike': recent_spike,
        'recent_reversal': recent_reversal,
        'num_prices': n,
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


def get_live_price() -> Optional[float]:
    """Get the latest EUR/USD price from the WebSocket feed."""
    with _price_lock:
        price = _latest_price['value']
        local_age = time.time() - _last_update_local['t'] if _last_update_local['t'] > 0 else float('inf')
    # Price should be fresh (updated within last 10 seconds)
    if price and local_age < 10:
        return price
    return None


def get_payout(page: Page) -> Optional[int]:
    """Read the current payout % from the Pocket Option UI."""
    try:
        text = page.evaluate("""() => {
            // Look for payout percentage near the trading panel
            const els = document.querySelectorAll('[class*="percent"], [class*="payout"], [class*="profit"]');
            for (const el of els) {
                const m = el.textContent.match(/(\\d+)\\s*%/);
                if (m && parseInt(m[1]) >= 50 && parseInt(m[1]) <= 100) return m[1];
            }
            // Fallback: scan all elements containing "%" near trading area
            const all = document.querySelectorAll('span, div, p');
            for (const el of all) {
                const t = el.textContent.trim();
                const m = t.match(/^\\+?(\\d+)\\s*%$/);
                if (m && parseInt(m[1]) >= 50 && parseInt(m[1]) <= 100) return m[1];
            }
            return null;
        }""")
        return int(text) if text else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# CANDLE SYNC — align to platform's 5-minute candle
# Countdown: 5:00 → 4:59 → 4:58 → ... → 0:01 → 0:00
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


def fmt_countdown(secs: float) -> str:
    """Format seconds remaining as M:SS countdown (e.g. 4:59, 0:12)."""
    s = max(0, int(secs))
    return f"{s // 60}:{s % 60:02d}"


def playwright_sleep(page: Page, duration: float):
    """Sleep while keeping Playwright's event loop alive (processes WS frames).
    Uses page.wait_for_timeout which yields to the browser event loop."""
    if duration <= 0:
        return
    # Break into chunks so WS messages get processed regularly
    chunk = min(duration, 2.0)
    remaining = duration
    while remaining > 0:
        ms = int(min(chunk, remaining) * 1000)
        page.wait_for_timeout(ms)
        remaining -= chunk


def wait_until_remaining(candle_end: datetime.datetime, target_secs: float, page: Page = None):
    """Sleep until the candle countdown reaches target_secs remaining.
    If page is provided, uses Playwright-friendly sleep to keep WS alive."""
    while True:
        rem = seconds_remaining(candle_end)
        if rem <= target_secs:
            return rem
        wait = rem - target_secs
        if page:
            if wait > 1:
                playwright_sleep(page, min(wait - 0.5, 2.0))
            else:
                playwright_sleep(page, 0.05)
        else:
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
      1. Collect 1 price/sec from 5:00 down to 0:12 (288 prices)
      2. At 0:12 — stop collecting, run Deep Signal Engine (~4s analysis)
      3. At 0:08 — place trade if signal says BUY/SELL
      4. 7-second expiry — trade expires at 0:01 (1s before candle close)
    """
    candle_end = next_candle_end()
    rem = seconds_remaining(candle_end)

    # ── Check payout before doing anything ──────────────
    payout = get_payout(page)
    payout_str = f"{payout}%" if payout else "unknown"

    print(f"\n{'='*60}")
    print(f"  CANDLE CYCLE — Deep Signal Engine v6")
    print(f"  Candle ends: {candle_end.strftime('%H:%M:%S')}  ({fmt_countdown(rem)} remaining)")
    print(f"  Payout: {payout_str}")
    print(f"{'='*60}")

    if payout is not None and payout < MIN_PAYOUT:
        print(f"[STANDBY] Payout {payout}% < {MIN_PAYOUT}% — waiting for payout to be more than {MIN_PAYOUT}%")
        return {'result': None, 'candle_end': candle_end}

    # Need enough collection time (rem must be > COLLECT_UNTIL + MIN_PRICES)
    collection_time = rem - COLLECT_UNTIL
    if collection_time < MIN_PRICES:
        print(f"[SKIP] Only {collection_time:.0f}s of collection time — need {MIN_PRICES}s. "
              f"Waiting for next candle...")
        return {'result': None, 'candle_end': candle_end}

    # Verify WebSocket feed is alive before committing to this candle
    if get_live_price() is None:
        print("[SKIP] WebSocket price feed not active — cannot sample. Waiting for next candle...")
        return {'result': None, 'candle_end': candle_end}

    # ── Collect prices: 1 per second until 0:12 remaining ──
    # Each price labeled A1 (first second) through A288 (last second at 0:12)
    prices = []
    no_price_streak = 0
    last_log_count = 0
    next_sample_time = time.time()

    print(f"[COLLECT] Starting: A1 → A288 ({fmt_countdown(rem)} → {fmt_countdown(COLLECT_UNTIL)})")

    while seconds_remaining(candle_end) > COLLECT_UNTIL:
        price = get_live_price()
        if price:
            prices.append(price)
            no_price_streak = 0
        else:
            no_price_streak += 1
            if no_price_streak >= 5:
                print(f"[ABORT] WebSocket price lost for 5s during collection. Scrapping candle.")
                return {'result': None, 'candle_end': candle_end}

        # Progress log every 60 prices
        if len(prices) > 0 and len(prices) % 60 == 0 and len(prices) != last_log_count:
            r = seconds_remaining(candle_end)
            print(f"[COLLECT] A{len(prices)} · {len(prices)} prices · {fmt_countdown(r)} remaining · "
                  f"latest: {prices[-1]:.5f}")
            last_log_count = len(prices)

        # Wait until next 1-second sample point
        next_sample_time += 1.0
        wait = next_sample_time - time.time()
        if wait > 0:
            playwright_sleep(page, wait)

    # ── Collection complete ──────────────────────────────
    rem = seconds_remaining(candle_end)
    print(f"[COLLECT] Done — A1 to A{len(prices)} ({len(prices)} prices, at {fmt_countdown(rem)} remaining)")

    if len(prices) < 30:
        print(f"[SKIP] Only {len(prices)} prices — need at least 30. Scrapping candle.")
        return {'result': None, 'candle_end': candle_end}

    # ── Run Deep Signal Engine (~4 seconds to analyze) ───
    t0 = time.time()
    result = run_deep_signal(prices)
    t_analysis = (time.time() - t0) * 1000

    signal = result['signal']
    score = result['score']
    verdict = result['verdict']
    direction = result['direction']

    print(f"\n[ENGINE] Analyzed in {t_analysis:.0f}ms — {result['num_prices']} prices")
    print(f"  Direction: {direction} ({result['range_pips']:.1f} pip range)")
    print(f"  Score:     {score}%")
    for comp, note, sc, verd in result['breakdown']:
        print(f"    {comp}: {sc} — {note} [{verd}]")
    print(f"  VERDICT:   {verdict}")

    # ── Should we trade? ─────────────────────────────────
    if signal == 'BLOCK':
        print("[BLOCK] Reversal detected — DO NOT ENTER")
        return {'result': result, 'candle_end': candle_end}

    if signal == 'SKIP':
        if score >= 35 and TRADE_ON_CAUTION and direction in ('BUY', 'SELL'):
            print(f"[CAUTION] Borderline score {score}% — trading anyway (TRADE_ON_CAUTION=True)")
            trade_direction = direction
        else:
            reason = "range too small" if result['range_pips'] < 2 else f"score {score}%"
            print(f"[SKIP] {reason} — no trade")
            return {'result': result, 'candle_end': candle_end}
    else:
        # signal is BUY or SELL (score >= 50)
        trade_direction = signal

    # ── Wait for trade entry point: 0:08 remaining ──────
    rem = seconds_remaining(candle_end)
    if rem > TRADE_AT_REMAINING:
        print(f"\n[WAIT] Trade fires at {fmt_countdown(TRADE_AT_REMAINING)} "
              f"(in {rem - TRADE_AT_REMAINING:.0f}s)...")
        wait_until_remaining(candle_end, TRADE_AT_REMAINING, page)

    # ── FIRE TRADE ───────────────────────────────────────
    rem_at_fire = seconds_remaining(candle_end)

    if trade_direction == "BUY":
        click_ms = click_buy(page)
    else:
        click_ms = click_sell(page)

    print(f"\n  >>> {trade_direction} TRADE PLACED <<<")
    print(f"  Score:       {score}%")
    print(f"  Fired at:    {fmt_countdown(rem_at_fire)} remaining")
    print(f"  Click time:  {click_ms:.0f}ms")
    print(f"  Expiry:      {TRADE_EXPIRY}s")
    print(f"  Expires at:  ~{fmt_countdown(rem_at_fire - TRADE_EXPIRY)} remaining")

    return {'result': result, 'candle_end': candle_end}


def main():
    now = datetime.datetime.now()
    print("=" * 60)
    print("  POCKET BOT — Deep Signal Engine v6")
    print(f"  Account:   {'DEMO' if DEMO_MODE else 'REAL'}")
    print(f"  Asset:     {ASSET}")
    print(f"  Amount:    ${TRADE_AMOUNT}")
    print(f"  Expiry:    {TRADE_EXPIRY}s (expires at 0:01)")
    print(f"  Candle:    {CANDLE_SECONDS // 60}min (5:00 → 0:00)")
    print(f"  Collect:   1/sec from 5:00 to 0:{COLLECT_UNTIL:02d}")
    print(f"  Trade at:  0:{TRADE_AT_REMAINING:02d} remaining")
    print(f"  Min data:  {MIN_PRICES} prices")
    print(f"  Time:      {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Day:       {'Weekend' if now.weekday() >= 5 else 'Weekday'}")
    print("=" * 60)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=0)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # Attach WebSocket price feed BEFORE login so we capture all connections
        setup_price_feed(page)

        login(page)
        set_amount(page, TRADE_AMOUNT)
        set_expiry(page, TRADE_EXPIRY)

        # Wait for WebSocket price feed to start delivering ticks
        print("[PRICE] Waiting for first price tick...")
        for _ in range(30):
            if get_live_price() is not None:
                print(f"[PRICE] Feed active — current price: {get_live_price():.5f}")
                break
            playwright_sleep(page, 1)
        else:
            print("[PRICE] WARNING: No price ticks received after 30s — check WebSocket connection")

        print("\n[READY] Bot is running. Ctrl+C to stop.")
        print(f"[READY] Collecting 288 prices/candle, trading at 0:{TRADE_AT_REMAINING:02d} remaining.\n")

        try:
            while True:
                cycle = run_candle_cycle(page)
                # Wait past candle end before starting next cycle
                rem = seconds_remaining(cycle['candle_end'])
                if rem > 0:
                    print(f"\n[WAIT] Candle closes in {fmt_countdown(rem)} — waiting for next cycle...")
                    playwright_sleep(page, rem + 2)
                else:
                    playwright_sleep(page, 2)
        except KeyboardInterrupt:
            print("\n[STOP] Stopped by user")

        browser.close()


if __name__ == "__main__":
    main()
