"""Tests for per-user timezone handling (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_users_table_has_timezone_column(self):
        from src.models.user import User
        self.assertIn("timezone", User.__table__.columns)


class HelperTests(unittest.TestCase):
    def test_user_tz_defaults_to_utc(self):
        from src.services.calendar_dates import user_tz
        class U: timezone = None
        self.assertEqual(user_tz(U()), "UTC")

    def test_user_tz_returns_stored(self):
        from src.services.calendar_dates import user_tz
        class U: timezone = "Asia/Tokyo"
        self.assertEqual(user_tz(U()), "Asia/Tokyo")

    def test_local_day_range_edt(self):
        from src.services.calendar_dates import local_day_range
        start, end = local_day_range("2026-06-22", "America/New_York")
        self.assertEqual(start, "2026-06-22T04:00:00+00:00")
        self.assertEqual(end, "2026-06-23T04:00:00+00:00")

    def test_local_day_range_bad_tz_falls_back_utc(self):
        from src.services.calendar_dates import local_day_range
        start, end = local_day_range("2026-06-22", "Not/AZone")
        self.assertEqual(start, "2026-06-22T00:00:00+00:00")
        self.assertEqual(end, "2026-06-23T00:00:00+00:00")


class EventBodyTests(unittest.TestCase):
    def test_event_body_stamps_tz_and_strips_z(self):
        from src.services.outlook_calendar_service import OutlookCalendarService
        body = OutlookCalendarService._event_body(
            "Meet", "2026-06-22T09:00:00Z", "2026-06-22T10:00:00", "America/New_York"
        )
        self.assertEqual(body["start"], {"dateTime": "2026-06-22T09:00:00", "timeZone": "America/New_York"})
        self.assertEqual(body["end"], {"dateTime": "2026-06-22T10:00:00", "timeZone": "America/New_York"})
        self.assertEqual(body["subject"], "Meet")


if __name__ == "__main__":
    unittest.main()
