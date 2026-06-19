"""Tests for calendar date helpers + mail range filter (stdlib unittest)."""
import unittest
from src.services.calendar_dates import month_range, day_range, parse_graph_dt


class DateHelperTests(unittest.TestCase):
    def test_month_range_mid_year(self):
        self.assertEqual(
            month_range(2026, 6),
            ("2026-06-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00"),
        )

    def test_month_range_december_rolls_year(self):
        self.assertEqual(
            month_range(2026, 12),
            ("2026-12-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00"),
        )

    def test_day_range(self):
        self.assertEqual(
            day_range("2026-06-13"),
            ("2026-06-13T00:00:00+00:00", "2026-06-14T00:00:00+00:00"),
        )

    def test_parse_graph_dt_handles_z(self):
        dt = parse_graph_dt("2026-06-13T14:30:00Z")
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour), (2026, 6, 13, 14))

    def test_parse_graph_dt_bad_value(self):
        self.assertIsNone(parse_graph_dt("not-a-date"))


from src.services.outlook_mail_service import OutlookMailService


class ReceivedRangeTests(unittest.TestCase):
    def _msgs(self):
        return [
            {"id": "a", "receivedDateTime": "2026-06-13T09:00:00Z"},
            {"id": "b", "receivedDateTime": "2026-06-12T23:59:00Z"},
            {"id": "c", "receivedDateTime": "2026-06-14T00:00:00Z"},
        ]

    def test_filters_to_the_day(self):
        kept = OutlookMailService._in_received_range(
            self._msgs(), "2026-06-13T00:00:00+00:00", "2026-06-14T00:00:00+00:00"
        )
        self.assertEqual([m["id"] for m in kept], ["a"])


from unittest.mock import AsyncMock, patch
from src.api import calendar as cal
from src.api.calendar import PushScheduleRequest, ScheduleBlockPush


class TriageThreadCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cal._TRIAGE_THREADS.clear()

    async def test_reuses_cached_thread_when_state_exists(self):
        cal._TRIAGE_THREADS[("u@e.com", "m1")] = "tid1"
        snap = type("S", (), {"values": {"classification": {}}})()
        app = type("A", (), {"aget_state": AsyncMock(return_value=snap)})()
        with patch.object(cal, "process_new_email", new=AsyncMock()) as pne:
            tid = await cal._triage_thread(app, "u@e.com", "m1")
        self.assertEqual(tid, "tid1")
        pne.assert_not_called()

    async def test_creates_and_caches_when_uncached(self):
        app = type("A", (), {"aget_state": AsyncMock(return_value=None)})()
        with patch.object(cal, "process_new_email", new=AsyncMock(return_value="tidNew")) as pne:
            tid = await cal._triage_thread(app, "u@e.com", "m2")
        self.assertEqual(tid, "tidNew")
        self.assertEqual(cal._TRIAGE_THREADS[("u@e.com", "m2")], "tidNew")
        pne.assert_awaited_once()


class PushScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_failed_blocks(self):
        req = PushScheduleRequest(blocks=[
            ScheduleBlockPush(summary="ok", start_time="2026-06-19T09:00:00", end_time="2026-06-19T09:30:00"),
            ScheduleBlockPush(summary="bad", start_time="2026-06-19T10:00:00", end_time="2026-06-19T10:30:00"),
        ])

        def fake_create(user, summary, start, end):
            if summary == "bad":
                raise RuntimeError("graph 500")
            return {"link": "http://event"}

        with patch.object(cal.OutlookCalendarService, "create_event", new=AsyncMock(side_effect=fake_create)):
            res = await cal.push_schedule(req, user=object())
        self.assertEqual(res["requested"], 2)
        self.assertEqual(res["created"], 1)
        self.assertEqual(res["failed"], 1)
        self.assertEqual(len(res["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
