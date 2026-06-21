"""Tests for the flexible daily schedule (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_schedule_blocks_table_registered(self):
        import src.models.schedule_block  # noqa: F401
        from src.database import Base
        self.assertIn("schedule_blocks", Base.metadata.tables)


class TimeHelperTests(unittest.TestCase):
    def test_parse_time_to_minute_variants(self):
        from src.services.schedule_ai import parse_time_to_minute
        self.assertEqual(parse_time_to_minute("9:00 AM"), 540)
        self.assertEqual(parse_time_to_minute("2:30 PM"), 870)
        self.assertEqual(parse_time_to_minute("12:00 AM"), 0)
        self.assertEqual(parse_time_to_minute("12:15 PM"), 735)
        self.assertEqual(parse_time_to_minute("14:30"), 870)  # 24h
        self.assertIsNone(parse_time_to_minute("whenever"))

    def test_free_gaps_basic(self):
        from src.services.schedule_ai import free_gaps
        # window 8:00(480)-12:00(720); busy 9:00-10:00 and 11:00-11:30
        gaps = free_gaps(480, 720, [(540, 600), (660, 690)])
        self.assertEqual(gaps, [(480, 540), (600, 660), (690, 720)])

    def test_free_gaps_merges_overlaps(self):
        from src.services.schedule_ai import free_gaps
        gaps = free_gaps(480, 720, [(500, 560), (550, 600)])
        self.assertEqual(gaps, [(480, 500), (600, 720)])


if __name__ == "__main__":
    unittest.main()
