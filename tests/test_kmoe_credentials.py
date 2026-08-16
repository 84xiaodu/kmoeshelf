from __future__ import annotations

import pytest

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.kmoe.credentials import (
    CredentialDecryptionError,
    decrypt_cookies,
    encrypt_cookies,
)


def settings(secret: str = "a" * 48) -> Settings:
    return Settings(app_secret_key=secret)


def test_cookie_encryption_round_trip_and_tamper_detection() -> None:
    token = encrypt_cookies(
        settings(),
        mirror="mox.moe",
        cookies={"session": "private-value"},
    )
    assert "private-value" not in token
    snapshot = decrypt_cookies(settings(), token)
    assert snapshot.mirror == "mox.moe"
    assert snapshot.cookies == {"session": "private-value"}

    with pytest.raises(CredentialDecryptionError):
        decrypt_cookies(settings(), token[:-1] + ("A" if token[-1] != "A" else "B"))

    with pytest.raises(CredentialDecryptionError):
        decrypt_cookies(settings("b" * 48), token)
