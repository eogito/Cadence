from cryptography.fernet import Fernet, InvalidToken
from src.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.token_encryption_key.get_secret_value().encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token-cache string for storage at rest."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str | None:
    """Decrypt a stored token cache. Returns None if it can't be decrypted
    (wrong/rotated key, corruption, or a legacy plaintext value)."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
