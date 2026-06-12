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
        self.assertEqual(
            OutlookMailService.build_classification_filter(["focused"]),
            "inferenceClassification eq 'focused'",
        )

    def test_both_is_empty(self):
        self.assertEqual(OutlookMailService.build_classification_filter(["focused", "other"]), "")

    def test_empty_is_sentinel(self):
        self.assertEqual(
            OutlookMailService.build_classification_filter([]),
            OutlookMailService.NO_MAIL_FILTER,
        )

    def test_unknown_values_ignored(self):
        self.assertEqual(
            OutlookMailService.build_classification_filter(["focused", "bogus"]),
            "inferenceClassification eq 'focused'",
        )


if __name__ == "__main__":
    unittest.main()
