#!/usr/bin/env python3
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/vividfog/nordpool-predict-fi/main/deploy/prediction.json"
TZ = ZoneInfo("Europe/Helsinki")
HOURS = 8
DAYS = 5

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sahkovatkain/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def transfer_price(dt):
    winter = dt.month in (11, 12, 1, 2, 3)
    expensive = winter and dt.weekday() != 6 and 7 <= dt.hour < 22
    return 3.20 if expensive else 1.90

data = fetch_json(SOURCE)
now = datetime.now(TZ)
today = now.date()
rows = []

for n in range(DAYS):
    day = today + timedelta(days=n)
    prices = []
    for ts_ms, price in data:
        dt = datetime.fromtimestamp(ts_ms / 1000, TZ)
        if dt.date() == day:
            prices.append(float(price) + transfer_price(dt))
    prices.sort()
    if len(prices) >= HOURS:
        avg = sum(prices[:HOURS]) / HOURS
        rows.append(f"{day:%Y%m%d},{avg:.2f}")

Path("deploy").mkdir(exist_ok=True)
stamp = now.isoformat(timespec="seconds")
text = "# sahkovatkain v0.1\n# updated=" + stamp + "\n" + "\n".join(rows) + "\n"
Path("deploy/sahkovatkain.txt").write_text(text, encoding="utf-8")
print(text)
