from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import Settings


_passwords = PasswordHasher()


def hash_password(password: str) -> str:
    return _passwords.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _passwords.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def token_hash(settings: Settings, token: str) -> str:
    return hmac.new(
        settings.app_secret_key.get_secret_value().encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class NewSession:
    token: str
    token_hash: str
    csrf_token: str
    expires_at: datetime


def new_session(settings: Settings) -> NewSession:
    token = secrets.token_urlsafe(32)
    return NewSession(
        token=token,
        token_hash=token_hash(settings, token),
        csrf_token=secrets.token_urlsafe(24),
        expires_at=utcnow() + timedelta(hours=settings.session_hours),
    )

