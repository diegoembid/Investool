"""Cifrado de secretos guardados en base de datos."""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class SecretDecryptionError(Exception):
    pass


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> Fernet:
    key = get_settings().app_secret_key.get_secret_value()
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "APP_SECRET_KEY no tiene el formato correcto. Genera una nueva con "
            "`python -m app.cli generate-secret`"
        ) from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "No se puede descifrar: APP_SECRET_KEY ha cambiado desde que se guardó el dato"
        ) from exc
