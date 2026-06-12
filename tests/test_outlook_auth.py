"""Tests for Microsoft auth foundation (stdlib unittest)."""
import unittest

from src.config import settings


class ConfigTests(unittest.TestCase):
    def test_ms_authority_defaults_to_common(self):
        self.assertTrue(settings.ms_authority.endswith("/common"))

    def test_session_secret_is_present(self):
        self.assertTrue(settings.session_secret.get_secret_value())

    def test_ms_redirect_uri_present(self):
        self.assertIn("/auth/callback", settings.ms_redirect_uri)


if __name__ == "__main__":
    unittest.main()

from src.models.user import User


class UserModelTests(unittest.TestCase):
    def test_user_has_ms_columns(self):
        cols = User.__table__.columns
        self.assertIn("ms_token_cache", cols)
        self.assertIn("ms_account_id", cols)


import asyncio
import uuid
from starlette.requests import Request
from fastapi import HTTPException


def _make_request(session: dict) -> Request:
    return Request({"type": "http", "headers": [], "session": session})


class _FakeResult:
    def __init__(self, obj): self._obj = obj
    def scalars(self): return self
    def first(self): return self._obj


class _FakeDB:
    def __init__(self, obj): self._obj = obj
    async def execute(self, *args, **kwargs): return _FakeResult(self._obj)


class CurrentUserTests(unittest.TestCase):
    def test_no_session_raises_401(self):
        from src.api.deps import current_user
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(current_user(_make_request({}), db=_FakeDB(None)))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_user_raises_401(self):
        from src.api.deps import current_user
        sess = {"user_id": str(uuid.uuid4())}
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(current_user(_make_request(sess), db=_FakeDB(None)))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_session_returns_user(self):
        from src.api.deps import current_user
        u = User(email="x@example.com")
        u.id = uuid.uuid4()
        result = asyncio.run(current_user(_make_request({"user_id": str(u.id)}), db=_FakeDB(u)))
        self.assertIs(result, u)
