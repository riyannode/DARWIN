from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


def encrypt_connection_material(value: str, key: str) -> str:
    return Fernet(key.encode("utf-8")).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_connection_material(value: str, key: str) -> str:
    try:
        return Fernet(key.encode("utf-8")).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("connection material could not be decrypted") from exc
