from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import Settings
from .errors import KmoeError


class CredentialDecryptionError(KmoeError):
    code = "credential_decryption_failed"


@dataclass(frozen=True, slots=True)
class CookieSnapshot:
    mirror: str
    cookies: dict[str, str]


def encrypt_cookies(
    settings: Settings, *, mirror: str, cookies: dict[str, str]
) -> str:
    payload = json.dumps(
        {"version": 1, "mirror": mirror, "cookies": cookies},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _fernet(settings).encrypt(payload).decode()


def decrypt_cookies(settings: Settings, token: str) -> CookieSnapshot:
    try:
        payload = json.loads(_fernet(settings).decrypt(token.encode()))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CredentialDecryptionError("Stored Kmoe credential cannot be decrypted") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or not isinstance(payload.get("mirror"), str)
        or not isinstance(payload.get("cookies"), dict)
        or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in payload["cookies"].items()
        )
    ):
        raise CredentialDecryptionError("Stored Kmoe credential has an invalid shape")
    return CookieSnapshot(mirror=payload["mirror"], cookies=payload["cookies"])


def _fernet(settings: Settings) -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"kmoe-subscriptions-cookie-v1",
        info=b"kmoe-cookie-encryption",
    ).derive(settings.app_secret_key.get_secret_value().encode())
    return Fernet(base64.urlsafe_b64encode(key))

