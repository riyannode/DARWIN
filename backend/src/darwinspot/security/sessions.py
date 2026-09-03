from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher

_password_hasher = PasswordHasher()


def issue_session_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_session_token(raw)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_owner_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except Exception:
        return False
