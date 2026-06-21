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


from unittest.mock import AsyncMock, patch


class RequestModelTests(unittest.TestCase):
    def test_requests_have_no_email_field(self):
        from src.api.schedule import CreateBlockRequest, UpdateBlockRequest, GenerateRequest
        for model in (CreateBlockRequest, UpdateBlockRequest, GenerateRequest):
            self.assertNotIn("email", model.model_fields)
            self.assertNotIn("user_email", model.model_fields)


class BlockIsoTests(unittest.TestCase):
    def test_block_to_iso(self):
        from src.api.schedule import _block_to_iso
        from datetime import date
        s, e = _block_to_iso(date(2026, 6, 20), 540, 90)  # 9:00 + 90m
        self.assertEqual(s, "2026-06-20T09:00:00")
        self.assertEqual(e, "2026-06-20T10:30:00")

    def test_iso_to_minute(self):
        from src.api.schedule import _iso_to_minute
        self.assertEqual(_iso_to_minute("2026-06-20T14:30:00Z"), 870)
        self.assertIsNone(_iso_to_minute(None))


class PushIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_block_skips_when_already_pushed(self):
        from src.api import schedule as sched

        class FakeBlock:
            outlook_event_id = "abc"
        with patch.object(sched, "_get_owned", new=AsyncMock(return_value=FakeBlock())), \
             patch.object(sched.OutlookCalendarService, "create_event", new=AsyncMock()) as ce:
            out = await sched.push_block("id", user=object(), db=object())
        self.assertEqual(out, {"pushed": False, "already": True})
        ce.assert_not_called()


if __name__ == "__main__":
    unittest.main()
