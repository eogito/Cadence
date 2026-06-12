"""Tests for Outlook mail read path (stdlib unittest)."""
import unittest

from src.services.text_utils import html_to_text


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags(self):
        out = html_to_text("<html><body><p>Hello <b>world</b></p></body></html>")
        self.assertIn("Hello", out)
        self.assertIn("world", out)
        self.assertNotIn("<", out)

    def test_drops_script_and_style(self):
        out = html_to_text("<style>.x{color:red}</style><p>Real</p><script>alert(1)</script>")
        self.assertEqual(out, "Real")


import asyncio
from src.models.user import User
from src.services.ms_auth import MicrosoftAuthService


class TokenProviderTests(unittest.TestCase):
    def test_no_cache_raises_permission_error(self):
        u = User(email="x@example.com")
        u.ms_token_cache = None
        with self.assertRaises(PermissionError):
            asyncio.run(MicrosoftAuthService.get_access_token(u))


from src.services.outlook_mail_service import OutlookMailService


class ClassificationFilterTests(unittest.TestCase):
    def test_focused_only(self):
        self.assertEqual(OutlookMailService._allowed_classifications(["focused"]), {"focused"})

    def test_both_is_none(self):
        self.assertIsNone(OutlookMailService._allowed_classifications(["focused", "other"]))

    def test_empty_is_empty_set(self):
        self.assertEqual(OutlookMailService._allowed_classifications([]), set())

    def test_unknown_values_ignored(self):
        self.assertEqual(OutlookMailService._allowed_classifications(["focused", "bogus"]), {"focused"})


class SendMailPayloadTests(unittest.TestCase):
    def test_sendmail_payload_shape(self):
        payload = OutlookMailService._sendmail_payload("a@b.com", "Hi", "Body text")
        self.assertEqual(payload["message"]["subject"], "Hi")
        self.assertEqual(payload["message"]["body"], {"contentType": "Text", "content": "Body text"})
        self.assertEqual(
            payload["message"]["toRecipients"],
            [{"emailAddress": {"address": "a@b.com"}}],
        )
        self.assertTrue(payload["saveToSentItems"])


from src.services.outlook_calendar_service import OutlookCalendarService


class CalendarPayloadTests(unittest.TestCase):
    def test_event_body_strips_trailing_z(self):
        body = OutlookCalendarService._event_body("Sync", "2026-06-15T14:00:00Z", "2026-06-15T15:00:00Z")
        self.assertEqual(body["subject"], "Sync")
        self.assertEqual(body["start"], {"dateTime": "2026-06-15T14:00:00", "timeZone": "UTC"})
        self.assertEqual(body["end"], {"dateTime": "2026-06-15T15:00:00", "timeZone": "UTC"})


if __name__ == "__main__":
    unittest.main()
