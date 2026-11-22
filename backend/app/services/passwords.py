"""Password hashing helpers backed by Argon2id via pwdlib."""

from __future__ import annotations

from pwdlib import PasswordHash

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return a salted, adaptive password hash (Argon2id in this deployment)."""
    if not password or not password.strip():
        raise ValueError("Password must not be empty.")
    return _password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str | None) -> bool:
    """Constant-time password verification; malformed/legacy hashes fail closed."""
    if not password or not encoded_hash:
        return False
    try:
        return _password_hasher.verify(password, encoded_hash)
    except (ValueError, TypeError):
        return False
