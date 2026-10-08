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
from hot_water_planner import plan_hot_water

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
    raw = os.getenv("SHELLY_EVENT_SETTINGS", "")
    if raw and raw not in ("null", "{}"):
        # Shelly KVS values may be JSON-encoded strings rather than objects.
        # Do not silently fall back to sample settings for a dispatch event.
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Shelly dispatch settings must be an object")
        for key in ("porssi", "porssi-1", "porssi-2", "porssi-3"):
            value = data.get(key)
            if isinstance(value, str):
                value = json.loads(value)
            if not isinstance(value, dict):
                raise ValueError("Missing or invalid settings: " + key)
            data[key] = value
        print("Shelly settings received directly from GitHub dispatch")
        return data
    if os.getenv("GITHUB_EVENT_NAME") == "repository_dispatch":
        raise ValueError("Shelly dispatch event contains no settings")
    print("Using stored sample settings (scheduled/manual run)")
    return SHELLY_SETTINGS

def make_cross_day_plans(merged, actual, now, loads, settings):
    """Select individual cheapest hours across rolling 24..120 hour windows.

    Forecast-only: this does not control relays or enforce heat demand.
    """
    now_hour = now.replace(minute=0, second=0, microsecond=0)
    points = []
    for ts, spot in merged.items():
        local = ts.astimezone(TZ)
        if local < now_hour:
            continue
        points.append({
            "ts": ts,
            "start": local.isoformat(timespec="minutes"),
            "date": local.date().isoformat(),
            "hour": local.hour,
            "price": round(spot + transfer(local), 4),
            "source": "actual" if ts in actual else "forecast",
        })
    points.sort(key=lambda p: p["ts"])
    result = {}
    for index, name in enumerate(("lvv", "floor", "direct"), 1):
        cfg = settings["porssi-" + str(index)]
        # Existing Shelly m2.c is a daily-hour target, not a 5-day quota.
        hours_per_day = max(0, min(24, int(cfg["m2"]["c"])))
        horizons = {}
        for days in range(1, DAYS + 1):
            cutoff = now_hour.astimezone(timezone.utc) + timedelta(hours=24 * days)
            candidates = [p for p in points if p["ts"] < cutoff]
            required = hours_per_day * days
            # If forecast is incomplete, report that rather than pretending
            # the available cheapest hours cover the whole deadline.
            chosen = sorted(candidates, key=lambda p: (p["price"], p["ts"]))[:required]
            chosen.sort(key=lambda p: p["ts"])
            complete = len(candidates) >= 24 * days and len(chosen) == required
            blocks = []
            for p in chosen:
                item = {"start": p["start"], "price": p["price"], "source": p["source"]}
                if blocks and p["ts"] == blocks[-1]["_end"]:
                    blocks[-1]["hours"] += 1
                    blocks[-1]["_end"] = p["ts"] + timedelta(hours=1)
                else:
                    blocks.append({"start": p["start"], "hours": 1,
                                   "_end": p["ts"] + timedelta(hours=1)})
            for b in blocks:
                del b["_end"]
            horizons[str(days)] = {
                "window_hours": 24 * days,
                "requested_hours": required,
                "available_hours": len(candidates),
                "selected_hours": len(chosen),
                "complete": complete,
                "average_price": round(sum(p["price"] for p in chosen) / len(chosen), 3) if chosen else None,
                "selected": [{"start": p["start"], "price": p["price"],
                              "source": p["source"]} for p in chosen],
                "blocks": blocks,
            }
        result[name] = {"hours_per_day": hours_per_day, "horizons": horizons}
    return result

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

    rolling_plans = make_cross_day_plans(merged, actual, now, loads, settings)
    # Heating counter arrives as an additional KVS value in the same dispatch.
    heating_state = settings.get("sahkovatkain-o1-state")
    if isinstance(heating_state, str):
        heating_state = json.loads(heating_state)
    hot_water_plan = plan_hot_water(merged, actual, now, transfer, heating_state)

    result = {
        "version": 3,
        "updated": now.isoformat(timespec="seconds"),
        "timezone": "Europe/Helsinki",
        "price": "spot_with_vat_plus_transfer_c_per_kwh",
        "transfer": {"winter_weekday_07_22": 3.20, "other": 1.90},
        "loads": loads,
        "days": days,
        "best": best,
        "rolling_plans": rolling_plans,
        "hot_water_plan": hot_water_plan,
        "rolling_plan_note": "Forecast only; not relay commands. Each horizon assumes daily m2.c hours of demand.",
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
