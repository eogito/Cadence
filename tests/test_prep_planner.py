"""Tests for the multi-day prep planner (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_schedule_blocks_has_plan_group(self):
        from src.models.schedule_block import ScheduleBlock
        self.assertIn("plan_group", ScheduleBlock.__table__.columns)


class AllocateTests(unittest.TestCase):
    def test_ramps_up(self):
        from src.services.prep_planner import allocate_per_day
        self.assertEqual(allocate_per_day(4, 600, 1000, ramp=True), [60, 120, 180, 240])

    def test_respects_cap(self):
        from src.services.prep_planner import allocate_per_day
        self.assertTrue(all(x <= 120 for x in allocate_per_day(4, 600, 120, ramp=True)))

    def test_even_when_no_ramp(self):
        from src.services.prep_planner import allocate_per_day
        self.assertEqual(allocate_per_day(3, 180, 1000, ramp=False), [60, 60, 60])

    def test_zero_guards(self):
        from src.services.prep_planner import allocate_per_day
        self.assertEqual(allocate_per_day(0, 600, 60), [])
        self.assertEqual(allocate_per_day(3, 0, 60), [0, 0, 0])


class PlaceSessionsTests(unittest.TestCase):
    def test_avoids_busy_and_splits(self):
        from src.services.prep_planner import place_sessions
        s = place_sessions(120, [(540, 600)], window=(480, 720), max_session=90, min_session=30)
        self.assertEqual(s, [(480, 60), (600, 60)])

    def test_shortfall_when_gaps_small(self):
        from src.services.prep_planner import place_sessions
        s = place_sessions(120, [(510, 720)], window=(480, 720), max_session=90, min_session=30)
        self.assertEqual(s, [(480, 30)])

    def test_returns_empty_below_min(self):
        from src.services.prep_planner import place_sessions
        self.assertEqual(place_sessions(20, [], window=(480, 720), min_session=30), [])


if __name__ == "__main__":
    unittest.main()
