"""Tests for email classification schema, routing, and graph wiring (stdlib unittest)."""
import unittest

from src.workflows.state import EmailClassification, EmailAnalysis


class SchemaTests(unittest.TestCase):
    def test_classification_defaults(self):
        c = EmailClassification(category="notification")
        self.assertEqual(c.category, "notification")
        self.assertEqual(c.reason, "")

    def test_analysis_has_needs_task(self):
        a = EmailAnalysis()
        self.assertFalse(a.needs_task)


if __name__ == "__main__":
    unittest.main()
