#!/usr/bin/env python3
"""Paper-only Solana watcher. No wallet. No orders.

SOL is checked every cycle. Memecoins are read from watchlist.txt.
A memecoin is ignored unless market cap and pool liquidity both pass.

Alerts only. This does not buy or sell.
"""

import csv
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOL_MINT = "So11111111111111111111111111111111111111112"
DEX = "https://api.dexscreener.com/tokens/v1/solana/"

MIN_LIQ = 50_000
MIN_MCAP = 2_000_000
MIN_AGE_DAYS = 3
STAKE_SMALL = 0.01
STAKE_NORMAL = 0.02
EQUITY = 100.0

ROOT = Path(__file__).resolve().parent
WATCHLIST = ROOT / "watchlist.txt"
ALERTS = ROOT / "alerts.csv"
TELEGRAM = ROOT / "telegram.txt"


def load_telegram():
    token = os.environ.get("TG_TOKEN", "")
    chat = os.environ.get("TG_CHAT", "")
    if token and chat:
        return token, chat
    if not TELEGRAM.exists():
        return "", ""
    for line in TELEGRAM.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("token="):
            token = line.split("=", 1)[1].strip()
        elif line.startswith("chat_id="):
            chat = line.split("=", 1)[1].strip()
    return token, chat


def send_telegram(text):
    token, chat = load_telegram()
    if not token or not chat:
        print("    no telegram.txt yet, alert saved to csv only")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as exc:
        print(f"    telegram failed: {exc}")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kairos-paper-watcher"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def best_pair(mint):
    data = get_json(DEX + mint)
    if not isinstance(data, list) or not data:
        return None
    def score(p):
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        quote = ((p.get("quoteToken") or {}).get("symbol") or "").upper()
        bonus = 1.1 if quote in ("USDC", "USDT") else 1.0
        return liq * bonus
    return max(data, key=score)


def checks(pair, is_sol):
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    mcap = float(pair.get("marketCap") or pair.get("fdv") or 0)
    ch = pair.get("priceChange") or {}
    vol = pair.get("volume") or {}
    tx = (pair.get("txns") or {}).get("h1") or {}
    h1 = float(ch.get("h1") or 0)
    h6 = float(ch.get("h6") or 0)
    m5 = float(ch.get("m5") or 0)
    vol_h1 = float(vol.get("h1") or 0)
    buys = float(tx.get("buys") or 0)
    sells = float(tx.get("sells") or 0)
    created = pair.get("pairCreatedAt") or 0
    age_days = (time.time() * 1000 - created) / 86_400_000 if created else 0

    exit_ok = liq >= MIN_LIQ
    if not is_sol:
        exit_ok = exit_ok and mcap >= MIN_MCAP and age_days >= MIN_AGE_DAYS

    trend_ok = h6 > 0 and h1 > -1
    chase_cap = 8 if is_sol else 15
    pullback_ok = h1 < chase_cap and m5 < (2 if is_sol else 5) and h1 > -3
    volume_ok = vol_h1 > 0 and buys > sells and buys >= 10

    flags = {
        "exit": exit_ok,
        "trend": trend_ok,
        "pullback": pullback_ok,
        "volume": volume_ok,
    }
    passed = sum(1 for v in flags.values() if v)
    return flags, passed, liq, mcap, h1


def targets(is_sol):
    if is_sol:
        return 1.5, 0.8
    return 8.0, 5.0


def load_mints():
    mints = [SOL_MINT]
    if WATCHLIST.exists():
        for line in WATCHLIST.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line and line not in mints:
                mints.append(line)
    return mints


def log_alert(row):
    new = not ALERTS.exists()
    with ALERTS.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def scan():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{now}")
    for mint in load_mints():
        is_sol = mint == SOL_MINT
        try:
            pair = best_pair(mint)
        except Exception as exc:
            print(f"  skip {mint[:6]} feed error: {exc}")
            continue
        if not pair:
            print(f"  skip {mint[:6]} no pool")
            continue
        symbol = (pair.get("baseToken") or {}).get("symbol") or mint[:6]
        flags, passed, liq, mcap, h1 = checks(pair, is_sol)
        price = pair.get("priceUsd")
        mark = "SOL" if is_sol else symbol
        flag_txt = " ".join(f"{k}:{'Y' if v else 'N'}" for k, v in flags.items())
        print(f"  {mark:10} passed {passed}/4  {flag_txt}  liq ${liq:,.0f}  1h {h1:+.1f}%")
        if not flags["exit"] or passed < 3:
            continue
        tp, sl = targets(is_sol)
        size_pct = STAKE_NORMAL if passed == 4 else STAKE_SMALL
        level = "normal" if passed == 4 else "small"
        stake = round(EQUITY * size_pct, 2)
        row = {
            "time": now,
            "symbol": mark,
            "mint": mint,
            "level": level,
            "passed": passed,
            "stake_usd": stake,
            "price": price,
            "tp_pct": tp,
            "sl_pct": sl,
            "liq_usd": round(liq, 2),
            "mcap_usd": round(mcap, 2),
            "h1_pct": h1,
            **{f"check_{k}": int(v) for k, v in flags.items()},
        }
        log_alert(row)
        text = (
            f"{mark} {level} entry\n"
            f"checks {passed}/4\n"
            f"stake ${stake} on ${EQUITY:.0f} paper\n"
            f"price {price}\n"
            f"target +{tp}%   stop -{sl}%\n"
            f"mint {mint}"
        )
        print(f"    ALERT {level} stake ${stake}  target +{tp}%  stop -{sl}%")
        send_telegram(text)


if __name__ == "__main__":
    if not WATCHLIST.exists():
        WATCHLIST.write_text(
            "# One memecoin mint per line. SOL is always checked.\n"
        )
    print("One scan. No orders.")
    scan()