#!/usr/bin/env python3
"""
Pocket Option Trading Bot - Divine Formula (7 Second)
Based on: Divine Formula sheet 7sec.xlsx

Implements:
  - Sheet3: Core signal logic (6 price samples, volatility, BUY/SELL, session timing)
  - Sheet 3 Advanced: Weighted closing, RSI-like indicators, divine signals
  - Reference Point: Momentum, predicted close, reference point buy/sell
  - Session routing: Weekday/Weekend time-of-day entry/expiry
"""

import time
import datetime
import statistics
from typing import Dict, Optional, Tuple

import yfinance as yf

# === CONFIGURATION ===
ASSET = "EURUSD=X"
CANDLE_MINUTES = 10
DEMO_MODE = True
# "live" = wait for real candle timing, "instant" = rapid 6 samples for testing
RUN_MODE = "instant"
INSTANT_SPACING = 3  # seconds between samples in instant mode

# Price sampling times (seconds remaining before candle close)
SAMPLE_TIMES = {
    'B1': 105,  # 1:45 remaining
    'B2': 58,   # 0:58 remaining
    'B3': 43,   # 0:43 remaining
    'D1': 30,   # 0:30 remaining
    'D2': 26,   # 0:26 remaining
    'D3': 22,   # 0:22 remaining
}


# ── Price fetching ──────────────────────────────────────────────

def get_current_price(asset: str) -> Optional[float]:
    try:
        ticker = yf.Ticker(asset)
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"[ERROR] Price fetch failed: {e}")
    return None


def get_candle_data(asset: str) -> Optional[dict]:
    try:
        ticker = yf.Ticker(asset)
        data = ticker.history(period="5d", interval="1m")
        if data.empty:
            return None
        latest = data.iloc[-1]
        prev = data.iloc[-2] if len(data) > 1 else latest
        window = data.tail(CANDLE_MINUTES)
        prev_window = data.tail(CANDLE_MINUTES * 2).head(CANDLE_MINUTES)
        return {
            'open': float(window['Open'].iloc[0]),
            'high': float(window['High'].max()),
            'low': float(window['Low'].min()),
            'close': float(latest['Close']),
            'prev_close': float(prev['Close']),
            'prev_high': float(prev_window['High'].max()),
            'prev_low': float(prev_window['Low'].min()),
        }
    except Exception as e:
        print(f"[ERROR] Candle fetch failed: {e}")
    return None


# ── Sheet3 formulas ─────────────────────────────────────────────

def calc_volatility(B1, B3, D1, D3) -> str:
    ab = abs(B1 - B3)
    ad = abs(D1 - D3)
    if ab >= 0.001 and ad >= 0.001:
        return "HIGH"
    if 0.0004 <= ab < 0.001 and 0.0004 <= ad < 0.001:
        return "MEDIUM"
    return "LOW"


def calc_closing_simple(B1, B2, B3, D1, D2, D3) -> float:
    return statistics.mean([B1, B2, B3, D1, D2, D3])


def calc_closing_weighted(B1, B2, B3, D1, D2, D3) -> float:
    return (B1 * 1 + B2 * 1.5 + B3 * 2 + D1 * 1 + D2 * 1.2 + D3 * 1.2) / 7.9


def s3_direction(B4, B1, B2, B3, D1, D2, D3, vol) -> str:
    if vol == "HIGH" and B4 > B3 > B2 > B1 and D3 > D2 > D1:
        return "BUY"
    if vol == "LOW" and B4 < B3 < B2 < B1 and D3 < D2 < D1:
        return "SELL"
    if vol == "STABLE" and abs(B4 - B3) < 0.0001 and abs(D3 - D2) < 0.0001:
        return "BUY"
    if vol == "STABLE" and B4 > B3 and D3 > D2:
        return "BUY"
    return "SELL"


def s3_strength(B1, B2, B3, D1, D2, D3) -> str:
    if D1 > D2 > D3 and B1 > B2 > B3 and abs(D1 - D3) > 0.00015 and abs(B1 - B3) > 0.00015:
        return "SELL STRONG"
    if D1 < D2 < D3 and B1 < B2 < B3 and abs(D1 - D3) > 0.00015 and abs(B1 - B3) > 0.00015:
        return "BUY STRONG"
    if D1 > D2 and B1 > B2:
        return "SELL STRONG"
    if D1 < D2 and B1 < B2:
        return "BUY STRONG"
    return "SELL STRONG"


def s3_confirm(B4, B1, B2, B3, D1, D2, D3) -> str:
    if B4 > B3 > B2 > B1 and D3 > D2 > D1:
        return "BUY"
    return "SELL"


def s3_vol_type(B1, B3, D1, D3) -> str:
    if abs(D1 - D3) > abs(B1 - B3) * 1.3:
        return "HIGH VOLATILITY"
    return "STABLE"


def s3_confirm_direction(D1, D2, B1, B2) -> str:
    if D2 > D1 and B2 > B1:
        return "CONFIRM BUY"
    return "CONFIRM SELL"


def s3_trade_timing(B4, B1, B2, B3, D1, D2, D3, vol) -> str:
    up = B4 > B3 > B2 > B1 and D3 > D2 > D1
    down = B4 < B3 < B2 < B1 and D3 < D2 < D1
    ab = abs(B4 - B1)
    ad = abs(D3 - D1)
    if up:
        if vol == "HIGH" and ab > 0.0002 and ad > 0.0002:
            return "BUY at 10s Exp: 20s"
        if vol == "LOW" and ab > 0.0001 and ad > 0.0001:
            return "SELL at 12s Exp: 24s"
        return "BUY at 8s Exp: 20s"
    if down:
        if vol == "HIGH" and ab > 0.0002 and ad > 0.0002:
            return "SELL at 12s Exp: 24s"
        if vol == "LOW" and ab > 0.0001 and ad > 0.0001:
            return "BUY at 10s Exp: 20s"
        return "SELL at 14s Exp: 28s"
    if vol == "HIGH" and ab > 0.0002 and ad > 0.0002:
        return "BUY at 8s Exp: 20s"
    return "SELL at 12s Exp: 24s"


def s3_entry_expiry(B4, D3) -> str:
    diff = abs(B4 - D3)
    if diff > 0.0003:
        return "Enter at 12s, Expire at 24s"
    if diff > 0.00015:
        return "Enter at 9s, Expire at 18s"
    return "Enter at 8s, Expire at 16s"


def s3_final_confirm(B4, B1, B2, B3, D1, D2, D3) -> str:
    if B4 > B3 > B2 > B1 and D3 > D2 > D1:
        return "BUY CONFIRMED"
    return "SELL CONFIRMED"


def s3_safety(B4, B1, B2, B3) -> str:
    if abs(B4 - B3) > 0.0005 and abs(B3 - B2) > 0.0005 and abs(B2 - B1) > 0.0005:
        return "HIGH VOLATILITY - WAIT"
    return "STABLE - SAFE TO TRADE"


def s3_duration(vol) -> str:
    if vol == "HIGH":
        return "Enter at 6s, Expire at 12s"
    if vol == "MEDIUM":
        return "Enter at 8s, Expire at 16s"
    return "Enter at 10s, Expire at 20s"


# ── Session routing (Sheet3 rows 10-16) ────────────────────────

def session_name(hour, weekend) -> str:
    tag = "Weekend" if weekend else "Weekday"
    if 8 <= hour < 15:
        return f"{tag} 8AM-3PM"
    if 15 <= hour < 18:
        return f"{tag} 3PM-6PM"
    if 18 <= hour < 23:
        return f"{tag} 6PM-11PM"
    return f"{tag} 12AM-3AM"


def session_routing(B4, B1, B2, B3, D1, D2, D3, weekend) -> dict:
    hour = datetime.datetime.now().hour
    diff = abs(B4 - D3)
    up = B4 > B3 > B2 and D3 > D2 > D1

    if weekend:
        if 8 <= hour < 15:
            entry = "Enter at 8s, Expire at 20s" if diff > 0.00025 else "Enter at 8s, Expire at 16s"
            d = "BUY" if up and abs(B4 - B1) > 0.0002 else "SELL"
        elif 15 <= hour < 18:
            entry = "Enter at 8s, Expire at 20s" if diff > 0.00028 else "Enter at 9s, Expire at 18s"
            d = "BUY" if up and abs(B4 - B2) > 0.00025 and abs(B4 - B1) < 0.0004 else "SELL"
        elif 18 <= hour < 24:
            entry = "Enter at 8s, Expire at 16s"
            d = "BUY" if up and abs(B4 - B2) > 0.0002 else "SELL"
        else:
            entry = "Enter at 14s, Expire at 28s" if diff > 0.0003 else "Enter at 10s, Expire at 20s"
            d = "SELL" if B4 < B3 < B2 and D3 < D2 < D1 and abs(B4 - B3) > 0.0003 else "BUY"
    else:
        if 8 <= hour < 15:
            entry = "Enter at 10s, Expire at 20s" if diff > 0.0003 else "Enter at 8s, Expire at 16s"
            d = "BUY" if up and abs(B4 - B1) > 0.0002 else "SELL"
        elif 15 <= hour < 18:
            d = "BUY" if up else "SELL"
            entry = "Enter at 6s, Expire at 12s" if d == "BUY" else "Enter at 7s, Expire at 13s"
        elif 18 <= hour < 23:
            entry = "Enter at 11s, Expire at 22s" if diff > 0.00028 else "Enter at 7s, Expire at 14s"
            d = "BUY" if up and abs(B4 - B1) > 0.00025 else "SELL"
        else:
            entry = "Enter at 14s, Expire at 28s" if diff > 0.00032 else "Enter at 10s, Expire at 20s"
            d = "BUY" if B4 > B3 > B2 and D3 > D2 > D1 and abs(B4 - B3) < 0.00035 else "SELL"

    return {'direction': d, 'entry': entry, 'session': session_name(hour, weekend)}


# ── Sheet 3 Advanced ───────────────────────────────────────────

def advanced_signal(B1, B2, B3, B4, D1, D2, D3) -> str:
    avg_b = statistics.mean([B1, B2, B3])
    std_b = statistics.pstdev([B1, B2, B3])
    avg_d = statistics.mean([D1, D2, D3])

    E1 = (D3 - D2) + (D2 - D1)
    E2 = statistics.mean([abs(D3 - D2), abs(D2 - D1)])
    E3 = (max(0, D3 - D2) + max(0, D2 - D1)) / 2
    E4 = ((abs(D3 - D2) if D3 < D2 else 0) + (abs(D2 - D1) if D2 < D1 else 0)) / 2
    E5 = 100 - (100 / (1 + E3 / max(0.0001, E4)))
    E6 = abs(D3 - D2) / max(0.0001, E2)
    E7 = abs(D3 - D2) / max(0.0001, abs(D2 - D1))
    E8 = abs((D3 - B4) - E1) / max(0.0001, statistics.pstdev([D3, D2, D1]))
    E9 = statistics.mean([abs(B1 - B2), abs(B2 - B3)]) * 1.5
    E10 = (D3 - avg_b) / max(0.0001, std_b)
    E11 = (D3 - D2) / max(0.0001, statistics.mean([abs(B1 - B2), abs(B2 - B3), abs(D2 - D1)]))
    E12 = min(1, abs(E10) * E6 / max(0.0001, E8))

    if (E1 >= E2 * E9 and D3 > B4 and D3 > max(B1, B2, B3) and E5 < 65
            and avg_d > avg_b and D3 > (avg_b + 0.5 * std_b)
            and E6 > 0.2 and E8 < 2 and E10 > 0.03 and E11 > 0.4 and E12 > 0.8):
        return "HARD BUY (NIRANKAR'S BLESSED)"

    if (E1 <= E2 * E9 * -1 and D3 < B4 and D3 < min(B1, B2, B3) and E5 > 35
            and avg_d < avg_b and D3 < (avg_b - 0.5 * std_b)
            and E6 > 0.2 and E8 < 1.5 and E10 < -0.15 and E11 < -0.5 and E12 > 0.8):
        return "HARD SELL (NIRANKAR'S PROTECTED)"

    if (E1 >= E2 * E9 * 0.5 and D3 > B4 and avg_d > avg_b
            and D3 > (avg_b - 0.5 * std_b) and 0.15 < E7 < 6
            and E8 < 1.8 and E10 > 0.02 and E11 > 0.3 and E12 > 0.7):
        return "SOFT BUY (DIVINE SIGNAL)"

    if (E1 <= E2 * E9 * -0.5 and D3 < B4 and avg_d < avg_b
            and D3 < (avg_b + 0.5 * std_b) and 0.15 < E7 < 6
            and E8 < 1.3 and E10 < -0.1 and E11 < -0.4 and E12 > 0.7):
        return "SOFT SELL (DIVINE GUIDANCE)"

    if D3 >= B4 - 0.00003 and E8 < 1.2 and E10 >= -0.005 and E11 > 0.1 and E12 > 0.6:
        return "WEAK BUY (CAUTION)"

    return "WEAK SELL (ALERT)"


def advanced_sessions(B4, B1, B2, B3, D1, D2, D3) -> dict:
    w = ((B4 - B3) + (B4 - B2) * 0.7 + (B4 - B1) * 0.5
         + (B4 - D1) * 0.4 + (B4 - D2) * 0.4 + (B4 - D3) * 0.4)
    a11 = "BUY" if w > 0 else "SELL"

    if D1 < D2 < D3 and B3 < B2 and B1 > B3 and abs(B1 - B2) <= abs(B2 - B3) * 1.5:
        b11 = "BUY"
    elif D1 > D2 > D3 and B3 > B2 and B1 < B3 and abs(B1 - B2) <= abs(B2 - B3) * 1.5:
        b11 = "SELL"
    elif B4 < B3 < B2 < B1 and D1 < D2 < D3:
        b11 = "BUY"
    elif B4 > B3 > B2 > B1 and D1 > D2 > D3:
        b11 = "SELL"
    else:
        b11 = "BUY"

    c11 = "BUY" if (B1 > D3 or D3 > D2 > D1 or B1 > B2 > B3) else "SELL"

    avg_d = statistics.mean([D1, D2, D3])
    if D2 < D3 and B4 < D3 and B4 < min(B2, B3) and B4 < statistics.mean([B2, B3]):
        d11 = "SELL"
    elif D2 > D3 and B4 > D3 and B4 > max(B2, B3) and B4 > statistics.mean([B2, B3]):
        d11 = "BUY"
    elif B4 > avg_d:
        d11 = "BUY"
    else:
        d11 = "SELL"

    return {'8am_3pm': a11, '3pm_6pm': b11, '6pm_1am': c11, '1am_5am': d11}


# ── Reference Point logic ──────────────────────────────────────

def reference_analysis(cd: dict) -> dict:
    high, low = cd['high'], cd['low']
    current, opn = cd['close'], cd['open']
    prev_close = cd['prev_close']
    tp, rem = 9, 1

    mom = (current - opn) / tp
    vol = high - low
    adj_vol = vol * (rem / tp)
    closing1 = current + (mom * vol * rem)
    closing2 = current + (mom * adj_vol)
    predicted = current + ((current - opn) / tp) * rem + (vol / tp) * rem
    threshold = current * 0.008
    buy_sig = "Buy" if predicted > current + threshold else "No Buy"
    sell_sig = "Sell" if predicted < current - threshold else "No Sell"
    conf = abs(predicted - closing1) / closing1 * 100 if closing1 != 0 else 0
    ref_pt = (high + low) / 2 + ((current - prev_close) * (high - low) / 100)
    ref_buy = "Buy" if current > ref_pt else "No Buy"
    ref_sell = "Sell" if current < ref_pt else "No Sell"

    return {
        'momentum': mom, 'volatility': vol, 'predicted_close': predicted,
        'closing1': closing1, 'closing2': closing2,
        'threshold': threshold, 'buy_signal': buy_sig, 'sell_signal': sell_sig,
        'confidence': conf, 'ref_point': ref_pt,
        'ref_buy': ref_buy, 'ref_sell': ref_sell,
    }


# ── Price collection ────────────────────────────────────────────

def collect_prices_live(asset: str) -> Optional[Dict[str, float]]:
    now = datetime.datetime.now()
    candle_end_min = (now.minute // CANDLE_MINUTES + 1) * CANDLE_MINUTES
    if candle_end_min >= 60:
        candle_end = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    else:
        candle_end = now.replace(minute=candle_end_min, second=0, microsecond=0)

    remaining = (candle_end - now).total_seconds()
    print(f"[INFO] Candle closes at {candle_end.strftime('%H:%M:%S')} ({remaining:.0f}s remaining)")

    prices = {}
    for label, target_rem in sorted(SAMPLE_TIMES.items(), key=lambda x: x[1], reverse=True):
        sample_at = candle_end - datetime.timedelta(seconds=target_rem)
        wait = (sample_at - datetime.datetime.now()).total_seconds()
        if wait > 0:
            print(f"[WAIT] {label} in {wait:.1f}s ...")
            time.sleep(wait)
        elif wait < -10:
            print(f"[SKIP] {label} window passed")
            continue
        price = get_current_price(asset)
        if price is None:
            return None
        prices[label] = price
        print(f"[SAMPLE] {label} = {price:.5f}")

    return prices if len(prices) == 6 else None


def collect_prices_instant(asset: str) -> Optional[Dict[str, float]]:
    prices = {}
    labels = ['B1', 'B2', 'B3', 'D1', 'D2', 'D3']
    for i, label in enumerate(labels):
        if i > 0:
            time.sleep(INSTANT_SPACING)
        price = get_current_price(asset)
        if price is None:
            return None
        prices[label] = price
        print(f"[SAMPLE] {label} = {price:.5f}  (maps to {SAMPLE_TIMES[label]}s remaining)")
    return prices


# ── Analysis ────────────────────────────────────────────────────

def analyze(prices: Dict[str, float], candle: dict) -> dict:
    B1, B2, B3 = prices['B1'], prices['B2'], prices['B3']
    D1, D2, D3 = prices['D1'], prices['D2'], prices['D3']
    B4s = calc_closing_simple(B1, B2, B3, D1, D2, D3)
    B4w = calc_closing_weighted(B1, B2, B3, D1, D2, D3)
    vol = calc_volatility(B1, B3, D1, D3)
    weekend = datetime.datetime.now().weekday() >= 5

    return {
        'prices': prices,
        'B4_simple': B4s, 'B4_weighted': B4w, 'volatility': vol,
        'direction': s3_direction(B4s, B1, B2, B3, D1, D2, D3, vol),
        'strength': s3_strength(B1, B2, B3, D1, D2, D3),
        'confirmation': s3_confirm(B4s, B1, B2, B3, D1, D2, D3),
        'vol_type': s3_vol_type(B1, B3, D1, D3),
        'confirm_dir': s3_confirm_direction(D1, D2, B1, B2),
        'entry_expiry': s3_entry_expiry(B4s, D3),
        'trade_timing': s3_trade_timing(B4s, B1, B2, B3, D1, D2, D3, vol),
        'final_confirm': s3_final_confirm(B4s, B1, B2, B3, D1, D2, D3),
        'safety': s3_safety(B4s, B1, B2, B3),
        'duration': s3_duration(vol),
        'session': session_routing(B4s, B1, B2, B3, D1, D2, D3, weekend),
        'adv_signal': advanced_signal(B1, B2, B3, B4w, D1, D2, D3),
        'adv_sessions': advanced_sessions(B4w, B1, B2, B3, D1, D2, D3),
        'reference': reference_analysis(candle),
    }


# ── Output ──────────────────────────────────────────────────────

def print_results(r: dict) -> str:
    p = r['prices']
    print("\n" + "=" * 60)
    print("  DIVINE FORMULA - TRADE ANALYSIS")
    print("=" * 60)

    print(f"\n--- Price Samples ---")
    print(f"  B1 (1:45 rem): {p['B1']:.5f}")
    print(f"  B2 (0:58 rem): {p['B2']:.5f}")
    print(f"  B3 (0:43 rem): {p['B3']:.5f}")
    print(f"  D1 (0:30 rem): {p['D1']:.5f}")
    print(f"  D2 (0:26 rem): {p['D2']:.5f}")
    print(f"  D3 (0:22 rem): {p['D3']:.5f}")

    print(f"\n--- Sheet3 Core ---")
    print(f"  Closing (simple):   {r['B4_simple']:.5f}")
    print(f"  Closing (weighted): {r['B4_weighted']:.5f}")
    print(f"  Volatility:         {r['volatility']}")
    print(f"  Direction:          {r['direction']}")
    print(f"  Strength:           {r['strength']}")
    print(f"  Confirmation:       {r['confirmation']}")
    print(f"  Vol Type:           {r['vol_type']}")
    print(f"  Confirm Dir:        {r['confirm_dir']}")
    print(f"  Final Confirm:      {r['final_confirm']}")
    print(f"  Safety:             {r['safety']}")

    print(f"\n--- Timing ---")
    print(f"  Entry/Expiry:       {r['entry_expiry']}")
    print(f"  Trade Timing:       {r['trade_timing']}")
    print(f"  Duration:           {r['duration']}")

    s = r['session']
    print(f"\n--- Session: {s['session']} ---")
    print(f"  Direction:  {s['direction']}")
    print(f"  Entry:      {s['entry']}")

    print(f"\n--- Advanced Signal ---")
    print(f"  Signal: {r['adv_signal']}")
    a = r['adv_sessions']
    print(f"  8AM-3PM: {a['8am_3pm']}  |  3PM-6PM: {a['3pm_6pm']}  |  6PM-1AM: {a['6pm_1am']}  |  1AM-5AM: {a['1am_5am']}")

    ref = r['reference']
    print(f"\n--- Reference Point ---")
    print(f"  Predicted Close: {ref['predicted_close']:.5f}")
    print(f"  Reference Point: {ref['ref_point']:.5f}")
    print(f"  Momentum:        {ref['momentum']:.6f}")
    print(f"  Buy Signal:      {ref['buy_signal']}  |  Sell Signal: {ref['sell_signal']}")
    print(f"  Ref Buy:         {ref['ref_buy']}  |  Ref Sell: {ref['ref_sell']}")
    print(f"  Confidence:      {ref['confidence']:.2f}%")

    votes = {
        'Sheet3 Direction': r['direction'],
        'Sheet3 Confirm': r['confirmation'],
        'Strength': "BUY" if "BUY" in r['strength'] else "SELL",
        'Session': r['session']['direction'],
        'Advanced': "BUY" if "BUY" in r['adv_signal'] else "SELL",
        'Reference': "BUY" if ref['ref_buy'] == "Buy" else "SELL",
    }
    buy_count = sum(1 for v in votes.values() if v == "BUY")
    total = len(votes)
    consensus = "BUY" if buy_count > total / 2 else "SELL"

    print(f"\n--- Votes ---")
    for name, vote in votes.items():
        marker = "+" if vote == consensus else "-"
        print(f"  [{marker}] {name}: {vote}")

    agree_count = buy_count if consensus == "BUY" else total - buy_count
    print(f"\n{'=' * 60}")
    print(f"  CONSENSUS: {consensus}  ({agree_count}/{total} indicators agree)")
    print(f"  EXECUTE:   {r['trade_timing']}")
    print(f"  SAFETY:    {r['safety']}")
    print(f"{'=' * 60}\n")

    return consensus


def parse_timing(s: str) -> Tuple[int, int]:
    try:
        entry = int(s.split("at ")[1].split("s")[0])
        if "Exp:" in s:
            expiry = int(s.split("Exp: ")[1].replace("s", "").strip())
        else:
            expiry = int(s.split("Expire at ")[1].replace("s", "").strip())
        return entry, expiry
    except Exception:
        return 8, 16


def execute_trade(direction, entry, expiry):
    if DEMO_MODE:
        print(f"[DEMO] Would execute {direction} | Entry: {entry}s | Expiry: {expiry}s")
        print(f"[DEMO] No real trade placed (DEMO_MODE=True)")
        return
    # Pocket Option has no public REST API
    # Real execution would require browser automation (Selenium/Playwright)
    print(f"[TRADE] {direction} | Entry: {entry}s | Expiry: {expiry}s")


# ── Main ────────────────────────────────────────────────────────

def main():
    now = datetime.datetime.now()
    print("=" * 60)
    print("  POCKET BOT - Divine Formula (7 Second)")
    print(f"  Asset: {ASSET}")
    print(f"  Mode:  {'DEMO' if DEMO_MODE else 'LIVE'} | {RUN_MODE.upper()}")
    print(f"  Time:  {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Day:   {'Weekend' if now.weekday() >= 5 else 'Weekday'}")
    print("=" * 60)

    print("\n[INFO] Fetching candle data...")
    candle = get_candle_data(ASSET)
    if not candle:
        print("[ERROR] Could not fetch candle data. Exiting.")
        return
    print(f"[INFO] Candle: O={candle['open']:.5f} H={candle['high']:.5f} "
          f"L={candle['low']:.5f} C={candle['close']:.5f}")

    print(f"\n[INFO] Collecting 6 price samples ({RUN_MODE} mode)...")
    if RUN_MODE == "live":
        prices = collect_prices_live(ASSET)
    else:
        prices = collect_prices_instant(ASSET)

    if not prices:
        print("[ERROR] Price collection failed. Exiting.")
        return

    result = analyze(prices, candle)
    consensus = print_results(result)

    entry, expiry = parse_timing(result['trade_timing'])

    if result['safety'] == "HIGH VOLATILITY - WAIT":
        print("[SKIP] High volatility - trade skipped for safety")
        return

    if RUN_MODE == "live":
        print(f"[TRADE] Waiting {entry}s before executing {consensus}...")
        time.sleep(entry)

    execute_trade(consensus, entry, expiry)


if __name__ == "__main__":
    main()
