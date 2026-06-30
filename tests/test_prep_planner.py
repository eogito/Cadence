"""Tests for the multi-day prep planner (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_schedule_blocks_has_plan_group(self):
        from src.models.schedule_block import ScheduleBlock
        self.assertIn("plan_group", ScheduleBlock.__table__.columns)


if __name__ == "__main__":
    unittest.main()
