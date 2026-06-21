"""Tests for the flexible daily schedule (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_schedule_blocks_table_registered(self):
        import src.models.schedule_block  # noqa: F401
        from src.database import Base
        self.assertIn("schedule_blocks", Base.metadata.tables)


if __name__ == "__main__":
    unittest.main()
