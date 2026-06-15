"""Deployment config: DB URL normalization + scheduler default (stdlib unittest)."""
import unittest

from src.database import _normalize_async_url
from src.config import settings


class DeploymentConfigTests(unittest.TestCase):
    def test_plain_postgres_url_gets_asyncpg_driver(self):
        self.assertEqual(
            _normalize_async_url("postgresql://u:p@host:5432/db"),
            "postgresql+asyncpg://u:p@host:5432/db",
        )

    def test_asyncpg_url_unchanged(self):
        url = "postgresql+asyncpg://u:p@host:5432/db"
        self.assertEqual(_normalize_async_url(url), url)

    def test_run_scheduler_defaults_true(self):
        self.assertTrue(settings.run_scheduler)


if __name__ == "__main__":
    unittest.main()
