"""Tests for Gmail section tracking (stdlib unittest)."""
import unittest

from src.models.email_preferences import VALID_CATEGORIES, DEFAULT_CATEGORIES


class ConstantsTests(unittest.TestCase):
    def test_valid_categories_are_focused_other(self):
        self.assertEqual(set(VALID_CATEGORIES), {"focused", "other"})

    def test_default_is_focused(self):
        self.assertEqual(DEFAULT_CATEGORIES, ["focused"])

    def test_default_is_subset_of_valid(self):
        self.assertTrue(set(DEFAULT_CATEGORIES).issubset(set(VALID_CATEGORIES)))


from src.services.email_preferences_service import invalid_categories


class ValidationTests(unittest.TestCase):
    def test_invalid_categories_detected(self):
        self.assertEqual(invalid_categories(["focused", "bogus", "x"]), ["bogus", "x"])

    def test_all_valid_returns_empty(self):
        self.assertEqual(invalid_categories(DEFAULT_CATEGORIES), [])


if __name__ == "__main__":
    unittest.main()
