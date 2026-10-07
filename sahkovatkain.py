#!/usr/bin/env python3
import csv
import io
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Helsinki")
FORECAST_URL = "https://raw.githubusercontent.com/vividfog/nordpool-predict-fi/main/deploy/prediction.json"
SAHKOTIN_URL = "https://sahkotin.fi/prices.csv"
DAYS = 5
LOADS = {"lvv": 3, "floor": 6, "direct": 12}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sahkovatkain/0.2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8-sig")

def transfer(dt):
    winter = dt.month in (11, 12, 1, 2, 3)
    return 3.20 if winter and dt.weekday() != 6 and 7 <= dt.hour < 22 else 1.90

def forecast_points():
    data = json.loads(get(FORECAST_URL))
    return {
        datetime.fromtimestamp(ts / 1000, timezone.utc): float(price)
        for ts, price in data
    }

def actual_points(start, end):
    params = urllib.parse.urlencode({
        "fix": "true",
        "vat": "true",
        "start": start.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "end": end.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
    })
    text = get(SAHKOTIN_URL + "?" + params)
    out = {}
    rows = csv.reader(io.StringIO(text))
    next(rows, None)
    for row in rows:
        if len(row) < 2:
            continue
        try:
            ts = datetime.fromisoformat(row[0].strip().replace("Z", "+00:00").replace(" ", "T"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out[ts.astimezone(timezone.utc)] = float(row[1].strip().replace(",", "."))
        except (ValueError, TypeError):
            pass
    return out

def main():
    now = datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=DAYS + 1)

    forecast = forecast_points()
    try:
        actual = actual_points(start, end)
    except Exception as e:
        print("WARNING: actual prices unavailable:", e)
        actual = {}

    # Published/actual prices always override prediction at the same timestamp.
    merged = dict(forecast)
    merged.update(actual)

    days = []
    for n in range(DAYS):
        day = (start + timedelta(days=n)).date()
        points = []
        for ts, price in merged.items():
            local = ts.astimezone(TZ)
            if local.date() == day:
                # For today, past hours can no longer be used for heating.
                # Keep the current clock hour and all future hours.
                if day == now.date() and local < now.replace(minute=0, second=0, microsecond=0):
                    continue
                source = "actual" if ts in actual else "forecast"
                points.append({
                    "ts": ts,
                    "hour": local.hour,
                    "price": price + transfer(local),
                    "source": source,
                })
        points.sort(key=lambda x: x["ts"])
        if not points:
            continue

        item = {
            "date": day.isoformat(),
            "actual_hours": sum(p["source"] == "actual" for p in points),
            "forecast_hours": sum(p["source"] == "forecast" for p in points),
            "loads": {},
        }
        for name, hours in LOADS.items():
            cheapest = sorted(points, key=lambda x: x["price"])[:hours]
            if len(cheapest) < hours:
                continue
            item["loads"][name] = {
                "hours": hours,
                "avg": round(sum(p["price"] for p in cheapest) / hours, 3),
                "selected": [p["hour"] for p in sorted(cheapest, key=lambda x: x["ts"])],
            }
        days.append(item)

    # For every heating type and every 1..5 day deadline, precompute which
    # calendar day is cheapest. Shelly only needs to pick the horizon that
    # corresponds to its current remaining deadline.
    best = {}
    for name in LOADS:
        best[name] = {}
        for horizon in range(1, DAYS + 1):
            candidates = [d for d in days[:horizon] if name in d["loads"]]
            if candidates:
                winner = min(candidates, key=lambda d: d["loads"][name]["avg"])
                best[name][str(horizon)] = {
                    "date": winner["date"],
                    "avg": winner["loads"][name]["avg"],
                    "today": winner["date"] == now.date().isoformat(),
                }

    result = {
        "version": 2,
        "updated": now.isoformat(timespec="seconds"),
        "timezone": "Europe/Helsinki",
        "price": "spot_with_vat_plus_transfer_c_per_kwh",
        "transfer": {"winter_weekday_07_22": 3.20, "other": 1.90},
        "loads": LOADS,
        "days": days,
        "best": best,
    }

    Path("deploy").mkdir(exist_ok=True)
    Path("deploy/sahkovatkain.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    # Tiny Shelly feed: date plus 3h/6h/12h daily scores.
    lines = [
        "# sahkovatkain v0.2",
        "# updated=" + now.isoformat(timespec="seconds"),
        "# date,lvv3,floor6,direct12",
    ]
    for d in days:
        vals = []
        for name in ("lvv", "floor", "direct"):
            vals.append(f'{d["loads"][name]["avg"]:.2f}' if name in d["loads"] else "-")
        lines.append(d["date"].replace("-", "") + "," + ",".join(vals))
    Path("deploy/sahkovatkain.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(json.dumps(best, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
