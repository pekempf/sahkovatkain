import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from hot_water_planner import plan_hot_water

TZ = ZoneInfo("Europe/Helsinki")
def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

class HotWaterTests(unittest.TestCase):
    def setUp(self):
        self.now = utc("2026-10-08T12:00:00Z")
        self.completed = "2026-10-07T06:00:00+03:00"
        self.state = {"last_completed_at": self.completed, "heated_hours": []}
        start = utc("2026-10-08T12:00:00Z")
        self.prices = {start + timedelta(hours=i): 20.0 for i in range(60)}
        self.transfer = lambda dt: 0.0

    def test_missing_state_never_produces_schedule(self):
        result = plan_hot_water(self.prices, {}, self.now, self.transfer)
        self.assertEqual(result["status"], "missing_heating_state")
        self.assertEqual(result["selected"], [])

    def test_cheapest_hours_can_cross_midnight(self):
        for h, price in [(8, 1), (9, 2), (10, 3), (11, 4)]:
            self.prices[utc("2026-10-08T12:00:00Z") + timedelta(hours=h)] = price
        result = plan_hot_water(self.prices, {}, self.now, self.transfer, self.state)
        self.assertEqual(result["status"], "planned")
        self.assertEqual([x["price"] for x in result["selected"]], [1, 2, 3, 4])

    def test_no_new_cycle_same_local_day(self):
        state = {"last_completed_at": "2026-10-08T05:00:00+03:00", "heated_hours": []}
        result = plan_hot_water(self.prices, {}, self.now, self.transfer, state)
        self.assertTrue(all(datetime.fromisoformat(x["start"]).date() >
                            datetime.fromisoformat(state["last_completed_at"]).date()
                            for x in result["selected"]))

    def test_already_heated_hours_reduce_remaining(self):
        state = {"last_completed_at": self.completed,
                 "heated_hours": ["2026-10-08T10:00:00+03:00", "2026-10-08T11:00:00+03:00"]}
        result = plan_hot_water(self.prices, {}, self.now, self.transfer, state)
        self.assertEqual(result["remaining_hours"], 2)
        self.assertEqual(len(result["selected"]), 2)

    def test_deadline_prevents_late_hours(self):
        result = plan_hot_water(self.prices, {}, self.now, self.transfer, self.state)
        deadline = datetime.fromisoformat(result["deadline"])
        self.assertTrue(all(datetime.fromisoformat(x["start"]) < deadline
                            for x in result["selected"]))

    def test_shelly_initial_330_seconds(self):
        state = {"last": 291450, "total": 330}
        result = plan_hot_water(self.prices, {}, self.now, self.transfer, state)
        self.assertEqual(result["status"], "initial_cycle_in_progress")
        self.assertEqual(result["heated_seconds"], 330)
        self.assertEqual(result["remaining_seconds"], 14070)
        self.assertEqual(result["selected"], [])

    def test_shelly_completed_cycle_and_partial_progress(self):
        state = {"last": 300000, "total": 330,
                 "last_completed": int(utc("2026-10-07T06:00:00Z").timestamp()),
                 "completed_count": 1}
        result = plan_hot_water(self.prices, {}, self.now, self.transfer, state)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["remaining_seconds"], 14070)
        self.assertEqual(result["remaining_hours"], 4)
        self.assertEqual(len(result["selected"]), 4)

    def test_shelly_deadline_blocks_late_hours(self):
        state = {"last": 300000, "total": 0,
                 "last_completed": int(utc("2026-10-06T06:00:00Z").timestamp())}
        result = plan_hot_water(self.prices, {}, self.now, self.transfer, state)
        deadline = datetime.fromisoformat(result["deadline"])
        self.assertTrue(all(datetime.fromisoformat(x["start"]) < deadline
                            for x in result["selected"]))

if __name__ == "__main__":
    unittest.main()
