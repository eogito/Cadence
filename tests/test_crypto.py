"""Tests for token encryption (stdlib unittest)."""
import unittest

from src.services.crypto import encrypt_token, decrypt_token


class CryptoTests(unittest.TestCase):
    def test_round_trip(self):
        secret = '{"AccessToken": {"x": "y"}}'
        self.assertEqual(decrypt_token(encrypt_token(secret)), secret)

    def test_ciphertext_differs_from_plaintext(self):
        secret = "sensitive-token-cache"
        self.assertNotEqual(encrypt_token(secret), secret)

    def test_decrypt_garbage_returns_none(self):
        self.assertIsNone(decrypt_token("not-a-valid-fernet-token"))

    def test_decrypt_legacy_plaintext_returns_none(self):
        self.assertIsNone(decrypt_token('{"AccessToken": {}}'))


if __name__ == "__main__":
    unittest.main()
