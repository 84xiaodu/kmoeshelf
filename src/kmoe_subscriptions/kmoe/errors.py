from __future__ import annotations


class KmoeError(Exception):
    code = "kmoe_error"


class AuthenticationExpired(KmoeError):
    code = "auth_expired"


class InvalidCredentials(KmoeError):
    code = "invalid_credentials"


class AccountDisabled(KmoeError):
    code = "account_disabled"


class AuthenticationChallenge(KmoeError):
    code = "auth_challenge"


class QuotaExhausted(KmoeError):
    code = "quota_exhausted"


class SiteChanged(KmoeError):
    code = "site_changed"


class NetworkError(KmoeError):
    code = "network_error"


class NotFound(KmoeError):
    code = "not_found"


class RateLimited(KmoeError):
    code = "rate_limited"


class MirrorExhausted(NetworkError):
    code = "mirror_unavailable"

    def __init__(self, mirrors: tuple[str, ...]) -> None:
        self.mirrors = mirrors
        super().__init__(f"All Kmoe mirrors failed: {', '.join(mirrors)}")
