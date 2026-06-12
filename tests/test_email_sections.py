"""Tests for Gmail section tracking (stdlib unittest)."""
import unittest

from src.models.email_preferences import VALID_CATEGORIES, DEFAULT_CATEGORIES


class ConstantsTests(unittest.TestCase):
    def test_valid_categories_contains_required_entries(self):
        for cat in ("primary", "social", "promotions", "updates", "forums"):
            self.assertIn(cat, VALID_CATEGORIES)

    def test_default_is_primary_and_updates(self):
        self.assertEqual(DEFAULT_CATEGORIES, ["primary", "updates"])

    def test_default_is_subset_of_valid(self):
        self.assertTrue(set(DEFAULT_CATEGORIES).issubset(set(VALID_CATEGORIES)))


from src.services.gmail_service import GmailService


class CategoryFilterTests(unittest.TestCase):
    def test_empty_is_none_sentinel(self):
        self.assertEqual(GmailService.build_category_filter([]), "category:__none__")

    def test_single(self):
        self.assertEqual(GmailService.build_category_filter(["primary"]), "category:primary")

    def test_two(self):
        self.assertEqual(
            GmailService.build_category_filter(["primary", "updates"]),
            "(category:primary OR category:updates)",
        )

    def test_all_five_is_empty(self):
        self.assertEqual(GmailService.build_category_filter(VALID_CATEGORIES), "")

    def test_invalid_values_filtered_out(self):
        self.assertEqual(GmailService.build_category_filter(["primary", "bogus"]), "category:primary")


from src.services.email_preferences_service import invalid_categories


class ValidationTests(unittest.TestCase):
    def test_invalid_categories_detected(self):
        self.assertEqual(invalid_categories(["primary", "bogus", "x"]), ["bogus", "x"])

    def test_all_valid_returns_empty(self):
        self.assertEqual(invalid_categories(DEFAULT_CATEGORIES), [])


if __name__ == "__main__":
    unittest.main()
