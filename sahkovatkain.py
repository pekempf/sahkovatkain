#!/usr/bin/env python3
import csv
import io
import json
import os
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Helsinki")
FORECAST_URL = "https://raw.githubusercontent.com/vividfog/nordpool-predict-fi/main/deploy/prediction.json"
SAHKOTIN_URL = "https://sahkotin.fi/prices.csv"
DAYS = 5
# Shelly KVS sample values. Later these can be supplied by a private bridge.
# The public repository must never contain cloud access tokens.
SHELLY_SETTINGS = {
    "porssi": {"vat": 25.5, "day": 3.2, "night": 1.9, "seasonal": 1},
    "porssi-1": {"en": 1, "mode": 2, "m2": {"p": 24, "c": 4, "l": 0, "m": 5}},
    "porssi-2": {"en": 1, "mode": 2, "m2": {"p": 24, "c": 6, "l": 0, "m": 3}},
    "porssi-3": {"en": 1, "mode": 2, "m2": {"p": 24, "c": 10, "l": 1, "m": 4}},
}
LOADS = {name: SHELLY_SETTINGS[f"porssi-{i}"]["m2"]["c"]
         for i, name in enumerate(("lvv", "floor", "direct"), 1)}

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

def read_settings():
    token = os.getenv("CLOUDFLARE_READ_TOKEN")
    if not token:
        return SHELLY_SETTINGS
    url = os.getenv("SETTINGS_URL")
    if not url:
        return SHELLY_SETTINGS
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)["settings"]
        for key in ("porssi", "porssi-1", "porssi-2", "porssi-3"):
            if not isinstance(data.get(key), dict):
                raise ValueError("Invalid settings")
        print("Shelly settings loaded from bridge")
        return data
    except urllib.error.HTTPError as exc:
        print("Bridge HTTP status:", exc.code)
        for name in ("server", "content-type", "cf-ray", "cf-mitigated", "location", "www-authenticate"):
            value = exc.headers.get(name)
            if value:
                print("Bridge header", name + ":", value)
        print("Bridge unavailable; using stored sample settings")
        return SHELLY_SETTINGS
    except Exception as exc:
        print("Bridge unavailable; using stored sample settings:", type(exc).__name__)
        return SHELLY_SETTINGS

def main():
    settings = read_settings()
    loads = {name: int(settings["porssi-" + str(i)]["m2"]["c"])
             for i, name in enumerate(("lvv", "floor", "direct"), 1)}
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
        for name, hours in loads.items():
            # If today has fewer hours left than requested, use every remaining
            # hour instead of discarding today as an option. This lets cheap
            # remaining electricity be used before a more expensive future day.
            use_hours = min(hours, len(points))
            if use_hours == 0:
                continue
            cheapest = sorted(points, key=lambda x: x["price"])[:use_hours]
            item["loads"][name] = {
                "hours": hours,
                "available_hours": use_hours,
                "avg": round(sum(p["price"] for p in cheapest) / use_hours, 3),
                "selected": [p["hour"] for p in sorted(cheapest, key=lambda x: x["ts"])],
            }
        days.append(item)

    # For every heating type and every 1..5 day deadline, precompute which
    # calendar day is cheapest. Shelly only needs to pick the horizon that
    # corresponds to its current remaining deadline.
    best = {}
    for name in loads:
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
        "loads": loads,
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
        "# date,lvv%d,floor%d,direct%d" % (loads["lvv"], loads["floor"], loads["direct"]),
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
