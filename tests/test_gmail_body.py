"""Tests for Gmail body extraction (stdlib unittest — run: python -m unittest)."""
import base64
import unittest

from src.services.gmail_service import GmailService


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class DecodeBodyTests(unittest.TestCase):
    def test_plain_text_part(self):
        payload = {
            "mimeType": "text/plain",
            "body": {"data": _b64("Hello plain world")},
        }
        self.assertEqual(GmailService._decode_body(payload), "Hello plain world")

    def test_html_only_falls_back_to_stripped_text(self):
        """Regression: HTML-only emails (newsletters/promos) must not return empty."""
        html = "<html><body><p>Up to <b>30% off</b> tonight</p></body></html>"
        payload = {
            "mimeType": "multipart/alternative",
            "body": {},
            "parts": [{"mimeType": "text/html", "body": {"data": _b64(html)}}],
        }
        result = GmailService._decode_body(payload)
        self.assertIn("30% off", result)
        self.assertIn("tonight", result)
        self.assertNotIn("<", result)  # tags stripped

    def test_prefers_plain_over_html(self):
        payload = {
            "mimeType": "multipart/alternative",
            "body": {},
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("PLAIN VERSION")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML VERSION</p>")}},
            ],
        }
        self.assertEqual(GmailService._decode_body(payload).strip(), "PLAIN VERSION")

    def test_script_and_style_stripped(self):
        html = "<style>.x{color:red}</style><p>Real text</p><script>alert(1)</script>"
        self.assertEqual(GmailService._html_to_text(html), "Real text")

    def test_empty_payload_returns_empty(self):
        self.assertEqual(GmailService._decode_body({"mimeType": "text/plain", "body": {}}), "")


if __name__ == "__main__":
    unittest.main()
