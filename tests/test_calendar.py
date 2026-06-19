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


if __name__ == "__main__":
    unittest.main()
