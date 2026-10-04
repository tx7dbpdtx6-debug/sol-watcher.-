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
    if not isinstance(