"""Tests for per-user timezone handling (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_users_table_has_timezone_column(self):
        from src.models.user import User
        self.assertIn("timezone", User.__table__.columns)


if __name__ == "__main__":
    unittest.main()
