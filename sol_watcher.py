#!/usr/bin/env python3
import json, os, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOL_MINT = "So11111111111111111111111111111111111111112"
DEX = "https://api.dexscreener.com/tokens/v1/solana/"
MIN_LIQ, MIN_MCAP, MIN_AGE_DAYS = 50_000, 2_000_000, 3
STAKE_SMALL, STAKE_NORMAL, EQUITY = 0.01, 0.02, 100.0
ROOT = Path(__file__).resolve().parent
WATCHLIST = ROOT / "watchlist.txt"

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kairos-paper-watcher"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())

def send_telegram(text):
    token, chat = os.environ.get("TG_TOKEN", ""), os.environ.get("TG_CHAT", "")
    if not token or not chat:
        print("    no telegram secrets")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as exc:
        print(f"    telegram failed: {exc}")

def best_pair(mint):
    data = get_json(DEX + mint)
    if not isinstance(data, list) or not data:
        return None
    def score(p):
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        quote = ((p.get("quoteToken") or {}).get("symbol") or "").upper()
        return liq * (1.1 if quote in ("USDC", "USDT") else 1.0)
    return max(data, key=score)

def checks(pair, is_sol):
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    mcap = float(pair.get("marketCap") or pair.get("fdv") or 0)
    ch, vol = pair.get("priceChange") or {}, pair.get("volume") or {}
    tx = (pair.get("txns") or {}).get("h1") or {}
    h1, h6, m5 = float(ch.get("h1") or 0), float(ch.get("h6") or 0), float(ch.get("m5") or 0)
    buys, sells = float(tx.get("buys") or 0), float(tx.get("sells") or 0)
    created = pair.get("pairCreatedAt") or 0
    age_days = (time.time() * 1000 - created) / 86_400_000 if created else 0
    exit_ok = liq >= MIN_LIQ
    if not is_sol:
        exit_ok = exit_ok and mcap >= MIN_MCAP and age_days >= MIN_AGE_DAYS
    trend_ok = h6 > 0 and h1 > -1
    chase_cap = 8 if is_sol else 15
    pullback_ok = h1 < chase_cap and m5 < (2 if is_sol else 5) and h1 > -3
    volume_ok = float(vol.get("h1") or 0) > 0 and buys > sells and buys >= 10
    flags = {"exit": exit_ok, "trend": trend_ok, "pullback": pullback_ok, "volume": volume_ok}
    return flags, sum(flags.values()), liq, mcap, h1

def ema(values, n):
    k = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out = [None] * (n - 1) + [prev]
    for v in values[n:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out

def atr(highs, lows, closes, n=14):
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    return None if len(trs) < n else sum(trs[-n:]) / n

def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(-n, 0):
        diff = closes[i] - closes[i - 1]
        gains += diff if diff >= 0 else 0
        losses -= diff if diff < 0 else 0
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - (100 / (1 + rs))

def scan_gold():
    hour = datetime.now(timezone.utc).hour
    if not (7 <= hour < 21):
        print("  XAUUSD skip outside London/New York")
        return
    try:
        data = get_json("https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=15m&range=5d")
        result = data["chart"]["result"][0]
        q = result["indicators"]["quote"][0]
        stamps = result["timestamp"]
        bars = []
        for i, ts in enumerate(stamps):
            c, h, l = q["close"][i], q["high"][i], q["low"][i]
            if c is None or h is None or l is None:
                continue
            bars.append((ts, h, l, c))
    except Exception as exc:
        print(f"  XAUUSD feed error: {exc}")
        return
    if len(bars) < 60:
        print("  XAUUSD not enough candles")
        return
    age_min = (time.time() - bars[-1][0]) / 60
    if age_min > 30:
        print(f"  XAUUSD skip, last candle is {age_min:.0f} min old. Market closed or feed stale.")
        return
    highs = [b[1] for b in bars]
    lows = [b[2] for b in bars]
    closes = [b[3] for b in bars]
    avg20, avg50 = ema(closes, 20), ema(closes, 50)
    a, strength = atr(highs, lows, closes), rsi(closes)
    if not a or not avg20[-1] or not avg20[-2] or not avg50[-1] or strength is None:
        return
    if highs[-1] - lows[-1] > 2 * a:
        print("  XAUUSD skip spike")
        return
    long_ok = closes[-1] > avg20[-1] and closes[-2] > avg20[-2] and closes[-1] > avg50[-1] and 45 <= strength <= 68 and closes[-1] <= max(highs[-20:-1]) - 0.3 * a
    short_ok = closes[-1] < avg20[-1] and closes[-2] < avg20[-2] and closes[-1] < avg50[-1] and 32 <= strength <= 55 and closes[-1] >= min(lows[-20:-1]) + 0.3 * a
    if not long_ok and not short_ok:
        print(f"  XAUUSD skip RSI {strength:.1f}")
        return
    side = "LONG" if long_ok else "SHORT"
    buy, risk = closes[-1], 1.5 * a
    sl_price = round(buy - risk, 2) if side == "LONG" else round(buy + risk, 2)
    tp_price = round(buy + 2 * risk, 2) if side == "LONG" else round(buy - 2 * risk, 2)
    text = (
        f"XAUUSD {side}\n"
        f"entry {round(buy, 2)}\n"
        f"take profit {tp_price}\n"
        f"stop loss {sl_price}\n"
        f"paper risk 0.5%\n"
        f"Your chart must be within 2 dollars of {round(buy, 2)}. If it is not, skip.\n"
        f"Confirm no CPI, jobs, FOMC, or Powell in the next 45 minutes."
    )
    print(text)
    send_telegram(text)

def scan():
    print(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    mints = [SOL_MINT]
    if WATCHLIST.exists():
        for line in WATCHLIST.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line and line not in mints:
                mints.append(line)
    for mint in mints:
        is_sol = mint == SOL_MINT
        try:
            pair = best_pair(mint)
        except Exception as exc:
            print(f"  skip {mint[:6]} {exc}")
            continue
        if not pair:
            continue
        flags, passed, liq, mcap, h1 = checks(pair, is_sol)
        mark = "SOL" if is_sol else (pair.get("baseToken") or {}).get("symbol") or mint[:6]
        print(f"  {mark} {passed}/4 liq ${liq:,.0f} 1h {h1:+.1f}%")
        if not flags["exit"] or passed < 3:
            continue
        tp, sl = (1.5, 0.8) if is_sol else (8.0, 5.0)
        stake = round(EQUITY * (STAKE_NORMAL if passed == 4 else STAKE_SMALL), 2)
        buy = float(pair.get("priceUsd"))
        digits = 2 if is_sol else 6
        text = (
            f"{mark} LONG\n"
            f"signal {'normal' if passed == 4 else 'small'}  {passed}/4 checks\n"
            f"entry {buy}\n"
            f"take profit {round(buy * (1 + tp / 100), digits)}\n"
            f"stop loss {round(buy * (1 - sl / 100), digits)}\n"
            f"paper stake ${stake} of ${EQUITY:.0f}"
        )
        print("   ", text)
        send_telegram(text)
    scan_gold()

if __name__ == "__main__":
    print("One scan. No orders.")
    scan()