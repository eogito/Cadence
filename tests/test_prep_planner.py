"""Tests for the multi-day prep planner (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_schedule_blocks_has_plan_group(self):
        from src.models.schedule_block import ScheduleBlock
        self.assertIn("plan_group", ScheduleBlock.__table__.columns)


class DistributeTests(unittest.TestCase):
    def test_uncapped_ramp_matches_ideal(self):
        from src.services.prep_planner import distribute
        self.assertEqual(distribute(600, [1000, 1000, 1000, 1000], ramp=True), [60, 120, 180, 240])

    def test_spills_full_budget_when_a_day_is_tight(self):
        from src.services.prep_planner import distribute
        out = distribute(600, [60, 1000, 1000], ramp=True)
        self.assertEqual(sum(out), 600)
        self.assertEqual(out[0], 60)
        self.assertTrue(out[2] >= out[1])

    def test_capacity_is_the_binding_limit(self):
        from src.services.prep_planner import distribute
        out = distribute(600, [60, 60, 60], ramp=True)
        self.assertEqual(sum(out), 180)
        self.assertTrue(all(x <= 60 for x in out))

    def test_even_when_no_ramp(self):
        from src.services.prep_planner import distribute
        self.assertEqual(distribute(180, [1000, 1000, 1000], ramp=False), [60, 60, 60])

    def test_zero_and_empty_guards(self):
        from src.services.prep_planner import distribute
        self.assertEqual(distribute(0, [100, 100]), [0, 0])
        self.assertEqual(distribute(100, []), [])
        self.assertTrue(all(v % 15 == 0 for v in distribute(600, [60, 1000, 1000])))


class DayCapacityTests(unittest.TestCase):
    def test_sums_usable_gaps(self):
        from src.services.prep_planner import day_capacity
        self.assertEqual(day_capacity([(480, 540), (600, 720)], 1000), 180)

    def test_ignores_gaps_below_min_session(self):
        from src.services.prep_planner import day_capacity
        self.assertEqual(day_capacity([(480, 500), (600, 720)], 1000), 120)

    def test_clamps_to_daily_cap(self):
        from src.services.prep_planner import day_capacity
        self.assertEqual(day_capacity([(480, 720)], 90), 90)

    def test_tail_below_min_is_not_counted(self):
        from src.services.prep_planner import day_capacity
        self.assertEqual(day_capacity([(480, 580)], 1000), 90)


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


class RequestModelTests(unittest.TestCase):
    def test_requests_have_no_email_field(self):
        from src.api.schedule import PrepPreviewRequest, PrepCommitRequest
        for model in (PrepPreviewRequest, PrepCommitRequest):
            self.assertNotIn("email", model.model_fields)
            self.assertNotIn("user_email", model.model_fields)


if __name__ == "__main__":
    unittest.main()
