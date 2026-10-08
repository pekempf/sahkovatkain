"""Price-only hot-water scheduling; never controls Shelly outputs."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Helsinki")
TARGET_HOURS = 4
MAX_INTERVAL_HOURS = 72


def parse_time(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Heating state timestamps must include a timezone")
    return dt.astimezone(timezone.utc)


def plan_hot_water(merged, actual, now, transfer, state=None):
    """Select remaining cheapest hours before deadline; actual heating state required.

    state: {"last_completed_at": ISO8601, "heated_hours": [ISO8601, ...]}.
    heated_hours contains completed hour starts since last_completed_at.
    """
    now_utc = now.astimezone(timezone.utc)
    current_hour = now_utc.replace(minute=0, second=0, microsecond=0)
    if not isinstance(state, dict) or not state.get("last_completed_at"):
        return {"status": "missing_heating_state", "target_hours": TARGET_HOURS,
                "max_interval_hours": MAX_INTERVAL_HOURS, "selected": [],
                "note": "Last completed heating cycle is unknown; no actionable schedule."}
    completed = parse_time(state["last_completed_at"])
    if completed > now_utc:
        raise ValueError("Last completion cannot be in the future")
    deadline = completed + timedelta(hours=MAX_INTERVAL_HOURS)
    completed_day = completed.astimezone(TZ).date()
    already = set()
    for item in state.get("heated_hours", []):
        hour = parse_time(item)
        if hour.minute or hour.second or hour.microsecond:
            raise ValueError("Heated hours must be exact hour starts")
        if hour >= completed and hour < now_utc:
            already.add(hour)
    if len(already) > TARGET_HOURS:
        raise ValueError("More than four heated hours in an unfinished cycle")
    remaining = TARGET_HOURS - len(already)
    # The next cycle may only start on a later local calendar day.
    eligible = []
    for ts, spot in merged.items():
        hour = ts.astimezone(timezone.utc)
        if hour < current_hour or hour >= deadline or hour in already:
            continue
        local = hour.astimezone(TZ)
        if local.date() <= completed_day:
            continue
        eligible.append({"ts": hour, "start": local.isoformat(timespec="minutes"),
                         "price": round(float(spot) + transfer(local), 4),
                         "source": "actual" if ts in actual else "forecast"})
    chosen = sorted(eligible, key=lambda p: (p["price"], p["ts"]))[:remaining]
    chosen.sort(key=lambda p: p["ts"])
    # A forecast can change; a selection is advisory until the hours actually run.
    status = ("deadline_passed" if deadline <= now_utc else
              "insufficient_price_data" if len(chosen) < remaining else "planned")
    return {
        "status": status,
        "target_hours": TARGET_HOURS,
        "max_interval_hours": MAX_INTERVAL_HOURS,
        "last_completed_at": completed.astimezone(TZ).isoformat(timespec="minutes"),
        "deadline": deadline.astimezone(TZ).isoformat(timespec="minutes"),
        "heated_hours": len(already),
        "remaining_hours": remaining,
        "selected": [{"start": p["start"], "price": p["price"],
                      "source": p["source"]} for p in chosen],
        "estimated_average_price": (round(sum(p["price"] for p in chosen) / len(chosen), 3)
                                    if chosen else None),
        "note": "Advisory forecast; actual completed hours must be reported by Shelly.",
    }
