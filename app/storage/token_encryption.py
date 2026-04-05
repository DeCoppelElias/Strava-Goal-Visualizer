from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryption:
    _ENCRYPTION_PREFIX = "enc:v1:"

    def __init__(self, token_encryption_key: str | None) -> None:
        self._token_cipher: Fernet | None = None
        key = token_encryption_key.strip() if isinstance(token_encryption_key, str) else ""
        if key:
            try:
                self._token_cipher = Fernet(key.encode("utf-8"))
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "TOKEN_ENCRYPTION_KEY is invalid. Use a urlsafe base64 Fernet key."
                ) from exc

    def encrypt(self, token: str | None) -> str | None:
        if token is None:
            return None
        if self._token_cipher is None:
            return token
        encrypted = self._token_cipher.encrypt(token.encode("utf-8")).decode("utf-8")
        return f"{self._ENCRYPTION_PREFIX}{encrypted}"

    def decrypt(self, token: str | None) -> str | None:
        if token is None:
            return None
        if not token.startswith(self._ENCRYPTION_PREFIX):
            # Backward compatibility for pre-encryption plaintext rows.
            return token
        if self._token_cipher is None:
            raise ValueError(
                "Encrypted OAuth token found but TOKEN_ENCRYPTION_KEY is not configured."
            )
        encrypted_payload = token[len(self._ENCRYPTION_PREFIX) :]
        try:
            return self._token_cipher.decrypt(encrypted_payload.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "OAuth token decryption failed. Check TOKEN_ENCRYPTION_KEY."
            ) from exc
