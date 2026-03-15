#!/usr/bin/env python3
"""
Pocket Option Live Trading Bot — Weekend Signal Engine v1
Runs Friday night through Sunday. Same candle sync as weekday bot but with
weekend-specific signal engine: trap detection, zigzag/chop detection,
manipulation scoring, and session-based thresholds (Fri/Sat/Sun).

Ported 1:1 from: EURUSD_Weekend_Signal_v1.html friday-sunday

Usage:
    cd ~/Desktop/Trading && source venv/bin/activate
    python3 -u pocket_live_weekend.py
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
EMAIL = "Sanchitk1904@gmail.com"
PASSWORD = "Sanchit_2704"
DEMO_MODE = False         # True = demo, False = real account
ASSET = "EUR/USD OTC"     # Change to any asset the platform supports
TRADE_AMOUNT = 1          # Dollars per trade
TRADE_EXPIRY = 7          # Seconds — trade expires at 0:01 remaining
CANDLE_SECONDS = 300      # 5-minute candle = 300 seconds
TRADE_AT_REMAINING = 8    # Place trade at 0:08 remaining

TRADE_ON_CAUTION = False  # True = trade on borderline scores — NOT recommended on weekends
MIN_PAYOUT = 80           # Minimum payout % — bot goes on standby below this

# Price collection: 1 price per second throughout the candle
COLLECT_UNTIL = 12        # Stop collecting at 0:12 remaining (trigger point)
MIN_PRICES = 120          # Minimum prices needed for reliable analysis


# ═══════════════════════════════════════════════════════════════
# SESSION CONFIG — weekend thresholds differ per day
# Ported 1:1 from EURUSD_Weekend_Signal_v1.html
# ═══════════════════════════════════════════════════════════════

SESSION_CONFIG = {
    'fri': {
        'label': 'Friday Late Night',
        'minScore': 68,
        'minNetDir': 0.32,
        'minRange': 1.5,
        'manipPenalty': 1.0,
    },
    'sat': {
        'label': 'Saturday',
        'minScore': 75,
        'minNetDir': 0.38,
        'minRange': 1.2,
        'manipPenalty': 1.4,
    },
    'sun': {
        'label': 'Sunday',
        'minScore': 72,
        'minNetDir': 0.35,
        'minRange': 1.3,
        'manipPenalty': 1.2,
    },
}


def get_session() -> str:
    """Return 'fri', 'sat', or 'sun' based on current day of week."""
    day = datetime.datetime.now().weekday()
    if day == 4:
        return 'fri'
    elif day == 5:
        return 'sat'
    else:
        return 'sun'


# ═══════════════════════════════════════════════════════════════
# WEEKEND SIGNAL ENGINE v1
# Ported 1:1 from: EURUSD_Weekend_Signal_v1.html
# 288 prices → 9-component scoring + manipulation score
# → BUY / SELL / SKIP / BLOCK / TRAP
# ═══════════════════════════════════════════════════════════════

PIP = 0.0001


def _detect_traps(pip_changes: List[float], n: int):
    """
    Weekend-specific trap move detection.
    A trap = price pushes strongly in ONE direction for ~8 seconds,
    then sharply reverses (wipes 60%+ of the push).
    This is the #1 weekend manipulation pattern.
    """
    traps = [False] * n
    trap_dir = [0] * n
    for i in range(10, n - 5):
        push_window = pip_changes[max(0, i - 8):i]
        push_sum = sum(push_window)
        if abs(push_sum) >= 1.5:
            reverse_window = pip_changes[i:i + 5]
            reverse_sum = sum(reverse_window)
            if (reverse_sum > 0) != (push_sum > 0) and abs(reverse_sum) >= abs(push_sum) * 0.6:
                traps[i] = True
                trap_dir[i] = 1 if push_sum > 0 else -1
    return traps, trap_dir


def _detect_spikes_weekend(pip_changes: List[float], n: int):
    """Detect fake spikes — lower threshold for weekend (2.0x instead of 2.5x)."""
    spikes = [False] * n
    for i in range(5, n - 2):
        window = pip_changes[max(0, i - 10):i]
        mean = sum(window) / len(window)
        std = (sum((x - mean) ** 2 for x in window) / len(window)) ** 0.5 or 0.01
        move = pip_changes[i]
        # Weekend: lower threshold (2.0x instead of 2.5x, 1.2 instead of 1.5)
        if abs(move) > max(2.0 * std, 1.2):
            reverse_check = pip_changes[i + 1] + (pip_changes[i + 2] if i + 2 < n else 0)
            if ((reverse_check > 0) != (move > 0)) and abs(reverse_check) > abs(move) * 0.35:
                spikes[i] = True
    return spikes


def _detect_reversals_weekend(pip_changes: List[float], spikes: List[bool], traps: List[bool], n: int):
    """Detect reversals — skips spikes AND traps (weekend-specific)."""
    reversals = [False] * n
    for i in range(8, n - 3):
        if spikes[i] or traps[i]:
            continue
        prev_sum = sum(pip_changes[i - 5:i])
        next_sum = sum(pip_changes[i:i + 3])
        # Weekend: slightly lower thresholds (1.5/1.0 instead of 2.0/1.5)
        if abs(prev_sum) > 1.5 and abs(next_sum) > 1.0 and ((prev_sum > 0) != (next_sum > 0)):
            reversals[i] = True
    return reversals


def _detect_zigzag(pip_changes: List[float], n: int):
    """
    Zigzag detection — alternating direction every 1-3 seconds.
    Pure chop/manipulation pattern common on weekends.
    """
    zigzag = [False] * n
    for i in range(4, n - 1):
        alternations = 0
        for j in range(i - 4, i):
            if j > 0 and (pip_changes[j] > 0) != (pip_changes[j - 1] > 0) and \
               abs(pip_changes[j]) > 0.3 and abs(pip_changes[j - 1]) > 0.3:
                alternations += 1
        if alternations >= 3:
            zigzag[i] = True
    return zigzag


def _compute_manipulation_score(
    recent_trap: bool, total_traps: int,
    recent_spike: bool, total_spikes: int,
    chop_rating: float, recent_reversal: bool,
    range_pips: float, min_range: float,
    zigzag_count: int, manip_penalty: float
) -> tuple:
    """
    Manipulation score (0-100, higher = more manipulation).
    Returns (score, items_list).
    """
    manip_score = 0
    items = []

    # Trap moves
    if recent_trap:
        manip_score += 35
        items.append(('TRAP MOVE', 'RECENT TRAP (last 25s)', True))
    elif total_traps > 0:
        manip_score += total_traps * 8
        items.append(('TRAP MOVE', f'{total_traps} trap(s) detected', True))
    else:
        items.append(('TRAP MOVE', 'none detected', False))

    # Fake spikes
    if recent_spike:
        manip_score += 20
        items.append(('FAKE SPIKE', 'RECENT SPIKE', True))
    elif total_spikes > 3:
        manip_score += 10
        items.append(('FAKE SPIKE', f'{total_spikes} spikes', True))
    else:
        items.append(('FAKE SPIKE', f'{total_spikes} spike(s)', False))

    # Chop zone
    if chop_rating > 0.35:
        manip_score += 20
        items.append(('CHOP ZONE', f'{chop_rating * 100:.0f}% zigzag', True))
    else:
        items.append(('CHOP ZONE', f'{chop_rating * 100:.0f}%', False))

    # Late reversal
    if recent_reversal:
        manip_score += 15
        items.append(('LATE REVERSAL', 'FLIP DETECTED', True))
    else:
        items.append(('LATE REVERSAL', 'none recent', False))

    # Micro range
    if range_pips < min_range:
        manip_score += 10
        items.append(('MICRO RANGE', f'{range_pips:.2f} pip (too small)', True))
    else:
        items.append(('MICRO RANGE', f'{range_pips:.2f} pip', False))

    # Zigzag
    if zigzag_count > 20:
        manip_score += 10
        items.append(('ZIGZAG', f'{zigzag_count} seconds choppy', True))
    else:
        items.append(('ZIGZAG', f'{zigzag_count} sec OK', False))

    # Apply session multiplier
    manip_score = min(100, round(manip_score * manip_penalty))

    return manip_score, items


def run_weekend_signal(prices: List[float], session: str = None) -> dict:
    """
    Weekend Signal Engine v1 — 9-component scoring + manipulation score.
    Takes array of prices (1 per second, from candle open to 0:12 remaining).
    Returns dict with signal, score, verdict, direction, breakdown, manipulation info.
    """
    if session is None:
        session = get_session()
    cfg = SESSION_CONFIG[session]

    n = len(prices)

    # ── Second-by-second pip changes ──────────────────────
    pip_changes = [0.0]
    for i in range(1, n):
        pip_changes.append((prices[i] - prices[i - 1]) / PIP)

    # ── Detection: traps, spikes, reversals, zigzag ───────
    traps, trap_dir = _detect_traps(pip_changes, n)
    spikes = _detect_spikes_weekend(pip_changes, n)
    reversals = _detect_reversals_weekend(pip_changes, spikes, traps, n)
    zigzag = _detect_zigzag(pip_changes, n)

    # ── Key metrics ───────────────────────────────────────
    open_price = prices[0]
    close_price = prices[-1]
    high = max(prices)
    low = min(prices)
    range_pips = (high - low) / PIP
    net_pips = (close_price - open_price) / PIP

    # Spike + trap filtered direction
    filt_up = 0.0
    filt_dn = 0.0
    for i in range(1, n):
        if spikes[i] or traps[i]:
            continue
        if pip_changes[i] > 0:
            filt_up += pip_changes[i]
        else:
            filt_dn += abs(pip_changes[i])

    if filt_up > filt_dn:
        filtered_direction = 'BUY'
    elif filt_dn > filt_up:
        filtered_direction = 'SELL'
    else:
        filtered_direction = 'FLAT'
    dir_strength = abs(filt_up - filt_dn) / (filt_up + filt_dn + 0.001)

    # Last 30 seconds momentum
    last30 = prices[max(0, n - 30):]
    last30_net = (last30[-1] - last30[0]) / PIP
    first30_net = abs((prices[29] - prices[0]) / PIP) if len(prices) >= 30 else 0
    last30_abs = abs(last30_net)
    accelerating = last30_abs > first30_net

    # Last 10 seconds
    last10_net = (prices[-1] - prices[max(0, n - 10)]) / PIP

    # Consistency (excluding spikes, traps, and zigzag)
    consistent_seconds = 0
    total_non_manip = 0
    for i in range(1, n):
        if spikes[i] or traps[i] or zigzag[i]:
            continue
        total_non_manip += 1
        if filtered_direction == 'BUY' and pip_changes[i] > 0:
            consistent_seconds += 1
        if filtered_direction == 'SELL' and pip_changes[i] < 0:
            consistent_seconds += 1
    consistency = consistent_seconds / total_non_manip if total_non_manip > 0 else 0

    # Chop rating
    zigzag_count = sum(zigzag)
    chop_rating = zigzag_count / n

    # Recent checks
    last_trap_idx = max((i for i in range(n) if traps[i]), default=-1)
    recent_trap = last_trap_idx >= n - 25 and last_trap_idx != -1

    last_spike_idx = max((i for i in range(n) if spikes[i]), default=-1)
    recent_spike = last_spike_idx >= n - 15 and last_spike_idx != -1

    last_rev_idx = max((i for i in range(n) if reversals[i]), default=-1)
    recent_reversal = last_rev_idx >= n - 20 and last_rev_idx != -1

    total_spikes = sum(spikes)
    total_traps = sum(traps)
    total_reversals = sum(reversals)

    # ── Manipulation Score ────────────────────────────────
    manip_score, manip_items = _compute_manipulation_score(
        recent_trap, total_traps,
        recent_spike, total_spikes,
        chop_rating, recent_reversal,
        range_pips, cfg['minRange'],
        zigzag_count, cfg['manipPenalty']
    )

    # ══════════════════════════════════════════════════════
    # SCORING SYSTEM (out of 100) — 9 components
    # ══════════════════════════════════════════════════════
    score = 0
    breakdown = []

    # ① NET DIRECTION (max 20) — weekend needs higher net dir %
    net_dir_blocked = dir_strength < cfg['minNetDir'] and range_pips >= cfg['minRange']
    if range_pips < cfg['minRange']:
        s1 = 0
        s1_note = f"Range {range_pips:.2f} pip — too small for weekend"
        s1_verdict = 'SKIP'
    elif net_dir_blocked:
        s1 = 0
        s1_note = f"{filtered_direction} · {dir_strength * 100:.0f}% — below {cfg['minNetDir'] * 100:.0f}% weekend minimum"
        s1_verdict = 'HARD SKIP'
    else:
        s1 = round(min(dir_strength * 28, 20))
        s1_note = f"{filtered_direction} · {dir_strength * 100:.0f}% strength (trap/spike filtered)"
        s1_verdict = 'STRONG' if s1 >= 15 else 'MODERATE' if s1 >= 9 else 'WEAK'
    score += s1
    breakdown.append(('① NET DIRECTION', s1_note, f'{s1}/20', s1_verdict))

    # ② TRAP MOVE PENALTY (max -25) — weekend exclusive
    if recent_trap:
        s2 = -25
        s2_note = 'Trap move in last 25s — FAKE direction push detected'
        s2_verdict = 'HARD BLOCK'
    elif total_traps > 1:
        s2 = -10 * min(total_traps, 2)
        s2_note = f'{total_traps} trap move(s) this candle'
        s2_verdict = 'DANGER'
    elif total_traps == 1:
        s2 = -5
        s2_note = '1 trap detected (early candle)'
        s2_verdict = 'CAUTION'
    else:
        s2 = 0
        s2_note = 'No trap moves'
        s2_verdict = 'CLEAN'
    score += s2
    breakdown.append(('② TRAP PENALTY', s2_note, f'{s2}/0', s2_verdict))

    # ③ LAST 30s MOMENTUM (max 18)
    l30_aligned = ((filtered_direction == 'BUY' and last30_net > 0) or
                   (filtered_direction == 'SELL' and last30_net < 0))
    if l30_aligned:
        s3 = min(round(abs(last30_net) * 3.5), 18)
        s3_note = f"{'+' if last30_net > 0 else ''}{last30_net:.2f}p last 30s"
        s3_verdict = 'STRONG PUSH' if s3 >= 12 else 'ALIGNED'
    else:
        s3 = 0
        s3_note = f"AGAINST signal · {last30_net:.2f} pips"
        s3_verdict = 'MISALIGNED'
    score += s3
    breakdown.append(('③ LAST 30s MOMENTUM', s3_note, f'{s3}/18', s3_verdict))

    # ④ CHOP / ZIGZAG PENALTY (max -15)
    if chop_rating > 0.4:
        s4 = -15
        s4_note = f'{chop_rating * 100:.0f}% of candle is zigzag chop'
        s4_verdict = 'EXTREME CHOP'
    elif chop_rating > 0.25:
        s4 = -8
        s4_note = f'{chop_rating * 100:.0f}% zigzag detected'
        s4_verdict = 'CHOPPY'
    else:
        s4 = 0
        s4_note = f'{chop_rating * 100:.0f}% — acceptable'
        s4_verdict = 'CLEAN'
    score += s4
    breakdown.append(('④ CHOP / ZIGZAG', s4_note, f'{s4}/0', s4_verdict))

    # ⑤ CONSISTENCY (max 14) — excluding spikes/traps/zigzag
    s5 = round(consistency * 14)
    s5_note = f"{consistency * 100:.0f}% non-manipulated seconds in signal direction"
    s5_verdict = 'CONSISTENT' if consistency >= 0.65 else 'MIXED' if consistency >= 0.5 else 'NOISY'
    score += s5
    breakdown.append(('⑤ CONSISTENCY', s5_note, f'{s5}/14', s5_verdict))

    # ⑥ ACCELERATION (max 8 — lower than weekday, less reliable on weekends)
    if accelerating:
        s6 = 8
        s6_note = f"Last 30s ({last30_abs:.1f}p) > First 30s ({first30_net:.1f}p)"
        s6_verdict = 'ACCELERATING'
    else:
        s6 = 2
        s6_note = f"Slowing · last 30s ({last30_abs:.1f}p)"
        s6_verdict = 'DECELERATING'
    score += s6
    breakdown.append(('⑥ ACCELERATION', s6_note, f'{s6}/8', s6_verdict))

    # ⑦ RANGE SIZE (max 8)
    if range_pips >= 4:
        s7, s7_verdict = 8, 'EXCELLENT'
    elif range_pips >= 2.5:
        s7, s7_verdict = 6, 'GOOD'
    elif range_pips >= cfg['minRange']:
        s7, s7_verdict = 3, 'BORDERLINE'
    else:
        s7, s7_verdict = 0, 'TOO SMALL'
    s7_note = f"{range_pips:.2f} pip range"
    score += s7
    breakdown.append(('⑦ RANGE SIZE', s7_note, f'{s7}/8', s7_verdict))

    # ⑧ LATE REVERSAL PENALTY (max -15)
    if recent_reversal:
        s8 = -15
        s8_note = 'Reversal in last 20s — flip already started'
        s8_verdict = 'HARD BLOCK'
    elif total_reversals > 2:
        s8 = -5
        s8_note = f'{total_reversals} reversals — indecisive candle'
        s8_verdict = 'CAUTION'
    else:
        s8 = 0
        s8_note = f'{total_reversals} reversal(s) — none recent'
        s8_verdict = 'SAFE'
    score += s8
    breakdown.append(('⑧ REVERSAL PENALTY', s8_note, f'{s8}/0', s8_verdict))

    # ⑨ LAST 10s ALIGNMENT (max 8)
    l10_aligned = ((filtered_direction == 'BUY' and last10_net > 0) or
                   (filtered_direction == 'SELL' and last10_net < 0))
    if l10_aligned:
        s9 = min(round(abs(last10_net) * 4), 8)
        s9_note = f"Last 10s: {'+' if last10_net > 0 else ''}{last10_net:.2f} pips"
        s9_verdict = 'ALIGNED'
    else:
        s9 = 0
        s9_note = 'Last 10s against signal'
        s9_verdict = 'MISALIGNED'
    score += s9
    breakdown.append(('⑨ LAST 10s ALIGNMENT', s9_note, f'{s9}/8', s9_verdict))

    # Clamp 0-100
    score = max(0, min(100, score))

    # Manipulation penalty on final score (30% of manip score)
    manip_penalty_on_score = round(manip_score * 0.3)
    score = max(0, score - manip_penalty_on_score)

    # ══════════════════════════════════════════════════════
    # FINAL VERDICT
    # ══════════════════════════════════════════════════════
    final_signal = filtered_direction

    if recent_trap and range_pips >= cfg['minRange']:
        verdict = 'TRAP DETECTED — HARD BLOCK'
        final_signal = 'TRAP'
    elif recent_reversal and range_pips >= cfg['minRange']:
        verdict = 'HARD BLOCK · REVERSAL'
        final_signal = 'BLOCK'
    elif net_dir_blocked:
        verdict = f"SKIP · NET DIR {dir_strength * 100:.0f}% (NEED {cfg['minNetDir'] * 100:.0f}%+)"
        final_signal = 'SKIP'
    elif score >= cfg['minScore']:
        if final_signal in ('BUY', 'SELL'):
            verdict = f'ENTER {final_signal}'
        else:
            verdict = 'SKIP'
            final_signal = 'SKIP'
    elif score >= cfg['minScore'] - 10:
        verdict = 'BORDERLINE — SKIP ON WEEKEND'
        final_signal = 'SKIP'
    else:
        verdict = 'SKIP'
        final_signal = 'SKIP'

    if range_pips < cfg['minRange']:
        verdict = 'SKIP · RANGE TOO SMALL'
        final_signal = 'SKIP'

    return {
        'signal': final_signal,
        'verdict': verdict,
        'score': score,
        'direction': filtered_direction,
        'breakdown': breakdown,
        'range_pips': range_pips,
        'net_pips': net_pips,
        'total_spikes': total_spikes,
        'total_traps': total_traps,
        'total_reversals': total_reversals,
        'last30_net': last30_net,
        'last10_net': last10_net,
        'consistency': consistency,
        'accelerating': accelerating,
        'recent_spike': recent_spike,
        'recent_trap': recent_trap,
        'recent_reversal': recent_reversal,
        'chop_rating': chop_rating,
        'manip_score': manip_score,
        'manip_items': manip_items,
        'session': session,
        'session_label': cfg['label'],
        'min_score': cfg['minScore'],
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

        if not page.locator(modal_sel).is_visible():
            page.locator('[class*="block-expiration"]').first.click()
            time.sleep(0.5)

        inputs = page.locator(f'{modal_sel} .input-field-wrapper input')
        if inputs.count() != 3:
            print(f"[SETUP] Expected 3 expiry inputs, found {inputs.count()} — set to {seconds}s manually")
            return

        hrs = seconds // 3600
        mins = (seconds % 3600) // 60
        secs = seconds % 60

        for i, val in enumerate([f"{hrs:02d}", f"{mins:02d}", f"{secs:02d}"]):
            inp = inputs.nth(i)
            inp.click(click_count=3)
            page.keyboard.type(val)
            time.sleep(0.1)

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
    if price and local_age < 10:
        return price
    return None


def get_payout(page: Page) -> Optional[int]:
    """Read the current payout % from the Pocket Option UI."""
    try:
        text = page.evaluate("""() => {
            const els = document.querySelectorAll('[class*="percent"], [class*="payout"], [class*="profit"]');
            for (const el of els) {
                const m = el.textContent.match(/(\\d+)\\s*%/);
                if (m && parseInt(m[1]) >= 50 && parseInt(m[1]) <= 100) return m[1];
            }
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
    s = max(0, int(secs))
    return f"{s // 60}:{s % 60:02d}"


def playwright_sleep(page: Page, duration: float):
    """Sleep while keeping Playwright's event loop alive (processes WS frames)."""
    if duration <= 0:
        return
    chunk = min(duration, 2.0)
    remaining = duration
    while remaining > 0:
        ms = int(min(chunk, remaining) * 1000)
        page.wait_for_timeout(ms)
        remaining -= chunk


def wait_until_remaining(candle_end: datetime.datetime, target_secs: float, page: Page = None):
    """Sleep until the candle countdown reaches target_secs remaining."""
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
    One full candle cycle (weekend mode):
      1. Collect 1 price/sec from 5:00 down to 0:12 (288 prices)
      2. At 0:12 — stop collecting, run Weekend Signal Engine
      3. At 0:08 — place trade if signal says BUY/SELL
      4. 7-second expiry — trade expires at 0:01
    """
    candle_end = next_candle_end()
    rem = seconds_remaining(candle_end)

    session = get_session()
    cfg = SESSION_CONFIG[session]

    # ── Check payout before doing anything ──────────────
    payout = get_payout(page)
    payout_str = f"{payout}%" if payout else "unknown"

    print(f"\n{'='*60}")
    print(f"  CANDLE CYCLE — Weekend Signal Engine v1")
    print(f"  Session: {cfg['label']} (min score: {cfg['minScore']}%)")
    print(f"  Candle ends: {candle_end.strftime('%H:%M:%S')}  ({fmt_countdown(rem)} remaining)")
    print(f"  Payout: {payout_str}")
    print(f"{'='*60}")

    if payout is not None and payout < MIN_PAYOUT:
        print(f"[STANDBY] Payout {payout}% < {MIN_PAYOUT}% — waiting for payout to be more than {MIN_PAYOUT}%")
        return {'result': None, 'candle_end': candle_end}

    # Need enough collection time
    collection_time = rem - COLLECT_UNTIL
    if collection_time < MIN_PRICES:
        print(f"[SKIP] Only {collection_time:.0f}s of collection time — need {MIN_PRICES}s. "
              f"Waiting for next candle...")
        return {'result': None, 'candle_end': candle_end}

    # Verify WebSocket feed is alive
    if get_live_price() is None:
        print("[SKIP] WebSocket price feed not active — cannot sample. Waiting for next candle...")
        return {'result': None, 'candle_end': candle_end}

    # ── Collect prices: 1 per second until 0:12 remaining ──
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

    # ── Run Weekend Signal Engine ──────────────────────
    t0 = time.time()
    result = run_weekend_signal(prices, session)
    t_analysis = (time.time() - t0) * 1000

    signal = result['signal']
    score = result['score']
    verdict = result['verdict']
    direction = result['direction']
    manip_score = result['manip_score']

    print(f"\n[ENGINE] Analyzed in {t_analysis:.0f}ms — {result['num_prices']} prices")
    print(f"  Session:   {result['session_label']} (threshold: {result['min_score']}%)")
    print(f"  Direction: {direction} ({result['range_pips']:.1f} pip range)")
    print(f"  Score:     {score}%")
    print(f"  Manip:     {manip_score}% manipulation score")
    print(f"  Chop:      {result['chop_rating'] * 100:.0f}% zigzag")
    for comp, note, sc, verd in result['breakdown']:
        print(f"    {comp}: {sc} — {note} [{verd}]")

    # Print manipulation items
    for key, val, detected in result['manip_items']:
        flag = '!!' if detected else 'OK'
        print(f"    [MANIP] {key}: {val} [{flag}]")

    print(f"  VERDICT:   {verdict}")

    # ── Should we trade? ─────────────────────────────────
    if signal == 'TRAP':
        print("[TRAP] Weekend trap detected — DO NOT ENTER")
        return {'result': result, 'candle_end': candle_end}

    if signal == 'BLOCK':
        print("[BLOCK] Reversal detected — DO NOT ENTER")
        return {'result': result, 'candle_end': candle_end}

    if signal == 'SKIP':
        if score >= cfg['minScore'] - 10 and TRADE_ON_CAUTION and direction in ('BUY', 'SELL'):
            print(f"[CAUTION] Borderline score {score}% — trading anyway (TRADE_ON_CAUTION=True)")
            trade_direction = direction
        else:
            reason = "range too small" if result['range_pips'] < cfg['minRange'] else f"score {score}%"
            print(f"[SKIP] {reason} — no trade")
            return {'result': result, 'candle_end': candle_end}
    else:
        # signal is BUY or SELL
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
    print(f"  Manip:       {manip_score}%")
    print(f"  Session:     {cfg['label']}")
    print(f"  Fired at:    {fmt_countdown(rem_at_fire)} remaining")
    print(f"  Click time:  {click_ms:.0f}ms")
    print(f"  Expiry:      {TRADE_EXPIRY}s")
    print(f"  Expires at:  ~{fmt_countdown(rem_at_fire - TRADE_EXPIRY)} remaining")

    return {'result': result, 'candle_end': candle_end}


def main():
    now = datetime.datetime.now()
    session = get_session()
    cfg = SESSION_CONFIG[session]

    print("=" * 60)
    print("  POCKET BOT — Weekend Signal Engine v1")
    print(f"  Account:   {'DEMO' if DEMO_MODE else 'REAL'}")
    print(f"  Session:   {cfg['label']}")
    print(f"  Min Score: {cfg['minScore']}%")
    print(f"  Min Dir:   {cfg['minNetDir'] * 100:.0f}%")
    print(f"  Min Range: {cfg['minRange']} pip")
    print(f"  Asset:     {ASSET}")
    print(f"  Amount:    ${TRADE_AMOUNT}")
    print(f"  Expiry:    {TRADE_EXPIRY}s (expires at 0:01)")
    print(f"  Candle:    {CANDLE_SECONDS // 60}min (5:00 → 0:00)")
    print(f"  Collect:   1/sec from 5:00 to 0:{COLLECT_UNTIL:02d}")
    print(f"  Trade at:  0:{TRADE_AT_REMAINING:02d} remaining")
    print(f"  Min data:  {MIN_PRICES} prices")
    print(f"  Time:      {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Day:       {now.strftime('%A')}")
    print("=" * 60)

    # Weekend check warning
    if now.weekday() < 4:
        print("\n[WARNING] Today is a weekday! This bot is designed for Friday-Sunday.")
        print("[WARNING] Running anyway, but consider using pocket_live.py instead.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=0)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # Attach WebSocket price feed BEFORE login
        setup_price_feed(page)

        login(page)
        set_amount(page, TRADE_AMOUNT)
        set_expiry(page, TRADE_EXPIRY)

        # Wait for WebSocket price feed
        print("[PRICE] Waiting for first price tick...")
        for _ in range(30):
            if get_live_price() is not None:
                print(f"[PRICE] Feed active — current price: {get_live_price():.5f}")
                break
            playwright_sleep(page, 1)
        else:
            print("[PRICE] WARNING: No price ticks received after 30s — check WebSocket connection")

        print("\n[READY] Weekend bot is running. Ctrl+C to stop.")
        print(f"[READY] Session: {cfg['label']} · Min score: {cfg['minScore']}%")
        print(f"[READY] Collecting 288 prices/candle, trading at 0:{TRADE_AT_REMAINING:02d} remaining.\n")

        try:
            while True:
                cycle = run_candle_cycle(page)
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
